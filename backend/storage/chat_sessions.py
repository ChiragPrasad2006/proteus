"""SQLite persistence for chat sessions, messages, and draft cards (per account)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatSessionStore:
    """Account-scoped store backed by ``chat_sessions.sqlite3``.

    Three tables:
      * ``sessions``     - one row per conversation thread
      * ``messages``     - ordered user/assistant turns
      * ``draft_cards``  - generated drafts and their review/send status
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # --- plumbing -----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        """Idempotently add a column to a table if it does not already exist."""
        cursor = connection.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    pending_clarification_json TEXT NOT NULL DEFAULT '{}',
                    is_custom_title INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS draft_cards (
                    card_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_id TEXT,
                    draft_id TEXT,
                    to_json TEXT NOT NULL DEFAULT '[]',
                    cc_json TEXT NOT NULL DEFAULT '[]',
                    bcc_json TEXT NOT NULL DEFAULT '[]',
                    subject TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_draft_cards_session
                    ON draft_cards(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_account
                    ON sessions(account_id, updated_at);
                """
            )
            # Idempotent migrations for existing databases
            self._ensure_column(connection, "sessions", "pending_clarification_json",
                               "pending_clarification_json TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "sessions", "is_custom_title",
                               "is_custom_title INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "sessions", "pinned",
                               "pinned INTEGER NOT NULL DEFAULT 0")

    # --- sessions -----------------------------------------------------------
    def create_session(
        self, account_id: str, title: str = "", session_id: str | None = None
    ) -> dict[str, Any]:
        """Create (or return an existing) chat session for an account."""
        session_id = session_id or str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing:
                return self.get_session_summary(session_id)  # type: ignore[return-value]
            connection.execute(
                """
                INSERT INTO sessions (session_id, account_id, title, created_at, updated_at, message_count)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (session_id, account_id, title, timestamp, timestamp),
            )
        return {
            "session_id": session_id,
            "account_id": account_id,
            "title": title,
            "created_at": timestamp,
            "updated_at": timestamp,
            "message_count": 0,
        }

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row) if row else None

    @staticmethod
    def _session_row(row: sqlite3.Row) -> dict[str, Any]:
        import json
        keys = row.keys()
        pending = row["pending_clarification_json"] if "pending_clarification_json" in keys else "{}"
        is_custom = row["is_custom_title"] if "is_custom_title" in keys else 0
        pinned = row["pinned"] if "pinned" in keys else 0
        return {
            "session_id": row["session_id"],
            "account_id": row["account_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"],
            "pending_clarification": json.loads(pending or "{}"),
            "is_custom_title": bool(is_custom),
            "pinned": bool(pinned),
        }

    def list_sessions(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List an account's sessions: pinned first, then most-recently-updated."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sessions
                WHERE account_id = ?
                ORDER BY pinned DESC, updated_at DESC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()
        return [self._session_row(row) for row in rows]

    def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        """Set (idempotently) the pinned flag of a session. Returns True when a row changed.

        ``updated_at`` is intentionally left untouched: pinning is an ordering hint,
        not new conversation activity.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET pinned = ? WHERE session_id = ?",
                (1 if pinned else 0, session_id),
            )
            return cursor.rowcount > 0

    def rename_session(self, session_id: str, title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (title, _now(), session_id),
            )

    def update_session_title(self, session_id: str, title: str, is_custom: bool = False) -> None:
        """Update session title and optionally mark as custom."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ?, is_custom_title = ? WHERE session_id = ?",
                (title, _now(), 1 if is_custom else 0, session_id),
            )

    def _touch(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (_now(), session_id)
        )

    # --- messages -----------------------------------------------------------
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a message turn and bump the session's message count / updated_at."""
        message_id = message_id or str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (message_id, session_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, timestamp, json.dumps(metadata or {})),
            )
            connection.execute(
                "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE session_id = ?",
                (timestamp, session_id),
            )
        return {
            "message_id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": timestamp,
            "metadata": metadata or {},
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]

    def get_recent_messages(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """Return the last ``limit`` messages for conversation context."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        # Return in chronological order (oldest first)
        rows = list(reversed(rows))
        return [
            {
                "message_id": row["message_id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]

    def set_pending_clarification(self, session_id: str, payload: dict[str, Any]) -> None:
        """Persist a pending clarification payload on the session."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET pending_clarification_json = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(payload), _now(), session_id),
            )

    def get_pending_clarification(self, session_id: str) -> dict[str, Any] | None:
        """Load the pending clarification payload for a session, if any."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pending_clarification_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row and row["pending_clarification_json"]:
            import json
            payload = json.loads(row["pending_clarification_json"])
            return payload if payload else None
        return None

    def clear_pending_clarification(self, session_id: str) -> None:
        """Clear the pending clarification payload for a session."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET pending_clarification_json = '{}', updated_at = ? WHERE session_id = ?",
                (_now(), session_id),
            )

    # --- draft cards --------------------------------------------------------
    def upsert_draft_card(
        self,
        session_id: str,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str = "",
        body: str = "",
        status: str = "DRAFT",
        draft_id: str | None = None,
        message_id: str | None = None,
        card_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new draft card (or update an existing one by ``card_id``)."""
        card_id = card_id or str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT card_id, created_at FROM draft_cards WHERE card_id = ?", (card_id,)
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE draft_cards
                    SET to_json = ?, cc_json = ?, bcc_json = ?, subject = ?, body = ?,
                        status = ?, draft_id = ?, message_id = ?, updated_at = ?
                    WHERE card_id = ?
                    """,
                    (
                        json.dumps(to or []),
                        json.dumps(cc or []),
                        json.dumps(bcc or []),
                        subject,
                        body,
                        status,
                        draft_id,
                        message_id,
                        timestamp,
                        card_id,
                    ),
                )
                created_at = existing["created_at"]
            else:
                created_at = timestamp
                connection.execute(
                    """
                    INSERT INTO draft_cards
                    (card_id, session_id, message_id, draft_id, to_json, cc_json, bcc_json,
                     subject, body, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        session_id,
                        message_id,
                        draft_id,
                        json.dumps(to or []),
                        json.dumps(cc or []),
                        json.dumps(bcc or []),
                        subject,
                        body,
                        status,
                        created_at,
                        timestamp,
                    ),
                )
            self._touch(connection, session_id)
        return self.get_draft_card(card_id)  # type: ignore[return-value]

    def update_draft_card_status(self, card_id: str, status: str, body: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            if body is None:
                connection.execute(
                    "UPDATE draft_cards SET status = ?, updated_at = ? WHERE card_id = ?",
                    (status, _now(), card_id),
                )
            else:
                connection.execute(
                    "UPDATE draft_cards SET status = ?, body = ?, updated_at = ? WHERE card_id = ?",
                    (status, body, _now(), card_id),
                )
        return self.get_draft_card(card_id)

    def update_draft_card_by_draft_id(
        self,
        draft_id: str,
        subject: str,
        body: str,
        status: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT card_id FROM draft_cards WHERE draft_id = ? ORDER BY updated_at DESC LIMIT 1",
                (draft_id,),
            ).fetchone()
            if row is None:
                return None
            updates = ["subject = ?", "body = ?", "updated_at = ?"]
            values: list[Any] = [subject, body, _now()]
            if to is not None:
                updates.append("to_json = ?")
                values.append(json.dumps(to))
            if cc is not None:
                updates.append("cc_json = ?")
                values.append(json.dumps(cc))
            if bcc is not None:
                updates.append("bcc_json = ?")
                values.append(json.dumps(bcc))
            if status is not None:
                updates.append("status = ?")
                values.append(status)
            values.append(row["card_id"])
            connection.execute(
                f"UPDATE draft_cards SET {', '.join(updates)} WHERE card_id = ?",
                values,
            )
        return self.get_draft_card(row["card_id"])

    def delete_draft_card_by_draft_id(self, draft_id: str) -> bool:
        """Delete the staged card(s) for a draft id and detach them from their messages.

        The assistant message keeps its turn but loses the card reference, so a
        discarded draft stays discarded after a reload.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT card_id, session_id FROM draft_cards WHERE draft_id = ?", (draft_id,)
            ).fetchall()
            if not rows:
                return False
            for row in rows:
                card_id = row["card_id"]
                messages = connection.execute(
                    "SELECT message_id, metadata_json FROM messages WHERE session_id = ? AND metadata_json LIKE ?",
                    (row["session_id"], f"%{card_id}%"),
                ).fetchall()
                for message in messages:
                    metadata = json.loads(message["metadata_json"] or "{}")
                    metadata.pop("card_id", None)
                    metadata.pop("draft_id", None)
                    metadata["status"] = "DRAFT_DISCARDED"
                    connection.execute(
                        "UPDATE messages SET metadata_json = ? WHERE message_id = ?",
                        (json.dumps(metadata), message["message_id"]),
                    )
                connection.execute("DELETE FROM draft_cards WHERE card_id = ?", (card_id,))
        return True

    def latest_pending_draft_id(self, session_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT draft_id FROM draft_cards WHERE session_id = ? AND status = 'PENDING_REVIEW' AND draft_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return row["draft_id"] if row else None

    @staticmethod
    def _card_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "card_id": row["card_id"],
            "session_id": row["session_id"],
            "message_id": row["message_id"],
            "draft_id": row["draft_id"],
            "to": json.loads(row["to_json"] or "[]"),
            "cc": json.loads(row["cc_json"] or "[]"),
            "bcc": json.loads(row["bcc_json"] or "[]"),
            "subject": row["subject"],
            "body": row["body"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_draft_card(self, card_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM draft_cards WHERE card_id = ?", (card_id,)
            ).fetchone()
        return self._card_row(row) if row else None

    def list_draft_cards(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM draft_cards WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [self._card_row(row) for row in rows]

    # --- aggregate ----------------------------------------------------------
    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return ``{session, messages, draft_cards}`` for a session, or ``None``."""
        summary = self.get_session_summary(session_id)
        if summary is None:
            return None
        return {
            "session": summary,
            "messages": self.list_messages(session_id),
            "draft_cards": self.list_draft_cards(session_id),
        }

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM draft_cards WHERE session_id = ?", (session_id,))
            cursor = connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return cursor.rowcount > 0
