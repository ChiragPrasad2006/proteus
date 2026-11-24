"""Account registry and per-account storage paths for strict multi-account isolation."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INDEX_LOCK = threading.RLock()
_INDEX_READ_ATTEMPTS = 3
_INDEX_WRITE_ATTEMPTS = 5
_INDEX_WRITE_BACKOFF_BASE = 0.02  # 20ms, max 100ms


def _atomic_write_json(path: Path, data: dict[str, dict[str, Any]]) -> None:
    """Atomically write JSON to path with fsync and Windows-safe retries."""
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_INDEX_WRITE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == _INDEX_WRITE_ATTEMPTS - 1:
                    raise
                time.sleep(min(_INDEX_WRITE_BACKOFF_BASE * (attempt + 1), 0.1))
    finally:
        tmp_path.unlink(missing_ok=True)


@dataclass
class AccountInfo:
    """Lightweight account registry entry."""

    account_id: str
    email: str
    display_name: str
    avatar_url: str = ""
    provider: str = "gmail"
    # False until IMAP/SMTP or OAuth mailbox credentials are verified for this
    # account. Legacy index entries without this key load as False.
    mailbox_connected: bool = False
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "provider": self.provider,
            "mailbox_connected": self.mailbox_connected,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccountInfo":
        """Load an index entry tolerantly.

        Unknown keys are ignored (forward compatibility) and legacy entries
        without ``mailbox_connected`` default to False (backward compatibility).
        """
        if not isinstance(data, dict):
            raise ValueError("Account index entry must be a JSON object.")
        field_names = set(cls.__dataclass_fields__)
        kwargs = {key: value for key, value in data.items() if key in field_names}
        if "mailbox_connected" in data:
            kwargs["mailbox_connected"] = bool(data["mailbox_connected"])
        return cls(**kwargs)


class AccountManager:
    """Manages the accounts index registry and provides per-account storage paths."""

    def __init__(self, local_user_data_dir: Path) -> None:
        self.local_user_data_dir = Path(local_user_data_dir)
        self.accounts_dir = self.local_user_data_dir / "accounts"
        self.index_path = self.local_user_data_dir / "accounts_index.json"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save_index({})

    def _load_index(self) -> dict[str, dict[str, Any]]:
            def _read_with_retry() -> str:
                for attempt in range(_INDEX_READ_ATTEMPTS):
                    try:
                        return self.index_path.read_text(encoding="utf-8")
                    except PermissionError:
                        if attempt == _INDEX_READ_ATTEMPTS - 1:
                            raise
                        time.sleep(0.05)
                return ""  # unreachable

            with _INDEX_LOCK:
                if not self.index_path.exists():
                    return {}
                try:
                    index = json.loads(_read_with_retry())
                except json.JSONDecodeError:
                    return {}

                changed = False
                for account_id, data in index.items():
                    if data.get("mailbox_connected"):
                        continue
                    paths = self.get_account_paths(account_id)
                    has_profile = False
                    profile_path = paths["profile_json"]
                    if profile_path.is_file():
                        try:
                            has_profile = isinstance(json.loads(profile_path.read_text(encoding="utf-8")), dict)
                        except (OSError, json.JSONDecodeError):
                            pass
                    has_credentials = False
                    password_path = paths["app_password"]
                    if password_path.is_file():
                        try:
                            saved_token = password_path.read_text(encoding="utf-8").strip()
                            has_credentials = saved_token.startswith(("dpapi:", "fernet:")) and len(saved_token) > 30
                        except OSError:
                            pass
                    if has_profile or has_credentials:
                        data["mailbox_connected"] = True
                        data["updated_at"] = datetime.now(timezone.utc).isoformat()
                        changed = True

                if changed:
                    self._save_index(index)
                return index

    def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
            with _INDEX_LOCK:
                _atomic_write_json(self.index_path, index)

    def get_account_dir(self, account_id: str) -> Path:
        """Get the root directory for an account's isolated data."""
        return self.accounts_dir / account_id

    def get_account_paths(self, account_id: str) -> dict[str, Path]:
        """Get all storage paths for a specific account."""
        base = self.get_account_dir(account_id)
        return {
            "root": base,
            "sqlite": base / "profile_metadata.sqlite3",
            "lancedb": base / "lancedb",
            "profile_json": base / "user_style_profile.json",
            "cleaned_emails_jsonl": base / "cleaned_sent_emails.jsonl",
            "cleaned_emails_parquet": base / "cleaned_sent_emails.parquet",
            "raw_emails_jsonl": base / "raw_sent_emails.jsonl",
            "chat_sessions": base / "chat_sessions.sqlite3",
            "oauth_tokens": base / "oauth_tokens",
            "app_password": base / "app_password.bin",
        }

    def create_account(
        self,
        email: str,
        display_name: str,
        provider: str = "gmail",
        avatar_url: str = "",
        mailbox_connected: bool = False,
    ) -> AccountInfo:
        """Create a new account with a generated account_id.

        ``mailbox_connected`` defaults to False: a connection is recorded only
        after the account's mailbox credentials have been verified (see the
        connect-app-password endpoint).
        """
        account_id = str(uuid.uuid4())[:12]  # Short readable ID
        account = AccountInfo(
            account_id=account_id,
            email=email.lower(),
            display_name=display_name,
            avatar_url=avatar_url,
            provider=provider,
            mailbox_connected=mailbox_connected,
            is_active=True,
        )
        index = self._load_index()
        index[account_id] = account.to_dict()
        self._save_index(index)

        # Create only directory entries; file paths (sqlite/jsonl) must stay files.
        base = self.get_account_dir(account_id)
        base.mkdir(parents=True, exist_ok=True)
        (base / "lancedb").mkdir(exist_ok=True)
        (base / "oauth_tokens").mkdir(exist_ok=True)

        return account

    def get_account(self, account_id: str) -> AccountInfo | None:
        """Get account info by ID."""
        index = self._load_index()
        data = index.get(account_id)
        return AccountInfo.from_dict(data) if data else None

    def get_account_by_email(self, email: str) -> AccountInfo | None:
        """Get account info by email address."""
        index = self._load_index()
        for data in index.values():
            if data.get("email", "").lower() == email.lower():
                return AccountInfo.from_dict(data)
        return None

    def list_accounts(self) -> list[AccountInfo]:
        """List all registered accounts."""
        index = self._load_index()
        return [AccountInfo.from_dict(data) for data in index.values()]

    def set_active_account(self, account_id: str) -> AccountInfo | None:
        """Mark an account as active (only one active at a time)."""
        index = self._load_index()
        if account_id not in index:
            return None
        for aid, data in index.items():
            data["is_active"] = (aid == account_id)
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_index(index)
        return AccountInfo.from_dict(index[account_id])

    def get_active_account(self) -> AccountInfo | None:
        """Get the currently active account."""
        index = self._load_index()
        for data in index.values():
            if data.get("is_active"):
                return AccountInfo.from_dict(data)
        # Fallback: return first account if none marked active
        if index:
            first_id = next(iter(index))
            return AccountInfo.from_dict(index[first_id])
        return None

    def delete_account(self, account_id: str) -> bool:
        """Delete an account and all its data."""
        import shutil
        index = self._load_index()
        if account_id not in index:
            return False
        # Remove account directory
        account_dir = self.get_account_dir(account_id)
        if account_dir.exists():
            shutil.rmtree(account_dir)
        # Remove from index
        del index[account_id]
        self._save_index(index)
        return True

    def update_account(self, account_id: str, **kwargs) -> AccountInfo | None:
        """Update account fields.

        Known ``AccountInfo`` fields are accepted even when the stored entry
        predates them (e.g. ``mailbox_connected`` on a legacy index entry).
        """
        index = self._load_index()
        if account_id not in index:
            return None
        data = index[account_id]
        known_fields = set(AccountInfo.__dataclass_fields__)
        for key, value in kwargs.items():
            if key in known_fields and key != "account_id":
                data[key] = value
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_index(index)
        return AccountInfo.from_dict(data)