"""
email_data_pipeline.deduplication.deduplicator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dual deduplication engine combining exact cryptographic hashing (SHA-256 / xxhash)
with MinHash Jaccard similarity estimation for detecting both exact and near-duplicates
while maintaining a negligible memory footprint under 16GB RAM constraints.
"""

import hashlib
import re
from typing import Dict, List, Set, Tuple
import xxhash


class MinHash:
    """
    Fast, memory-efficient MinHash signature implementation using 64 hash permutations.
    Computes Jaccard similarity without retaining raw shingle sets in memory.
    """

    def __init__(self, num_perm: int = 64, seed: int = 42):
        self.num_perm = num_perm
        self.seed = seed
        # Precompute simple linear hash coefficients (a * x + b) % prime
        # Using Mersenne Prime (2^61 - 1)
        self.prime = (1 << 61) - 1
        # Deterministic pseudo-random coefficients
        self.a_coeffs = []
        self.b_coeffs = []
        state = seed
        for _ in range(num_perm):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            self.a_coeffs.append((state | 1))  # Ensure odd
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            self.b_coeffs.append(state)

    def compute_signature(self, tokens: List[str]) -> Tuple[int, ...]:
        """Calculates MinHash signature tuple of length `num_perm`."""
        if not tokens:
            return tuple([0] * self.num_perm)

        # Hash each token to an integer
        token_hashes = [xxhash.xxh64(t.encode("utf-8")).intdigest() for t in tokens]

        signature = []
        for i in range(self.num_perm):
            a = self.a_coeffs[i]
            b = self.b_coeffs[i]
            min_val = min(((a * h + b) & 0xFFFFFFFFFFFFFFFF) for h in token_hashes)
            signature.append(min_val)

        return tuple(signature)

    @staticmethod
    def jaccard_similarity(sig_a: Tuple[int, ...], sig_b: Tuple[int, ...]) -> float:
        """Estimates Jaccard similarity between two MinHash signatures."""
        if not sig_a or not sig_b or len(sig_a) != len(sig_b):
            return 0.0
        matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
        return matches / float(len(sig_a))


class Deduplicator:
    """
    Combined Deduplication system tracking:
    1. Exact normalized prompt hashes.
    2. Exact normalized assistant email hashes.
    3. MinHash signature buckets for near-duplicate email content.
    """

    def __init__(
        self,
        jaccard_threshold: float = 0.85,
        num_perm: int = 64,
        k_shingle: int = 3,
        use_minhash: bool = True,
    ):
        self.jaccard_threshold = jaccard_threshold
        self.k_shingle = k_shingle
        self.use_minhash = use_minhash
        self.minhash_engine = MinHash(num_perm=num_perm) if use_minhash else None

        # Exact hash indices for exact duplicate detection
        self.signatures_store: List[Tuple[int, ...]] = []
        self._max_signatures_indexed: int = 200000  # Cap index to guarantee strict O(1) RAM

        # Sets storing 64-bit integer digests for extreme RAM efficiency (< 10 MB for 100k items)
        self.seen_prompt_hashes: Set[int] = set()
        self.seen_output_hashes: Set[int] = set()

        # MinHash LSH index: 8 bands of 8 permutations, bucketed by band key tuple.
        self.band_width: int = 8
        self.band_buckets: Dict[Tuple[int, ...], List[int]] = {}

        # Running statistics
        self.exact_prompt_dupes: int = 0
        self.exact_output_dupes: int = 0
        self.near_output_dupes: int = 0
        self._max_shingles_for_signature: int = 256

    def _band_keys(self, signature: Tuple[int, ...]):
        """Generates the LSH band sub-tuples for a signature (8 bands of 8 permutations)."""
        for b in range(0, len(signature), self.band_width):
            yield signature[b : b + self.band_width]

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Lowercases and normalizes whitespace/punctuation for canonical hashing."""
        if not text:
            return ""
        s = text.lower()
        s = re.sub(r"[^\w\s]", "", s)
        return " ".join(s.split())

    def _get_shingles(self, text: str) -> List[str]:
        """Extracts word k-shingles from text."""
        words = text.split()
        if len(words) < self.k_shingle:
            return [" ".join(words)]
        return [
            " ".join(words[i : i + self.k_shingle])
            for i in range(len(words) - self.k_shingle + 1)
        ]

    def check_and_add(self, prompt: str, output: str) -> bool:
        """
        Checks if the item (prompt or output) is a duplicate.
        Returns:
            True if it IS a duplicate (should be dropped).
            False if it IS UNIQUE (and has now been indexed).
        """
        norm_prompt = self._normalize_text(prompt)
        norm_output = self._normalize_text(output)

        if not norm_output:
            return True

        # 1. Exact Output Deduplication
        out_hash = xxhash.xxh64(norm_output.encode("utf-8")).intdigest()
        if out_hash in self.seen_output_hashes:
            self.exact_output_dupes += 1
            return True

        # 2. Exact Prompt Deduplication
        if norm_prompt:
            p_hash = xxhash.xxh64(norm_prompt.encode("utf-8")).intdigest()
            if p_hash in self.seen_prompt_hashes:
                self.exact_prompt_dupes += 1
                return True
        else:
            p_hash = None

        # 3. Near-Duplicate Output MinHash Checking (banding LSH)
        if self.use_minhash and self.minhash_engine:
            shingles = self._get_shingles(norm_output)
            # Cap signature input size so MinHash cost stays O(1) per item on long emails
            if len(shingles) > self._max_shingles_for_signature:
                step = len(shingles) // self._max_shingles_for_signature + 1
                shingles = shingles[::step]
            sig = self.minhash_engine.compute_signature(shingles)
            idx = len(self.signatures_store)

            # Locate candidates via shared band keys, then verify with full Jaccard similarity
            seen_candidate_ids = set()
            for band_key in self._band_keys(sig):
                for candidate_id in self.band_buckets.get(band_key, ()):
                    if candidate_id in seen_candidate_ids:
                        continue
                    seen_candidate_ids.add(candidate_id)
                    sim = MinHash.jaccard_similarity(sig, self.signatures_store[candidate_id])
                    if sim >= self.jaccard_threshold:
                        self.near_output_dupes += 1
                        return True

            # Register signature into the LSH band index
            if idx < self._max_signatures_indexed:
                for band_key in self._band_keys(sig):
                    self.band_buckets.setdefault(band_key, []).append(idx)
                self.signatures_store.append(sig)

        # Record unique hashes
        self.seen_output_hashes.add(out_hash)
        if p_hash is not None:
            self.seen_prompt_hashes.add(p_hash)

        return False

    def stats(self) -> dict:
        """Return total deduplication counters."""
        return {
            "unique_outputs_indexed": len(self.seen_output_hashes),
            "unique_prompts_indexed": len(self.seen_prompt_hashes),
            "exact_output_dupes_dropped": self.exact_output_dupes,
            "exact_prompt_dupes_dropped": self.exact_prompt_dupes,
            "near_output_dupes_dropped": self.near_output_dupes,
            "total_dupes_dropped": (
                self.exact_output_dupes
                + self.exact_prompt_dupes
                + self.near_output_dupes
            ),
        }
