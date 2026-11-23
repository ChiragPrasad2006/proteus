"""JSONL and optional Parquet persistence restricted to the local filesystem."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from backend.config import Settings
from backend.schemas import CleanedSentEmail, CorpusStatistics, RawSentEmail, RecipientProfile, UserStyleProfile


class ProfileStore:
    """Store personal corpus data locally; no email content is uploaded by this class."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_local_directories()
        self._initialize_sqlite()

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        """Idempotently add a column to a table if it does not already exist."""
        cursor = connection.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _initialize_sqlite(self) -> None:
        """Create a body-free metadata index for Tier 2 retrieval preparation."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS email_metadata (
                    kind TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    recipient_email TEXT,
                    recipient_domain TEXT,
                    subject TEXT,
                    timestamp TEXT,
                    thread_id TEXT,
                    word_count INTEGER,
                    PRIMARY KEY (kind, message_id)
                );
                CREATE TABLE IF NOT EXISTS profile_metadata (
                    profile_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    clean_email_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recipient_profiles (
                    recipient_email TEXT PRIMARY KEY,
                    recipient_domain TEXT,
                    relationship_tier TEXT DEFAULT 'unknown',
                    preferred_greeting TEXT DEFAULT '',
                    sent_count INTEGER DEFAULT 0,
                    learned_rules_json TEXT DEFAULT '[]',
                    last_updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_drafts (
                    draft_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    draft TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    recipient_profiles_json TEXT NOT NULL
                );
                """
            )
            # Idempotent migrations for existing databases
            # No new columns needed currently, but migration guard is in place for future changes

    def _index_messages(self, kind: str, records: Sequence[RawSentEmail | CleanedSentEmail]) -> None:
        """Refresh searchable metadata while keeping full personal text in local JSONL only."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.execute("DELETE FROM email_metadata WHERE kind = ?", (kind,))
            connection.executemany(
                """
                INSERT INTO email_metadata
                (kind, message_id, recipient_email, recipient_domain, subject, timestamp, thread_id, word_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        kind,
                        record.message_id,
                        record.recipient_email,
                        record.recipient_domain,
                        record.subject,
                        record.timestamp.isoformat() if record.timestamp else None,
                        record.thread_id,
                        record.word_count if isinstance(record, CleanedSentEmail) else None,
                    )
                    for record in records
                ],
            )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Replace a local record atomically to avoid corrupting profile state."""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)

    @staticmethod
    def _jsonl(records: Iterable[RawSentEmail | CleanedSentEmail]) -> str:
        return "".join(record.model_dump_json() + "\n" for record in records)

    def save_raw_emails(self, records: list[RawSentEmail]) -> Path:
        """Persist normalized raw Sent data locally for extraction traceability."""
        self._atomic_write(self.settings.raw_emails_path, self._jsonl(records))
        self._index_messages("raw", records)
        return self.settings.raw_emails_path

    def save_cleaned_emails(self, records: list[CleanedSentEmail]) -> Path:
        """Persist cleaned corpus as JSONL and Parquet when PyArrow is available."""
        self._atomic_write(self.settings.cleaned_emails_path, self._jsonl(records))
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist([record.model_dump(mode="json") for record in records])
            pq.write_table(table, self.settings.cleaned_emails_parquet_path)
        except ImportError:
            pass
        self._index_messages("clean", records)
        return self.settings.cleaned_emails_path

    @staticmethod
    def _read_jsonl(path: Path, model_type: type[RawSentEmail] | type[CleanedSentEmail]) -> list[Any]:
        if not path.exists():
            return []
        return [
            model_type.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def load_raw_emails(self) -> list[RawSentEmail]:
        """Load locally persisted raw records."""
        return self._read_jsonl(self.settings.raw_emails_path, RawSentEmail)

    def load_cleaned_emails(self) -> list[CleanedSentEmail]:
        """Load locally persisted clean records."""
        return self._read_jsonl(self.settings.cleaned_emails_path, CleanedSentEmail)

    def corpus_statistics(self, cleaned: list[CleanedSentEmail] | None = None) -> CorpusStatistics:
        """Return safe aggregate corpus statistics without exposing message contents."""
        cleaned = cleaned if cleaned is not None else self.load_cleaned_emails()
        recipients = Counter(record.recipient_email for record in cleaned if record.recipient_email)
        return CorpusStatistics(
            total_sent_emails=len(self.load_raw_emails()),
            clean_emails_retained=len(cleaned),
            top_recipients=[
                {"recipient_email": email, "sent_count": count}
                for email, count in recipients.most_common(10)
            ],
        )

    # Recipient profile management
    def get_recipient_profile(self, recipient_email: str) -> RecipientProfile | None:
        """Load a recipient profile from SQLite."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute(
                """
                SELECT recipient_email, recipient_domain, relationship_tier, preferred_greeting,
                       sent_count, learned_rules_json, last_updated
                FROM recipient_profiles WHERE recipient_email = ?
                """,
                (recipient_email.lower(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            import json
            return RecipientProfile(
                recipient_email=row[0],
                recipient_domain=row[1] or "",
                relationship_tier=row[2] or "unknown",
                preferred_greeting=row[3] or "",
                sent_count=row[4] or 0,
                learned_rules_json=json.loads(row[5]) if row[5] else [],
                last_updated=datetime.fromisoformat(row[6]) if row[6] else datetime.now(timezone.utc),
            )

    def list_recipient_profiles(self) -> list[RecipientProfile]:
        """Return every recipient profile of the active account (alphabetical)."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT recipient_email, recipient_domain, relationship_tier, preferred_greeting,
                       sent_count, learned_rules_json, last_updated
                FROM recipient_profiles
                ORDER BY recipient_email ASC
                """
            ).fetchall()
        import json
        return [
            RecipientProfile(
                recipient_email=row[0],
                recipient_domain=row[1] or "",
                relationship_tier=row[2] or "unknown",
                preferred_greeting=row[3] or "",
                sent_count=row[4] or 0,
                learned_rules_json=json.loads(row[5]) if row[5] else [],
                last_updated=datetime.fromisoformat(row[6]) if row[6] else datetime.now(timezone.utc),
            )
            for row in rows
        ]

    # --- learned rule mutation ---------------------------------------------
    @staticmethod
    def global_rule_id(index: int) -> str:
        """Deterministic identifier for a global learned rule (index based)."""
        return f"global:{index}"

    @staticmethod
    def recipient_rule_id(recipient_email: str, index: int) -> str:
        """Deterministic identifier for a recipient-scoped learned rule."""
        return f"recipient:{recipient_email.lower()}:{index}"

    def update_global_rule(self, index: int, text: str) -> bool:
        """Replace the text of a global learned rule. Returns True when it existed."""
        profile = self.load_profile()
        if profile is None:
            return False
        rules = list(profile.global_learned_rules)
        if not 0 <= index < len(rules):
            return False
        rules[index] = text.strip()
        profile.global_learned_rules = rules[:10]
        self.save_profile(profile)
        return True

    def delete_global_rule(self, index: int) -> bool:
        """Remove a global learned rule. Returns True when it existed."""
        profile = self.load_profile()
        if profile is None:
            return False
        rules = list(profile.global_learned_rules)
        if not 0 <= index < len(rules):
            return False
        rules.pop(index)
        profile.global_learned_rules = rules
        self.save_profile(profile)
        return True

    def update_recipient_rule(self, recipient_email: str, index: int, text: str) -> bool:
        """Replace the text of a recipient-scoped learned rule."""
        profile = self.get_recipient_profile(recipient_email)
        if profile is None:
            return False
        rules = list(profile.learned_rules_json)
        if not 0 <= index < len(rules):
            return False
        rules[index] = text.strip()
        profile.learned_rules_json = rules
        self.upsert_recipient_profile(profile)
        return True

    def delete_recipient_rule(self, recipient_email: str, index: int) -> bool:
        """Remove a recipient-scoped learned rule."""
        profile = self.get_recipient_profile(recipient_email)
        if profile is None:
            return False
        rules = list(profile.learned_rules_json)
        if not 0 <= index < len(rules):
            return False
        rules.pop(index)
        profile.learned_rules_json = rules
        self.upsert_recipient_profile(profile)
        return True

    def clear_learned_rules(self) -> None:
        """Forget every learned rule (global + per recipient) without touching the corpus."""
        profile = self.load_profile()
        if profile is not None:
            profile.global_learned_rules = []
            self.save_profile(profile)
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.execute("UPDATE recipient_profiles SET learned_rules_json = '[]'")

    def upsert_recipient_profile(self, profile: RecipientProfile) -> None:
        """Insert or update a recipient profile in SQLite."""
        import json
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO recipient_profiles
                (recipient_email, recipient_domain, relationship_tier, preferred_greeting,
                 sent_count, learned_rules_json, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.recipient_email.lower(),
                    profile.recipient_domain,
                    profile.relationship_tier,
                    profile.preferred_greeting,
                    profile.sent_count,
                    json.dumps(profile.learned_rules_json),
                    profile.last_updated.isoformat(),
                ),
            )

    def increment_recipient_sent_count(self, recipient_email: str, greeting: str = "") -> int:
        """Increment sent count for a recipient and optionally update preferred greeting."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute(
                "SELECT sent_count, preferred_greeting FROM recipient_profiles WHERE recipient_email = ?",
                (recipient_email.lower(),),
            )
            row = cursor.fetchone()
            if row:
                new_count = row[0] + 1
                new_greeting = greeting or row[1]
                connection.execute(
                    "UPDATE recipient_profiles SET sent_count = ?, preferred_greeting = ?, last_updated = ? WHERE recipient_email = ?",
                    (new_count, new_greeting, datetime.now(timezone.utc).isoformat(), recipient_email.lower()),
                )
                return new_count
            else:
                # First time sending to this recipient
                connection.execute(
                    """
                    INSERT INTO recipient_profiles
                    (recipient_email, recipient_domain, relationship_tier, preferred_greeting, sent_count, last_updated)
                    VALUES (?, ?, 'unknown', ?, 1, ?)
                    """,
                    (
                        recipient_email.lower(),
                        recipient_email.split("@")[-1] if "@" in recipient_email else "",
                        greeting,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                return 1

    def add_learned_rule(self, recipient_email: str, rule: str) -> None:
        """Add a learned style rule for a specific recipient (max 2 per recipient)."""
        profile = self.get_recipient_profile(recipient_email)
        if profile is None:
            profile = RecipientProfile(
                recipient_email=recipient_email,
                recipient_domain=recipient_email.split("@")[-1] if "@" in recipient_email else "",
            )
        # Deduplicate and cap at 2
        rules = list(dict.fromkeys([r for r in profile.learned_rules_json if r] + [rule]))[:2]
        profile.learned_rules_json = rules
        self.upsert_recipient_profile(profile)

    def add_global_learned_rule(self, rule: str) -> None:
        """Add a global learned style rule (max 10). This updates the profile JSON."""
        profile = self.load_profile()
        if profile:
            rules = list(dict.fromkeys([r for r in profile.global_learned_rules if r] + [rule]))[:10]
            profile.global_learned_rules = rules
            self.save_profile(profile)

    def save_profile(self, profile: UserStyleProfile) -> Path:
        """Persist the merged deterministic and model-derived profile locally."""
        self._atomic_write(self.settings.profile_path, profile.model_dump_json(indent=2))
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO profile_metadata (profile_id, created_at, clean_email_count)
                VALUES (?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.created_at.isoformat(),
                    profile.corpus_statistics.clean_emails_retained,
                ),
            )
        return self.settings.profile_path

    def load_profile(self) -> UserStyleProfile | None:
        """Return the active profile, if local onboarding has completed."""
        if not self.settings.profile_path.exists():
            return None
        return UserStyleProfile.model_validate_json(self.settings.profile_path.read_text(encoding="utf-8"))

    def load_pending_draft(self, draft_id: str) -> dict[str, Any] | None:
        """Load a pending draft from SQLite."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute(
                "SELECT draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json FROM pending_drafts WHERE draft_id = ?",
                (draft_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            import json
            return {
                "draft_id": row[0],
                "profile_id": row[1],
                "request": json.loads(row[2]),
                "draft": row[3],
                "created_at": row[4],
                "recipient_profiles": json.loads(row[5]),
            }

    def update_pending_draft(self, draft_id: str, request_data: dict[str, Any], draft: str) -> bool:
        """Persist a revised pending draft while retaining its recipient metadata."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute(
                "UPDATE pending_drafts SET request_json = ?, draft = ? WHERE draft_id = ?",
                (json.dumps(request_data), draft, draft_id),
            )
            return cursor.rowcount > 0

    def delete_pending_draft(self, draft_id: str) -> bool:
        """Delete a pending draft after approval."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute("DELETE FROM pending_drafts WHERE draft_id = ?", (draft_id,))
            return cursor.rowcount > 0