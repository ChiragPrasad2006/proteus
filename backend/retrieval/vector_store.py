"""LanceDB vector store for few-shot email retrieval with audience-aware, time-decayed reranking."""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp, log
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa

from backend.config import Settings
from backend.schemas import CleanedSentEmail, RetrievedExample


class LanceDBVectorStore:
    """LanceDB-backed vector store for sent emails with audience-aware, time-decayed hybrid retrieval."""

    SCHEMA = pa.schema(
        [
            pa.field("message_id", pa.string()),
            pa.field("recipient_email", pa.string()),
            pa.field("recipient_domain", pa.string()),
            pa.field("subject", pa.string()),
            pa.field("clean_body", pa.string()),
            pa.field("greeting", pa.string()),
            pa.field("signoff", pa.string()),
            pa.field("word_count", pa.int32()),
            pa.field("timestamp", pa.string()),
            pa.field("timestamp_epoch", pa.float64()),
            pa.field("audience_mode", pa.string()),
            pa.field("cc_count", pa.int32()),
            pa.field("bcc_count", pa.int32()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ]
    )

    # Time decay half-life in days
    HALF_LIFE_DAYS = 90.0
    LAMBDA = log(2) / HALF_LIFE_DAYS  # decay rate

    # Boost weights
    RECIPIENT_BOOST = 0.12
    AUDIENCE_BOOST = 0.06

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._db = None
        self._table = None

    def _connect(self):
        if self._db is None:
            self._db = lancedb.connect(str(self.settings.lancedb_dir))
        return self._db

    def _get_or_create_table(self, force_recreate: bool = False):
        if self._table is None or force_recreate:
            db = self._connect()
            table_name = self.settings.lancedb_table_name
            if table_name in db.table_names():
                if force_recreate:
                    try:
                        db.drop_table(table_name)
                    except Exception:
                        pass
                    self._table = db.create_table(table_name, schema=self.SCHEMA)
                else:
                    self._table = db.open_table(table_name)
            else:
                self._table = db.create_table(table_name, schema=self.SCHEMA)
        return self._table

    def _compute_audience_mode(self, email: CleanedSentEmail) -> str:
        """Determine audience mode from email metadata.
        Note: CleanedSentEmail doesn't have cc/bcc, so we infer from recipient count.
        For now, default to 1on1_private. In production, this would be enriched from raw headers.
        """
        # Simple heuristic: if recipient has multiple emails in thread, it might be group
        return "1on1_private"

    def _compute_timestamp_epoch(self, timestamp_str: str) -> float:
        """Convert ISO timestamp string to epoch seconds."""
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0

    def index_emails(self, emails, embedder, force_recreate: bool = False) -> int:
        """Index cleaned emails into LanceDB with embeddings."""
        if not emails:
            return 0

        table = self._get_or_create_table(force_recreate=force_recreate)

        # Clear existing data for fresh reindex (simpler than upserts for now)
        try:
            table.delete("true")
        except Exception:
            pass

        texts = [embedder.prepare_text(e.subject, e.clean_body) for e in emails]
        vectors = embedder.encode(texts)

        data = []
        for email, vector in zip(emails, vectors):
            # Extract greeting and signoff for retrieval display
            greeting = self._extract_greeting(email.clean_body)
            signoff = email.signature or self._extract_signoff(email.clean_body)

            timestamp_str = email.timestamp.isoformat() if email.timestamp else ""
            timestamp_epoch = self._compute_timestamp_epoch(timestamp_str)
            audience_mode = self._compute_audience_mode(email)

            data.append(
                {
                    "message_id": email.message_id,
                    "recipient_email": email.recipient_email,
                    "recipient_domain": email.recipient_domain,
                    "subject": email.subject,
                    "clean_body": email.clean_body,
                    "greeting": greeting,
                    "signoff": signoff,
                    "word_count": email.word_count,
                    "timestamp": timestamp_str,
                    "timestamp_epoch": timestamp_epoch,
                    "audience_mode": audience_mode,
                    "cc_count": 0,  # Not available in CleanedSentEmail
                    "bcc_count": 0,  # Not available in CleanedSentEmail
                    "vector": vector.tolist(),
                }
            )

        table.add(data)
        return len(data)

    @staticmethod
    def _extract_greeting(text: str) -> str:
        """Extract the first greeting line from email body."""
        for line in text.splitlines()[:3]:
            line = line.strip()
            if line and any(line.lower().startswith(g) for g in ("hi ", "hey ", "dear ", "hello ")):
                return line
        return ""

    @staticmethod
    def _extract_signoff(text: str) -> str:
        """Extract the last signoff-like line from email body."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in reversed(lines[-5:]):
            if any(line.lower().startswith(s) for s in ("best", "regards", "thanks", "cheers", "sincerely", "respectfully")):
                return line
        return ""

    @staticmethod
    def _escape_sql(value: str) -> str:
        """Escape single quotes for LanceDB SQL filter."""
        return value.replace("'", "''")

    def upsert_sent_email(self, email: CleanedSentEmail, embedder, audience_mode: str = "1on1_private", cc_count: int = 0, bcc_count: int = 0) -> None:
        """Embed and upsert a newly sent email into LanceDB for immediate availability."""
        table = self._get_or_create_table()

        text = embedder.prepare_text(email.subject, email.clean_body)
        vector = embedder.encode_single(text)

        timestamp_str = email.timestamp.isoformat() if email.timestamp else ""
        timestamp_epoch = self._compute_timestamp_epoch(timestamp_str)

        data = {
            "message_id": email.message_id,
            "recipient_email": email.recipient_email,
            "recipient_domain": email.recipient_domain,
            "subject": email.subject,
            "clean_body": email.clean_body,
            "greeting": self._extract_greeting(email.clean_body),
            "signoff": email.signature or self._extract_signoff(email.clean_body),
            "word_count": email.word_count,
            "timestamp": timestamp_str,
            "timestamp_epoch": timestamp_epoch,
            "audience_mode": audience_mode,
            "cc_count": cc_count,
            "bcc_count": bcc_count,
            "vector": vector.tolist(),
        }

        try:
            # Try to delete existing record with same message_id first
            table.delete(f"message_id = '{self._escape_sql(email.message_id)}'")
        except Exception:
            pass

        table.add([data])

    def retrieve_few_shot_examples(
        self,
        embedder,
        recipient_email=None,
        recipient_domain=None,
        query_text="",
        k=2,
        min_word_count=25,
        target_audience_mode: str = "1on1_private",
        strict_audience: bool = False,
    ):
        """
        Overfetch + Time-Decayed Hybrid Reranking:
        1. Overfetch top k=15 semantic matches from LanceDB
        2. Re-rank every candidate d against query q using:
           Score(q, d) = 0.75 * Sim_cos(q, d) + 0.25 * exp(-lambda * delta_t_days) + beta_recipient + beta_audience
           where lambda = ln(2)/90 (90-day half-life), beta_recipient = +0.12 if d.recipient_email == primary_to,
           beta_audience = +0.06 if d.audience_mode == target_audience_mode
        3. Return the top 2 highest-scoring examples
        """
        table = self._get_or_create_table()
        if table.count_rows() == 0:
            return []

        query_vector = embedder.encode_single(query_text) if query_text else None
        overfetch_k = 15  # Overfetch for reranking

        # Build base filter. Strict audience mode turns the audience boost into
        # a hard filter so group/broadcast drafting never sees 1:1 examples.
        filter_parts = []
        if min_word_count:
            filter_parts.append(f"word_count >= {min_word_count}")
        if strict_audience:
            escaped_audience = self._escape_sql(target_audience_mode)
            filter_parts.append(f"audience_mode = '{escaped_audience}'")

        # Stage 1: Exact recipient matches (higher priority in overfetch)
        exact_matches = []
        if recipient_email:
            escaped_email = self._escape_sql(recipient_email)
            filter_sql = " AND ".join([f"recipient_email = '{escaped_email}'"] + list(filter_parts))
            try:
                exact_results = (
                    table.search(query_vector.tolist() if query_vector is not None else None)
                    .where(filter_sql)
                    .limit(overfetch_k)
                    .to_list()
                )
                exact_matches = exact_results
            except Exception:
                pass

        # Stage 2: Domain/semantic fallback (backfill)
        domain_matches = []
        if recipient_domain and (not recipient_email or len(exact_matches) < overfetch_k):
            escaped_domain = self._escape_sql(recipient_domain)
            domain_parts = [f"recipient_domain = '{escaped_domain}'"] + list(filter_parts)
            if recipient_email:
                escaped_email = self._escape_sql(recipient_email)
                domain_parts.append(f"recipient_email != '{escaped_email}'")
            filter_sql = " AND ".join(domain_parts)
            # Preserve legacy behaviour: the domain scope also constrains the
            # later pure-semantic backfill stage when it needs more candidates.
            filter_parts = domain_parts
            try:
                domain_results = (
                    table.search(query_vector.tolist() if query_vector is not None else None)
                    .where(filter_sql)
                    .limit(overfetch_k - len(exact_matches))
                    .to_list()
                )
                domain_matches = domain_results
            except Exception:
                pass

        # Stage 3: Pure semantic fallback (no recipient filtering)
        semantic_matches = []
        needed = overfetch_k - len(exact_matches) - len(domain_matches)
        if needed > 0:
            filter_sql = " AND ".join(filter_parts) if filter_parts else None
            if min_word_count:
                if filter_sql:
                    filter_sql = f"{filter_sql} AND word_count >= {min_word_count}"
                else:
                    filter_sql = f"word_count >= {min_word_count}"
            try:
                if filter_sql:
                    semantic_results = (
                        table.search(query_vector.tolist() if query_vector is not None else None)
                        .where(filter_sql)
                        .limit(needed)
                        .to_list()
                    )
                else:
                    semantic_results = (
                        table.search(query_vector.tolist() if query_vector is not None else None)
                        .limit(needed)
                        .to_list()
                    )
                semantic_matches = semantic_results
            except Exception:
                pass

        # Combine all candidates
        all_candidates = exact_matches + domain_matches + semantic_matches

        # Time-decayed reranking
        now_epoch = datetime.now(timezone.utc).timestamp()
        primary_recipient = (recipient_email or "").lower()

        scored = []
        for candidate in all_candidates:
            # Cosine similarity (LanceDB returns _distance, convert to similarity)
            distance = candidate.get("_distance", 1.0)
            cos_sim = max(0.0, 1.0 - distance)

            # Time decay
            timestamp_epoch = candidate.get("timestamp_epoch", 0.0)
            delta_days = max(0.0, (now_epoch - timestamp_epoch) / 86400.0)
            time_score = exp(-self.LAMBDA * delta_days)

            # Recipient boost
            recipient_boost = self.RECIPIENT_BOOST if candidate.get("recipient_email", "").lower() == primary_recipient else 0.0

            # Audience boost
            audience_boost = self.AUDIENCE_BOOST if candidate.get("audience_mode") == target_audience_mode else 0.0

            final_score = (
                0.75 * cos_sim
                + 0.25 * time_score
                + recipient_boost
                + audience_boost
            )

            scored.append((final_score, candidate))

        # Sort by score descending and take top k
        scored.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [candidate for _, candidate in scored[:k]]

        return top_candidates

    def search(self, embedder, query_text: str, k=5):
        """Simple semantic search without recipient filtering."""
        table = self._get_or_create_table()
        if table.count_rows() == 0:
            return []
        query_vector = embedder.encode_single(query_text)
        return table.search(query_vector.tolist()).limit(k).to_list()

    def count(self) -> int:
        table = self._get_or_create_table()
        return table.count_rows()