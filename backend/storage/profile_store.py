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
                    recipient_profiles_json TEXT NOT NULL,
                    audience_type TEXT NOT NULL DEFAULT '1on1_private',
                    resolution_meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS pilot_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    audience_type TEXT NOT NULL DEFAULT '1on1_private',
                    draft_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pilot_events_type
                    ON pilot_events(event_type, created_at);
                """
            )
            # Idempotent migrations for existing databases
            self._ensure_column(
                connection, "pending_drafts", "audience_type",
                "audience_type TEXT NOT NULL DEFAULT '1on1_private'",
            )
            self._ensure_column(
                connection, "pending_drafts", "resolution_meta_json",
                "resolution_meta_json TEXT NOT NULL DEFAULT '{}'",
            )

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
                """SELECT draft_id, profile_id, request_json, draft, created_at,
                          recipient_profiles_json, audience_type, resolution_meta_json
                   FROM pending_drafts WHERE draft_id = ?""",
                (draft_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "draft_id": row[0],
                "profile_id": row[1],
                "request": json.loads(row[2]),
                "draft": row[3],
                "created_at": row[4],
                "recipient_profiles": json.loads(row[5]),
                "audience_type": row[6] or "1on1_private",
                "resolution_meta": json.loads(row[7] or "{}") if row[7] else {},
            }

    def update_pending_draft(
        self,
        draft_id: str,
        request_data: dict[str, Any],
        draft: str,
        audience_type: str | None = None,
        resolution_meta: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a revised pending draft while retaining its recipient metadata."""
        updates = ["request_json = ?", "draft = ?"]
        values: list[Any] = [json.dumps(request_data), draft]
        if audience_type is not None:
            updates.append("audience_type = ?")
            values.append(audience_type)
        if resolution_meta is not None:
            updates.append("resolution_meta_json = ?")
            values.append(json.dumps(resolution_meta))
        values.append(draft_id)
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute(
                f"UPDATE pending_drafts SET {', '.join(updates)} WHERE draft_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete_pending_draft(self, draft_id: str) -> bool:
        """Delete a pending draft after approval."""
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            cursor = connection.execute("DELETE FROM pending_drafts WHERE draft_id = ?", (draft_id,))
            return cursor.rowcount > 0

    # --- local-only pilot metrics (zero PII / zero email text) -------------
    def record_pilot_event(
        self,
        event_type: str,
        audience_type: str = "1on1_private",
        draft_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Record an anonymous local lifecycle count in SQLite (no content/PII)."""
        import uuid

        safe_audience = audience_type if audience_type in ("1on1_private", "group_cc", "broadcast_bcc") else "1on1_private"
        ts = created_at or datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.settings.sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO pilot_events (event_id, event_type, audience_type, draft_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), event_type, safe_audience, str(draft_id or ""), ts),
            )

    @staticmethod
    def _extract_iso_date(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            date_part = raw[:10]
            if date_part.replace("-", "").isdigit():
                return date_part
        return None

    def compute_pilot_metrics(self, chat_sessions_path: Path | None = None) -> dict[str, Any]:
        """Compute account-scoped aggregate counts & dates with zero PII."""
        breakdown: dict[str, int] = {
            "1on1_private": 0,
            "group_cc": 0,
            "broadcast_bcc": 0,
        }
        total_generated = 0
        inbox_replies = 0
        drafts_refined = 0
        drafts_sent = 0
        drafts_discarded = 0
        active_dates: set[str] = set()
        logged_generated_ids: set[str] = set()
        logged_sent_ids: set[str] = set()

        with sqlite3.connect(self.settings.sqlite_path) as connection:
            rows = connection.execute(
                "SELECT event_type, audience_type, draft_id, created_at FROM pilot_events"
            ).fetchall()
            for event_type, aud, draft_id, created_at in rows:
                safe_aud = aud if aud in breakdown else "1on1_private"
                if day := self._extract_iso_date(created_at):
                    active_dates.add(day)
                if event_type == "draft_generated":
                    total_generated += 1
                    breakdown[safe_aud] += 1
                    if draft_id:
                        logged_generated_ids.add(draft_id)
                elif event_type == "inbox_reply_drafted":
                    total_generated += 1
                    inbox_replies += 1
                    breakdown[safe_aud] += 1
                    if draft_id:
                        logged_generated_ids.add(draft_id)
                elif event_type == "draft_refined":
                    drafts_refined += 1
                elif event_type == "draft_sent":
                    drafts_sent += 1
                    if draft_id:
                        logged_sent_ids.add(draft_id)
                elif event_type == "draft_discarded":
                    drafts_discarded += 1

            # Include any unlogged staged pending drafts (e.g., seeded/legacy rows)
            pending_rows = connection.execute(
                "SELECT draft_id, request_json, created_at, audience_type FROM pending_drafts"
            ).fetchall()
            for draft_id, req_json, created_at, aud in pending_rows:
                if day := self._extract_iso_date(created_at):
                    active_dates.add(day)
                if draft_id and draft_id in logged_generated_ids:
                    continue
                safe_aud = aud if aud in breakdown else "1on1_private"
                total_generated += 1
                breakdown[safe_aud] += 1
                if draft_id:
                    logged_generated_ids.add(draft_id)
                try:
                    req = json.loads(req_json or "{}")
                    if req.get("thread_id") or req.get("reply_mode"):
                        inbox_replies += 1
                except (TypeError, ValueError):
                    pass

        # Read-only inspection of chat_sessions.sqlite3 if present
        if chat_sessions_path is not None and Path(chat_sessions_path).is_file():
            with sqlite3.connect(chat_sessions_path) as s_conn:
                for table, cols in (
                    ("sessions", "created_at, updated_at"),
                    ("messages", "created_at"),
                ):
                    try:
                        for row in s_conn.execute(f"SELECT {cols} FROM {table}").fetchall():
                            for val in row:
                                if day := self._extract_iso_date(val):
                                    active_dates.add(day)
                    except sqlite3.OperationalError:
                        pass
                try:
                    card_cols = {r[1] for r in s_conn.execute("PRAGMA table_info(draft_cards)").fetchall()}
                    aud_col = "audience_type" if "audience_type" in card_cols else "'1on1_private'"
                    for card_id, draft_id, status, aud, created_at, updated_at in s_conn.execute(
                        f"SELECT card_id, draft_id, status, {aud_col}, created_at, updated_at FROM draft_cards"
                    ).fetchall():
                        for val in (created_at, updated_at):
                            if day := self._extract_iso_date(val):
                                active_dates.add(day)
                        key = draft_id or card_id
                        safe_aud = aud if aud in breakdown else "1on1_private"
                        if key and key not in logged_generated_ids:
                            total_generated += 1
                            breakdown[safe_aud] += 1
                            logged_generated_ids.add(key)
                        if status == "SENT" and key and key not in logged_sent_ids:
                            drafts_sent += 1
                            logged_sent_ids.add(key)
                except sqlite3.OperationalError:
                    pass

        profile = self.load_profile()
        global_rules_cnt = len(profile.global_learned_rules) if profile is not None else 0
        recipient_rules_cnt = sum(len(rp.learned_rules_json) for rp in self.list_recipient_profiles())
        sorted_dates = sorted(active_dates)
        return {
            "total_drafts_generated": total_generated,
            "inbox_replies_drafted": inbox_replies,
            "drafts_refined": drafts_refined,
            "drafts_sent": drafts_sent,
            "drafts_discarded": drafts_discarded,
            "active_days": len(sorted_dates),
            "active_dates": sorted_dates,
            "learned_rules_count": global_rules_cnt + recipient_rules_cnt,
            "audience_breakdown": breakdown,
        }