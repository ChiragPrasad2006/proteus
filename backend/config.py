"""Configuration for the local-first personalization backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _path_from_env(name: str, default: Path) -> Path:
    """Return an expanded path from an environment override or a default."""
    return Path(os.getenv(name, str(default))).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    """Runtime settings; all persisted user content remains below local_user_data_dir."""

    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    local_user_data_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "EMAIL_WRITER_LOCAL_DATA_DIR", PROJECT_ROOT / "local_user_data"
        )
    )
    exported_model_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "EMAIL_WRITER_MODEL_DIR", PROJECT_ROOT / "exported_models" / "qwen2.5-3b-email-8bit"
        )
    )
    adapter_model_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "EMAIL_WRITER_ADAPTER_DIR", PROJECT_ROOT / "checkpoints" / "qwen-email-dpo-final"
        )
    )
    ollama_url: str = field(
        default_factory=lambda: os.getenv("EMAIL_WRITER_OLLAMA_URL", "http://127.0.0.1:11434")
    )
    # Upgraded to qwen3:8b as default model
    model_name: str = field(default_factory=lambda: os.getenv("EMAIL_WRITER_MODEL_NAME", "email-writer"))
    ollama_fallback_model: str = field(
        default_factory=lambda: os.getenv("EMAIL_WRITER_OLLAMA_FALLBACK_MODEL", "qwen3:8b")
    )
    profiler_mode: str = field(default_factory=lambda: os.getenv("EMAIL_WRITER_PROFILER_MODE", "local"))
    minimum_clean_words: int = field(
        default_factory=lambda: int(os.getenv("EMAIL_WRITER_MINIMUM_CLEAN_WORDS", "20"))
    )
    default_extract_limit: int = field(
        default_factory=lambda: int(os.getenv("EMAIL_WRITER_DEFAULT_EXTRACT_LIMIT", "300"))
    )
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L12-v2"
    sentence_transformer_cache_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "SENTENCE_TRANSFORMERS_HOME", Path.home() / ".cache" / "sentence_transformers"
        )
    )

    # HF_HOME override to keep large caches on D: drive
    hf_home: Path = field(
        default_factory=lambda: _path_from_env("HF_HOME", Path("D:/huggingface_cache"))
    )

    # LanceDB vector store
    lancedb_dir: Path = field(
        default_factory=lambda: _path_from_env(
            "EMAIL_WRITER_LANCEDB_DIR", PROJECT_ROOT / "local_user_data" / "lancedb"
        )
    )

    # Ollama context window cap for qwen3:8b (8GB VRAM target)
    ollama_num_ctx: int = field(
        default_factory=lambda: int(os.getenv("EMAIL_WRITER_OLLAMA_NUM_CTX", "8192"))
    )

    # Google OAuth settings
    google_client_secrets_file: Path = field(
        default_factory=lambda: _path_from_env(
            "GOOGLE_CLIENT_SECRETS_FILE", Path.home() / ".config" / "gmail_client_secrets.json"
        )
    )
    google_oauth_redirect_uri: str = field(
        default_factory=lambda: os.getenv(
            "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/api/auth/google/callback"
        )
    )
    google_oauth_port: int = field(
        default_factory=lambda: int(os.getenv("GOOGLE_OAUTH_PORT", "8080"))
    )

    # Frontend URL for redirects after the OAuth callback
    frontend_url: str = field(
        default_factory=lambda: os.getenv("FRONTEND_URL", "http://localhost:5173")
    )

    @property
    def lancedb_table_name(self) -> str:
        return "sent_emails"

    @property
    def accounts_dir(self) -> Path:
        """Root directory for all account data."""
        return self.local_user_data_dir / "accounts"

    @property
    def accounts_index_path(self) -> Path:
        """Registry of all connected accounts."""
        return self.local_user_data_dir / "accounts_index.json"

    @property
    def oauth_token_dir(self) -> Path:
        """OAuth token directory (legacy single-account root, per-account after for_account)."""
        return self.local_user_data_dir / "oauth_tokens"

    @property
    def raw_emails_path(self) -> Path:
        return self.local_user_data_dir / "raw_sent_emails.jsonl"

    @property
    def cleaned_emails_path(self) -> Path:
        return self.local_user_data_dir / "cleaned_sent_emails.jsonl"

    @property
    def cleaned_emails_parquet_path(self) -> Path:
        return self.local_user_data_dir / "cleaned_sent_emails.parquet"

    @property
    def sqlite_path(self) -> Path:
        """Local metadata index; message bodies remain in the JSONL corpus files."""
        return self.local_user_data_dir / "profile_metadata.sqlite3"

    @property
    def profile_path(self) -> Path:
        return self.local_user_data_dir / "user_style_profile.json"

    @property
    def chat_sessions_path(self) -> Path:
        """SQLite store for chat sessions, messages, and draft cards."""
        return self.local_user_data_dir / "chat_sessions.sqlite3"

    @property
    def contacts_path(self) -> Path:
        """SQLite store for the resolved contacts registry."""
        return self.local_user_data_dir / "contacts.sqlite3"

    @property
    def ollama_models(self) -> Tuple[str, ...]:
        """Prefer the exported personalized Ollama model, then the local base fallback."""
        return tuple(dict.fromkeys((self.model_name, self.ollama_fallback_model)))

    @property
    def google_oauth_scopes(self) -> Tuple[str, ...]:
        """Full Google OAuth2 scope set for desktop connect (identity + Gmail read/send)."""
        return (
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        )

    def ensure_local_directories(self) -> None:
        """Create only local directories used for tokens and user email-derived data."""
        self.local_user_data_dir.mkdir(parents=True, exist_ok=True)
        self.oauth_token_dir.mkdir(parents=True, exist_ok=True)
        self.lancedb_dir.mkdir(parents=True, exist_ok=True)
        self.hf_home.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)

    def for_account(self, account_id: str) -> "Settings":
        """Return an isolated Settings whose derived paths live under ``accounts/<id>/``.

        Every derived path property (profile, corpus, sqlite, chat sessions, OAuth
        tokens) resolves below the returned copy's ``local_user_data_dir``, so a
        per-account copy gives strict storage isolation between accounts.
        """
        account_root = self.local_user_data_dir / "accounts" / account_id
        account_root.mkdir(parents=True, exist_ok=True)
        return replace(self, local_user_data_dir=account_root, lancedb_dir=account_root / "lancedb")

    def get_account_paths(self, account_id: str) -> dict[str, Path]:
        """Get all storage paths for a specific account."""
        base = self.accounts_dir / account_id
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
        }