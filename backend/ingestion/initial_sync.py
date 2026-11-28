"""Automatic, resumable First-Launch Mailbox Knowledge Sync."""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.automation.contact_resolver import ContactResolver
from backend.config import Settings
from backend.connectors.base import ConnectorError
from backend.connectors.factory import get_connector_for_account
from backend.processing import clean_raw_email, compute_stylometry
from backend.profiler.qwen_profiler import ProfilerUnavailable, QwenStyleProfiler
from backend.retrieval.embedder import LocalEmbedder
from backend.retrieval.vector_store import LanceDBVectorStore
from backend.schemas import CleanedSentEmail, RecipientProfile, UserStyleProfile
from backend.storage.account_manager import AccountManager
from backend.storage.profile_store import ProfileStore

_SYNC_LOCK = threading.Lock()
_ACTIVE_SYNCS: dict[str, threading.Thread] = {}
_PERSONA_MODEL_SEMAPHORE = threading.Semaphore(1)

_DEFAULT_LIMIT = 250
_INBOX_WARM_LIMIT = 25
_TOP_PERSONA_RECIPIENTS = 12
_MIN_EMAILS_FOR_PERSONA = 3


def _classify_audience_mode(email: CleanedSentEmail) -> str:
    """Classify audience topology for a cleaned sent email."""
    body_lower = (email.clean_body or "").lower()
    if any(marker in body_lower for marker in ("all hands", "everyone,", "dear subscribers", "newsletter", "team-wide")):
        return "broadcast_bcc"
    if any(marker in body_lower for marker in ("hi team", "hey team", "hi all", "hey all", "folks,")):
        return "group_cc"
    return "1on1_private"


def _deterministic_recipient_rules(recipient_emails: list[CleanedSentEmail]) -> tuple[str, list[str]]:
    """Compute deterministic per-recipient greeting and fallback persona rules."""
    metrics = compute_stylometry(recipient_emails)
    top_greeting = metrics.top_greetings[0].pattern if metrics.top_greetings else ""
    rules: list[str] = []
    if top_greeting:
        rules.append(f"Open with '{top_greeting}' when writing to this contact.")
    avg_words = metrics.avg_sentence_length_words
    if avg_words > 0:
        if avg_words <= 12:
            rules.append("Keep sentences short and direct (under 12 words on average).")
        elif avg_words >= 20:
            rules.append("Use detailed, well-structured sentences with full context.")
        else:
            rules.append("Use balanced, clear sentences at a conversational pace.")
    if metrics.exact_signoff and len(rules) < 2:
        rules.append(f"Close with '{metrics.exact_signoff}'.")
    return top_greeting, rules[:2]


def _extract_recipient_rules_with_qwen(
    acc_settings: Settings,
    recipient_email: str,
    samples: list[CleanedSentEmail],
    fallback_rules: list[str],
) -> list[str]:
    """Run qwen3:8b (think=True, throttled for 8GB VRAM) with graceful offline fallback."""
    snippets = "\n---\n".join(
        f"Subject: {item.subject}\n{item.clean_body[:400]}"
        for item in samples[:5]
    )
    prompt = (
        f"Analyze these {len(samples[:5])} sent emails to {recipient_email}. "
        "Return ONLY a JSON array of up to 2 concise style rules (each under 18 words) "
        "capturing greeting, tone, or length habits for this recipient.\n\n"
        f"{snippets}"
    )
    payload = {
        "model": acc_settings.model_name,
        "messages": [
            {"role": "system", "content": "Return a strict JSON array of 1-2 short style rule strings. No markdown."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": True,
        "options": {"temperature": 0.2, "num_ctx": acc_settings.ollama_num_ctx},
    }
    try:
        with _PERSONA_MODEL_SEMAPHORE:
            resp = httpx.post(
                f"{acc_settings.ollama_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=12.0,
            )
            resp.raise_for_status()
            content = str(resp.json().get("message", {}).get("content", "")).strip()
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                cleaned = [str(item).strip() for item in parsed if str(item).strip()]
                if cleaned:
                    return cleaned[:2]
    except Exception:
        pass
    return fallback_rules[:2]


def _run_initial_sync(
    account_id: str,
    settings: Settings,
    account_manager: AccountManager,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Execute the 4-stage first-launch sync pipeline for a single account."""
    acc_settings = settings.for_account(account_id)
    store = ProfileStore(acc_settings)

    try:
        # Stage 1: Fetch Sent Corpus
        store.update_initial_sync_state(stage="fetching_sent", error="")
        sent_connector = get_connector_for_account(account_id, settings, account_manager, purpose="sent")
        raw_records = sent_connector.fetch_sent_emails(limit=limit)
        store.save_raw_emails(raw_records)
        cleaned = [
            record
            for raw in raw_records
            if (record := clean_raw_email(raw, minimum_words=acc_settings.minimum_clean_words)) is not None
        ]
        store.save_cleaned_emails(cleaned)
        store.update_initial_sync_state(sent_total=len(cleaned), sent_processed=0)

        # Stage 2: Vector DB Indexing (LanceDB, deduplicated by message_id)
        store.update_initial_sync_state(stage="indexing_vectors")
        if cleaned:
            embedder = LocalEmbedder()
            embedder.load()
            audience_modes = {email.message_id: _classify_audience_mode(email) for email in cleaned}
            LanceDBVectorStore(acc_settings).upsert_emails(cleaned, embedder, audience_modes=audience_modes)
            store.update_initial_sync_state(sent_processed=len(cleaned))

        # Stage 3: Per-Recipient Persona & Global Stylometry Extraction
        store.update_initial_sync_state(stage="building_personas")
        personas_built = 0
        if cleaned:
            metrics = compute_stylometry(cleaned)
            try:
                style_card = QwenStyleProfiler(acc_settings).profile(cleaned, metrics)
            except ProfilerUnavailable:
                style_card = QwenStyleProfiler._heuristic_profile(cleaned, metrics)
            profile = UserStyleProfile(
                profile_id=f"sync-{account_id[:8]}",
                created_at=datetime.now(timezone.utc),
                deterministic_stylometry=metrics,
                global_style_card=style_card,
                corpus_statistics=store.corpus_statistics(cleaned),
            )
            store.save_profile(profile)
            ContactResolver(acc_settings.contacts_path).rebuild_from_emails(cleaned)

            by_recipient: dict[str, list[CleanedSentEmail]] = defaultdict(list)
            for item in cleaned:
                addr = (item.recipient_email or "").strip().lower()
                if addr:
                    by_recipient[addr].append(item)

            top_recipients = sorted(
                ((addr, items) for addr, items in by_recipient.items() if len(items) >= _MIN_EMAILS_FOR_PERSONA),
                key=lambda pair: len(pair[1]),
                reverse=True,
            )[:_TOP_PERSONA_RECIPIENTS]

            for addr, items in top_recipients:
                greeting, fallback_rules = _deterministic_recipient_rules(items)
                rules = _extract_recipient_rules_with_qwen(acc_settings, addr, items, fallback_rules)
                domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
                store.upsert_recipient_profile(
                    RecipientProfile(
                        recipient_email=addr,
                        recipient_domain=domain,
                        relationship_tier="unknown",
                        preferred_greeting=greeting,
                        sent_count=len(items),
                        learned_rules_json=rules[:2],
                        last_updated=datetime.now(timezone.utc),
                    )
                )
                personas_built += 1
                store.update_initial_sync_state(personas_built=personas_built)

        # Stage 4: Warm Read-Only Inbox Cache
        store.update_initial_sync_state(stage="caching_inbox")
        inbox_count = 0
        try:
            inbox_connector = get_connector_for_account(account_id, settings, account_manager, purpose="inbox")
            threads = inbox_connector.fetch_inbox_threads(limit=_INBOX_WARM_LIMIT)
            inbox_count = store.save_inbox_threads_cache(threads)
        except ConnectorError:
            inbox_count = 0

        return store.update_initial_sync_state(
            initial_sync_completed=True,
            stage="completed",
            sent_processed=len(cleaned),
            sent_total=len(cleaned),
            personas_built=personas_built,
            inbox_threads_indexed=inbox_count,
            last_synced_at=datetime.now(timezone.utc).isoformat(),
            error="",
        )
    except Exception as exc:
        try:
            return store.update_initial_sync_state(
                stage="error",
                error=str(exc),
            )
        except Exception:
            return {
                "initial_sync_completed": False,
                "running": False,
                "stage": "error",
                "sent_processed": 0,
                "sent_total": 0,
                "personas_built": 0,
                "inbox_threads_indexed": 0,
                "last_synced_at": "",
                "error": str(exc),
            }
    finally:
        with _SYNC_LOCK:
            _ACTIVE_SYNCS.pop(account_id, None)


def start_initial_sync(
    account_id: str,
    settings: Settings,
    account_manager: AccountManager,
    *,
    force: bool = False,
    limit: int = _DEFAULT_LIMIT,
    background: bool = True,
) -> dict[str, Any]:
    """Start (or return) the idempotent first-launch mailbox sync for ``account_id``."""
    acc_settings = settings.for_account(account_id)
    store = ProfileStore(acc_settings)

    with _SYNC_LOCK:
        active_thread = _ACTIVE_SYNCS.get(account_id)
        if active_thread is not None and active_thread.is_alive():
            return store.get_initial_sync_state()

        current = store.get_initial_sync_state()
        if current["initial_sync_completed"] and not force:
            return current

        state = store.update_initial_sync_state(
            initial_sync_completed=False if force else current["initial_sync_completed"],
            stage="fetching_sent",
            sent_processed=0,
            sent_total=0,
            personas_built=0,
            inbox_threads_indexed=0,
            error="",
        )

        if not background:
            # Release lock before running synchronously to avoid re-entrancy issues.
            pass
        else:
            thread = threading.Thread(
                target=_run_initial_sync,
                args=(account_id, settings, account_manager, limit),
                name=f"proteus-initial-sync-{account_id[:8]}",
                daemon=True,
            )
            _ACTIVE_SYNCS[account_id] = thread
            thread.start()
            return state

    return _run_initial_sync(account_id, settings, account_manager, limit)
