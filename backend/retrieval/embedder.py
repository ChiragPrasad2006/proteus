"""Local sentence-transformer embedder for few-shot retrieval."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

_MODEL_LOCK = threading.Lock()
_SHARED_MODEL: Any | None = None

# Set HF_HOME before importing sentence_transformers to keep cache on D: drive
os.environ.setdefault("HF_HOME", str(Path("D:/huggingface_cache").expanduser().resolve()))

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional at test time
    SentenceTransformer = None  # type: ignore


class LocalEmbedder:
    """CPU-only embedder using all-MiniLM-L12-v2 (384-dim, normalized)."""

    MODEL_NAME = "sentence-transformers/all-MiniLM-L12-v2"
    DIM = 384
    MAX_WORDPIECES = 256

    def __init__(self, cache_dir: Path | None = None) -> None:
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers not installed")
        self.cache_dir = cache_dir or Path(os.environ.get("HF_HOME", "D:/huggingface_cache"))
        self._model: SentenceTransformer | None = None

    def load(self) -> None:
        """Load and reuse the shared CPU model (keeps GPU VRAM free for Qwen)."""
        global _SHARED_MODEL
        if self._model is not None:
            return
        with _MODEL_LOCK:
            if _SHARED_MODEL is None:
                _SHARED_MODEL = SentenceTransformer(
                    self.MODEL_NAME,
                    device="cpu",
                    cache_folder=str(self.cache_dir),
                )
            self._model = _SHARED_MODEL

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def is_model_cached(self) -> bool:
        """Check if model files exist locally without triggering a download."""
        hub_model_dir = self.cache_dir / "hub" / f"models--{self.MODEL_NAME.replace('/', '--')}"
        return hub_model_dir.exists() and any(hub_model_dir.iterdir())

    def encode(self, texts: list[str], normalize: bool = True) -> np.ndarray:
        """Encode texts to normalized float32 vectors."""
        if self._model is None:
            self.load()
        assert self._model is not None
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
            batch_size=32,
        )
        return vectors.astype(np.float32)

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        return self.encode([text], normalize=normalize)[0]

    @staticmethod
    def prepare_text(subject: str, clean_body: str, max_chars: int = 1000) -> str:
        """Prepare text for embedding: Subject + truncated clean body."""
        body = clean_body[:max_chars].strip()
        return f"Subject: {subject}\n{body}" if subject else body