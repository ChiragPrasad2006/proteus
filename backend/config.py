"""Configuration for the local-first personalization backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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

    @property
    def lancedb_table_name(self) -> str:
        return "sent_emails"

    @property
    def oauth_token_dir(self) -> Path:
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
    def ollama_models(self) -> Tuple[str, ...]:
        """Prefer the exported personalized Ollama model, then the local base fallback."""
        return tuple(dict.fromkeys((self.model_name, self.ollama_fallback_model)))

    def ensure_local_directories(self) -> None:
        """Create only local directories used for tokens and user email-derived data."""
        self.local_user_data_dir.mkdir(parents=True, exist_ok=True)
        self.oauth_token_dir.mkdir(parents=True, exist_ok=True)
        self.lancedb_dir.mkdir(parents=True, exist_ok=True)
        self.hf_home.mkdir(parents=True, exist_ok=True)