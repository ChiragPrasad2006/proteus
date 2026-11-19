"""Contact registry and fuzzy name resolution built from ingested sent mail.

The resolver aggregates every recipient seen during email ingestion into a
``contacts`` table (email, full_name, first_name, last_name, aliases,
company_domain, interaction_count) and resolves free-text / partial names to a
single contact. Unknown or ambiguous names return ``NEEDS_CLARIFICATION`` so the
caller can ask the user instead of silently guessing a recipient.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable, Sequence

from backend.schemas import CleanedSentEmail, RawSentEmail

# A candidate must score at least this high (0..1) to be considered a match.
MATCH_THRESHOLD = 0.72
# Two distinct contacts closer than this in score are treated as ambiguous.
AMBIGUITY_MARGIN = 0.06

_LOCALPART_SPLIT = re.compile(r"[._\-+]+")


def _split_display_name(display: str) -> tuple[str, str]:
    """Return ``(first_name, last_name)`` from a free-text display name."""
    parts = [p for p in re.split(r"\s+", (display or "").strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _name_from_localpart(local: str) -> tuple[str, str]:
    """Derive a best-effort name from an email local-part like ``jane.doe``."""
    tokens = [t for t in _LOCALPART_SPLIT.split(local) if t and not t.isdigit()]
    if not tokens:
        return "", ""
    first = tokens[0].capitalize()
    last = tokens[-1].capitalize() if len(tokens) > 1 else ""
    return first, last


@dataclass
class Contact:
    """A single resolved correspondent."""

    email: str
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    aliases: list[str] = field(default_factory=list)
    company_domain: str = ""
    interaction_count: int = 0
    last_seen: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "aliases": list(self.aliases),
            "company_domain": self.company_domain,
            "interaction_count": self.interaction_count,
            "last_seen": self.last_seen,
        }


@dataclass
class Resolution:
    """Outcome of resolving a free-text name to a contact."""

    query: str
    status: str  # "MATCHED" | "NEEDS_CLARIFICATION"
    matched: Contact | None = None
    candidates: list[Contact] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "matched": self.matched.to_dict() if self.matched else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "reason": self.reason,
        }


class ContactResolver:
    """Builds and queries the per-account contacts registry."""

    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._cache: dict[str, Contact] = {}
        self._load_cache()

    # --- schema -------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    email TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL DEFAULT '',
                    first_name TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '',
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    company_domain TEXT NOT NULL DEFAULT '',
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    last_seen TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_contacts_domain ON contacts(company_domain);
                """
            )

    # --- persistence --------------------------------------------------------
    @staticmethod
    def _row_to_contact(row: sqlite3.Row) -> Contact:
        return Contact(
            email=row["email"],
            full_name=row["full_name"] or "",
            first_name=row["first_name"] or "",
            last_name=row["last_name"] or "",
            aliases=json.loads(row["aliases_json"] or "[]"),
            company_domain=row["company_domain"] or "",
            interaction_count=row["interaction_count"] or 0,
            last_seen=row["last_seen"] or "",
        )

    def _load_cache(self) -> None:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM contacts").fetchall()
        self._cache = {row["email"].lower(): self._row_to_contact(row) for row in rows}

    def upsert_contact(self, contact: Contact) -> Contact:
        """Insert or merge a contact (case-insensitive on email)."""
        email = contact.email.strip().lower()
        if not email:
            raise ValueError("contact email is required")
        contact.email = email
        existing = self._cache.get(email)
        if existing:
            contact.aliases = list(dict.fromkeys(existing.aliases + contact.aliases))
            contact.interaction_count = max(existing.interaction_count, contact.interaction_count)
            if not contact.full_name:
                contact.full_name = existing.full_name
            if not contact.first_name:
                contact.first_name = existing.first_name
            if not contact.last_name:
                contact.last_name = existing.last_name
            if not contact.company_domain:
                contact.company_domain = existing.company_domain
            if not contact.last_seen:
                contact.last_seen = existing.last_seen
        for alias in (contact.full_name, f"{contact.first_name} {contact.last_name}".strip()):
            alias = alias.strip()
            if alias and alias.lower() != contact.full_name.lower():
                if alias not in contact.aliases:
                    contact.aliases.append(alias)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO contacts
                (email, full_name, first_name, last_name, aliases_json, company_domain, interaction_count, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    contact.full_name,
                    contact.first_name,
                    contact.last_name,
                    json.dumps(contact.aliases),
                    contact.company_domain,
                    contact.interaction_count,
                    contact.last_seen,
                ),
            )
        self._cache[email] = contact
        return contact

    def list_contacts(self) -> list[Contact]:
        return sorted(self._cache.values(), key=lambda c: (-c.interaction_count, c.email))

    def contact_names(self) -> list[str]:
        names: list[str] = []
        for contact in self._cache.values():
            for name in (contact.full_name, f"{contact.first_name} {contact.last_name}".strip(), contact.email):
                name = (name or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    # --- ingestion ----------------------------------------------------------
    def rebuild_from_emails(
        self,
        emails: Sequence[RawSentEmail | CleanedSentEmail],
        reset: bool = True,
    ) -> int:
        """(Re)build the contacts table by aggregating recipient addresses.

        Display names captured from ``To:`` headers become ``full_name`` and are
        kept as aliases; a missing display name is derived from the local-part.
        """
        if reset:
            with self._connect() as connection:
                connection.execute("DELETE FROM contacts")
            self._cache = {}

        for record in emails:
            raw_recipient = (record.recipient_email or "").strip()
            if not raw_recipient:
                continue
            display, addr = parseaddr(raw_recipient)
            if not addr:
                addr = raw_recipient
            addr = addr.strip().lower()
            if "@" not in addr:
                # Cannot form a usable address; skip malformed entries.
                continue

            local, _, domain = addr.partition("@")
            first, last = _split_display_name(display)
            if not first:
                first, last = _name_from_localpart(local)
            full_name = " ".join(p for p in (first, last) if p).strip()

            aliases: list[str] = []
            if display and display.strip():
                aliases.append(display.strip())

            timestamp_value: Any = getattr(record, "timestamp", None)
            timestamp = timestamp_value.isoformat() if timestamp_value else ""

            contact = self._cache.get(addr)
            if contact is None:
                contact = Contact(
                    email=addr,
                    full_name=full_name,
                    first_name=first,
                    last_name=last,
                    aliases=list(dict.fromkeys(aliases)),
                    company_domain=domain,
                    interaction_count=1,
                    last_seen=timestamp,
                )
            else:
                contact.interaction_count += 1
                if len(full_name) > len(contact.full_name):
                    contact.full_name = full_name
                if not contact.first_name and first:
                    contact.first_name = first
                if not contact.last_name and last:
                    contact.last_name = last
                for alias in aliases:
                    if alias not in contact.aliases:
                        contact.aliases.append(alias)
                if timestamp and timestamp > contact.last_seen:
                    contact.last_seen = timestamp
            self._cache[addr] = contact

        # Persist the aggregated registry in one transaction.
        rows = [
            (
                c.email,
                c.full_name,
                c.first_name,
                c.last_name,
                json.dumps(c.aliases),
                c.company_domain,
                c.interaction_count,
                c.last_seen,
            )
            for c in self._cache.values()
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO contacts
                (email, full_name, first_name, last_name, aliases_json, company_domain, interaction_count, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def is_empty(self) -> bool:
        return not self._cache

    # --- resolution ---------------------------------------------------------
    def _score(self, query: str, contact: Contact) -> float:
        """Score a free-text query against a contact's names, aliases and address."""
        candidates = [
            contact.full_name,
            contact.first_name,
            f"{contact.first_name} {contact.last_name}".strip(),
            contact.email,
            contact.email.split("@")[0],
            *contact.aliases,
        ]
        best = 0.0
        for value in candidates:
            value = (value or "").strip().lower()
            if not value:
                continue
            if value == query:
                best = max(best, 1.0)
            elif value.startswith(query) or query.startswith(value):
                best = max(best, 0.90)
            for token in value.replace("@", " ").split():
                if token == query:
                    best = max(best, 0.95)
                elif token.startswith(query):
                    best = max(best, 0.88)
            best = max(best, difflib.SequenceMatcher(None, query, value).ratio())
        return best

    def resolve(self, name: str) -> Resolution:
        """Resolve one free-text name to a single contact or request clarification."""
        query = (name or "").strip()
        if not query:
            return Resolution(query=query, status="NEEDS_CLARIFICATION", reason="Empty recipient name.")

        lowered = query.lower()

        # Direct address / local-part lookup.
        if "@" in query:
            _, addr = parseaddr(query)
            addr = (addr or query).split()[0].lower()
            if addr in self._cache:
                return Resolution(query=query, status="MATCHED", matched=self._cache[addr])
            local = addr.split("@")[0]
            for contact in self._cache.values():
                if contact.email.split("@")[0] == local:
                    return Resolution(query=query, status="MATCHED", matched=contact)
            return Resolution(
                query=query,
                status="NEEDS_CLARIFICATION",
                reason=f"No contact found for address '{query}'.",
            )

        scored = [
            (self._score(lowered, contact), contact)
            for contact in self._cache.values()
        ]
        scored = [(score, contact) for score, contact in scored if score >= MATCH_THRESHOLD]
        if not scored:
            return Resolution(
                query=query,
                status="NEEDS_CLARIFICATION",
                reason=f"No known contact matches '{query}'.",
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        top_score, top = scored[0]
        close = [
            contact
            for score, contact in scored
            if contact.email != top.email and score >= top_score - AMBIGUITY_MARGIN
        ]
        if close:
            candidates = [top, *close]
            return Resolution(
                query=query,
                status="NEEDS_CLARIFICATION",
                candidates=candidates,
                reason=f"'{query}' is ambiguous across {len(candidates)} contacts.",
            )
        return Resolution(query=query, status="MATCHED", matched=top)

    def resolve_many(self, names: Iterable[str]) -> list[Resolution]:
        """Resolve each name, collapsing names that point at the same contact.

        A single recipient can be mentioned in several forms ("manu" and
        "manu@expano.in"); those must resolve to one entry so the envelope
        never lists the same person twice.
        """
        resolutions: list[Resolution] = []
        seen_emails: set[str] = set()
        seen_queries: set[str] = set()
        for name in names:
            if not (name or "").strip():
                continue
            resolution = self.resolve(name)
            if resolution.status == "MATCHED" and resolution.matched is not None:
                email = resolution.matched.email.lower()
                if email in seen_emails:
                    continue
                seen_emails.add(email)
            else:
                query = resolution.query.strip().lower()
                if query in seen_queries:
                    continue
                seen_queries.add(query)
            resolutions.append(resolution)
        return resolutions
