"""FastAPI entrypoint for the local-first email personalization backend."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.automation import Dispatcher, StyleLearner
from backend.automation.contact_resolver import ContactResolver
from backend.config import Settings
from backend.connectors import (
    ConnectorError,
    GmailConnector,
    ImapConnector,
    LocalMailFileConnector,
    OutlookConnector,
)
from backend.generation import DrafterUnavailable, QwenDrafter
from backend.processing import clean_raw_email, compute_stylometry
from backend.profiler import ProfilerUnavailable, QwenStyleProfiler
from backend.retrieval import LanceDBVectorStore, LocalEmbedder
from backend.schemas import (
    AccountListResponse,
    AccountSwitchRequest,
    ApproveAndLearnRequest,
    ApproveAndLearnResponse,
    BuildProfileRequest,
    ChatSessionCreateRequest,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatSessionSummary,
    ChatTurnRequest,
    ChatTurnResponse,
    ContactResolution,
    DispatchRequest,
    DispatchResponse,
    DraftRequest,
    DraftResponse,
    GoogleAuthStartResponse,
    GoogleOAuthCredentialsStatus,
    GoogleOAuthCredentialsUpload,
    OnboardingRequest,
    OnboardingStatus,
    OutboundEmailRequest,
    RawSentEmail,
    ReindexRequest,
    ReindexResponse,
    RetrieveRequest,
    RetrieveResponse,
    RetrievedExample,
    SendReceipt,
    UserStyleProfile,
)
from backend.storage import AccountInfo, AccountManager, ChatSessionStore, ProfileStore

# Demo accounts created (and seeded) by the demo-seed endpoint.
DEMO_ACCOUNTS = [
    {"email": "sam@cloudscale.io", "display_name": "Sam Carter"},
    {"email": "chirag@expano.in", "display_name": "Chirag Sharma"},
]

# --- Natural-language intent parsing (qwen3:8b, think=True, structured JSON) -
_CHAT_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action",
        "to_names",
        "cc_names",
        "bcc_names",
        "subject_hint",
        "intent_bullets",
    ],
    "properties": {
        "action": {"type": "string", "enum": ["send", "reply", "forward", "draft"]},
        "to_names": {"type": "array", "items": {"type": "string"}},
        "cc_names": {"type": "array", "items": {"type": "string"}},
        "bcc_names": {"type": "array", "items": {"type": "string"}},
        "subject_hint": {"type": "string"},
        "intent_bullets": {"type": "string"},
    },
}

_CHAT_INTENT_SYSTEM = """You are an email intent parser for a personal email assistant.
Parse the user's natural-language request into STRICT JSON with exactly these fields:
- action: one of send, reply, forward, draft
- to_names: list of primary recipient names or email addresses mentioned for the To field
- cc_names: list of names/addresses explicitly for Cc
- bcc_names: list of names/addresses explicitly for Bcc
- subject_hint: a short subject line if the user implies one, else an empty string
- intent_bullets: a bulleted (- prefixed, newline separated) list of the concrete points the email must cover
Only use recipients actually mentioned. Never invent recipients or addresses. Return ONLY the JSON object."""

_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)\b")
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w.\-]+\.\w+")

# Capitalized tokens that commonly begin a request but are not recipient names.
_NAME_STOPWORDS = {
    "email", "send", "message", "write", "draft", "reply", "forward", "subject",
    "hi", "hello", "hey", "dear", "please", "the", "and", "that", "them", "cc", "bcc", "to",
}


def _normalize_intent(data: Any) -> dict[str, Any] | None:
    """Coerce a raw LLM JSON payload into the canonical intent dict."""
    if not isinstance(data, dict):
        return None

    def _as_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    action = str(data.get("action", "send")).strip().lower()
    if action not in ("send", "reply", "forward", "draft"):
        action = "send"
    return {
        "action": action,
        "to_names": _as_list(data.get("to_names")),
        "cc_names": _as_list(data.get("cc_names")),
        "bcc_names": _as_list(data.get("bcc_names")),
        "subject_hint": str(data.get("subject_hint") or "").strip(),
        "intent_bullets": str(data.get("intent_bullets") or "").strip(),
    }


def _extract_field_names(text: str, marker: str) -> list[str]:
    """Pull names/addresses following a ``to|cc|bcc`` marker out of free text."""
    match = re.search(rf"\b{marker}\b\s*[:\-]?\s*(.+)", text, re.IGNORECASE)
    if not match:
        return []
    chunk = match.group(1)
    chunk = re.split(r"\b(?:cc|bcc|to|subject)\b\s*[:\-]", chunk, maxsplit=1, flags=re.IGNORECASE)[0]
    chunk = re.split(r"[.;\n]", chunk)[0]
    found = _EMAIL_RE.findall(chunk)
    found += [m.group(1).strip() for m in _NAME_RE.finditer(chunk)]
    seen: set[str] = set()
    result: list[str] = []
    for name in found:
        key = name.lower()
        if key and key not in seen and key not in _NAME_STOPWORDS:
            seen.add(key)
            result.append(name)
    return result


def _build_contact_gazetteer(resolver: Any) -> dict[str, list[str]]:
    """Map lowercase name tokens to the canonical contact names that contain them.

    The deterministic fallback parser uses this so it recognises the contacts a
    user types regardless of case (``manu`` as well as ``Manu``). A token shared
    by two contacts keeps both names, which lets the resolver report ambiguity.
    """
    gazetteer: dict[str, list[str]] = {}
    try:
        contacts = resolver.list_contacts()
    except Exception:
        return gazetteer
    for contact in contacts:
        canonical = (contact.full_name or contact.email or "").strip()
        if not canonical:
            continue
        forms = {
            (contact.full_name or "").strip().lower(),
            (contact.first_name or "").strip().lower(),
            (contact.last_name or "").strip().lower(),
            " ".join(p for p in (contact.first_name, contact.last_name) if p).strip().lower(),
        }
        tokens: set[str] = set()
        for form in forms:
            if len(form) >= 3:
                tokens.add(form)
            for token in re.split(r"[\s._\-+@]+", form):
                if len(token) >= 3 and not token.isdigit():
                    tokens.add(token)
        for token in tokens:
            bucket = gazetteer.setdefault(token, [])
            if canonical not in bucket:
                bucket.append(canonical)
    return gazetteer


def _gazetteer_field_split(
    lowered_text: str, gazetteer: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Assign mentioned contacts to to/cc/bcc via the first marker of each kind.

    Only the first ``to``/``cc``/``bcc`` keyword is treated as a field marker, so
    phrasing such as "cc attached to Jatin" does not re-open the To field.
    """
    marker_positions: list[tuple[int, str]] = []
    for keyword in ("to", "cc", "bcc"):
        match = re.search(rf"\b{keyword}\b", lowered_text)
        if match:
            marker_positions.append((match.start(), keyword))
    marker_positions.sort()

    def field_for(position: int) -> str:
        field = "to"
        for marker_start, keyword in marker_positions:
            if marker_start <= position:
                field = keyword
            else:
                break
        return field

    buckets: dict[str, list[str]] = {"to": [], "cc": [], "bcc": []}
    for match in re.finditer(r"[a-z0-9']+", lowered_text):
        names = gazetteer.get(match.group(0))
        if not names:
            continue
        # Ambiguous token -> keep the bare query so the resolver asks the user.
        value = names[0] if len(names) == 1 else match.group(0)
        bucket = buckets[field_for(match.start())]
        if value not in bucket:
            bucket.append(value)
    return buckets


def _heuristic_intent(user_message: str, gazetteer: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Deterministic fallback parser used when the local model is unavailable."""
    text = (user_message or "").strip()
    lowered = text.lower()
    action = "send"
    for candidate in ("reply", "forward", "draft"):
        if re.search(rf"\b{candidate}\b", lowered):
            action = candidate
            break

    to_names: list[str] = []
    cc_names: list[str] = []
    bcc_names: list[str] = []
    if gazetteer:
        split = _gazetteer_field_split(lowered, gazetteer)
        to_names, cc_names, bcc_names = split["to"], split["cc"], split["bcc"]

    if not (to_names or cc_names or bcc_names):
        bcc_names = _extract_field_names(text, "bcc")
        cc_names = _extract_field_names(text, "cc")
        to_names = _extract_field_names(text, "to")
    if not (to_names or cc_names or bcc_names):
        to_names = [
            m.group(1).strip()
            for m in _NAME_RE.finditer(text)
            if m.group(1).strip().lower() not in _NAME_STOPWORDS
        ][:1]

    subject_match = re.search(r"subject[:\s]+([^\n]+)", text, re.IGNORECASE)
    subject_hint = subject_match.group(1).strip().strip("\"'") if subject_match else ""

    bullets = [
        line.strip().lstrip("-•* \t")
        for line in text.splitlines()
        if line.strip().startswith(("-", "•", "*"))
    ]
    intent_bullets = "\n".join(f"- {b}" for b in bullets) if bullets else text

    return {
        "action": action,
        "to_names": to_names,
        "cc_names": cc_names,
        "bcc_names": bcc_names,
        "subject_hint": subject_hint,
        "intent_bullets": intent_bullets,
    }


def _parse_chat_intent(
    settings: Settings,
    user_message: str,
    contact_names: list[str],
    gazetteer: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Parse a natural-language turn with qwen3:8b, falling back to heuristics."""
    endpoint = f"{settings.ollama_url.rstrip('/')}/api/chat"
    hints = ", ".join(sorted({name for name in contact_names if name})[:60])
    user_content = f"Known contacts (reference only): {hints}\n\nUser request:\n{user_message}"

    parsed: dict[str, Any] | None = None
    try:
        response = httpx.post(
            endpoint,
            json={
                "model": settings.ollama_fallback_model,  # qwen3:8b
                "messages": [
                    {"role": "system", "content": _CHAT_INTENT_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "format": _CHAT_INTENT_SCHEMA,
                "options": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "top_k": 20,
                    "num_ctx": settings.ollama_num_ctx,
                    "think": True,  # deep reasoning for intent parsing
                },
            },
            timeout=120,
        )
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "")
            content = re.sub(r" thinking.*?</think>", "", content, flags=re.DOTALL).strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
            parsed = _normalize_intent(json.loads(content))
    except Exception:
        parsed = None

    if parsed is None:
        parsed = _heuristic_intent(user_message, gazetteer)
        parsed["source"] = "heuristic"
    else:
        parsed["source"] = "ollama"
    return parsed


def _fallback_draft(profile: UserStyleProfile, primary_name: str, intent_bullets: str) -> str:
    """Deterministic, clearly-labelled skeleton used only when the model is offline."""
    stylometry = profile.deterministic_stylometry
    first_name = (primary_name or "").split()[0] if primary_name else ""
    greeting = ""
    if stylometry.top_greetings:
        greeting = stylometry.top_greetings[0].pattern.replace("{first_name}", first_name).strip()
    if not greeting:
        greeting = f"Hi {first_name}," if first_name else "Hi,"
    signoff = stylometry.exact_signoff or "Best"
    body = intent_bullets or "(no points provided)"
    return f"{greeting}\n\n{body}\n\n{signoff}"


def _first_name_from_email(email: str | None) -> str:
    """Derive a friendly first name from a recipient address local-part."""
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0]
    for separator in (".", "_", "-", "+"):
        local = local.split(separator, 1)[0]
    return local.capitalize()


def _resolve_primary_name(resolution_list: list[Any]) -> str:
    for resolution in resolution_list:
        matched = getattr(resolution, "matched", None)
        if matched is not None:
            return matched.full_name or matched.email
    return ""


def _gpu_status() -> dict[str, Any]:
    """Return concise NVIDIA telemetry when nvidia-smi is available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        name, total, free = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",")]
        return {"available": True, "name": name, "vram_total_mib": int(total), "vram_free_mib": int(free)}
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
        return {"available": False}


def _sentence_transformer_cache_status(settings: Settings) -> dict[str, Any]:
    """Check cache presence only: health checks must never trigger a model download."""
    hub_model_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--sentence-transformers--all-MiniLM-L12-v2"
    ready = hub_model_dir.exists() or settings.sentence_transformer_cache_dir.exists() and any(
        settings.sentence_transformer_cache_dir.iterdir()
    )
    return {
        "model": settings.sentence_transformer_model,
        "cache_ready": ready,
        "cache_dir": str(settings.sentence_transformer_cache_dir),
    }


def _connector_from_request(request: OnboardingRequest, settings: Settings):
    """Construct a connector without persisting password-like request fields."""
    credentials = request.credentials
    if request.provider == "gmail":
        client_path = credentials.get("client_secrets_file") or str(settings.google_client_secrets_file)
        if not client_path:
            raise ConnectorError("gmail credentials.client_secrets_file is required.")
        return GmailConnector(
            Path(client_path).expanduser(),
            settings.oauth_token_dir / "gmail_token.json",
        )
    if request.provider == "outlook":
        return OutlookConnector(
            client_id=str(credentials.get("client_id", "")),
            token_cache_file=settings.oauth_token_dir / "outlook_token_cache.json",
            tenant_id=str(credentials.get("tenant_id", "common")),
        )
    if request.provider == "imap":
        return ImapConnector(
            host=str(credentials.get("host", "")),
            username=str(credentials.get("username", "")),
            password=str(credentials.get("password", "")),
            folder=str(credentials.get("folder", "Sent")),
            port=int(credentials.get("port", 993)),
        )
    path = request.file_path or credentials.get("file_path")
    if not path:
        raise ConnectorError("mbox requires file_path or credentials.file_path.")
    return LocalMailFileConnector(Path(path).expanduser())


def _clean_and_persist(raw_records: list[RawSentEmail], store: ProfileStore, settings: Settings) -> OnboardingStatus:
    """Persist raw extraction and its clean retained subset as a single pipeline stage."""
    store.save_raw_emails(raw_records)
    cleaned = [
        record
        for raw in raw_records
        if (record := clean_raw_email(raw, minimum_words=settings.minimum_clean_words)) is not None
    ]
    storage_path = store.save_cleaned_emails(cleaned)
    return OnboardingStatus(
        provider="local",
        extracted_emails=len(raw_records),
        clean_emails_retained=len(cleaned),
        dropped_emails=len(raw_records) - len(cleaned),
        storage_path=str(storage_path),
    )


def _run_post_connect_pipeline(
    settings: Settings, client_secrets_file: Path, token_file: Path, limit: int
) -> None:
    """Extraction -> cleaning -> profiling -> indexing -> contacts, all best-effort.

    Runs as a background task after the OAuth callback so the redirect is immediate.
    """
    try:
        connector = GmailConnector(client_secrets_file, token_file)
        records = connector.fetch_sent_emails(limit)
        store = ProfileStore(settings)
        _clean_and_persist(records, store, settings)
        cleaned = store.load_cleaned_emails()
        if not cleaned:
            return

        metrics = compute_stylometry(cleaned)
        try:
            card = QwenStyleProfiler(settings).profile(cleaned, metrics)
            profile = UserStyleProfile(
                profile_id=str(uuid.uuid4()),
                created_at=datetime.now(timezone.utc),
                deterministic_stylometry=metrics,
                global_style_card=card,
                corpus_statistics=store.corpus_statistics(cleaned),
            )
            store.save_profile(profile)
        except ProfilerUnavailable:
            pass

        try:
            embedder = LocalEmbedder()
            embedder.load()
            LanceDBVectorStore(settings).index_emails(cleaned, embedder, force_recreate=True)
        except Exception:
            pass

        try:
            ContactResolver(settings.contacts_path).rebuild_from_emails(cleaned)
        except Exception:
            pass
    except Exception:
        # Never let a background extraction failure surface to the user's browser.
        pass


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance suitable for production or isolated tests."""
    runtime_settings = settings or Settings()
    account_manager = AccountManager(runtime_settings.local_user_data_dir)

    try:
        embedder = LocalEmbedder()
    except Exception:
        embedder = None  # type: ignore[assignment]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime_settings.ensure_local_directories()
        if embedder is not None:
            try:
                embedder.load()
            except Exception:
                pass
        yield

    app = FastAPI(title="Personalized AI Email Writer Local Backend", version="0.2.0", lifespan=lifespan)
    app.state.settings = runtime_settings
    app.state.account_manager = account_manager
    app.state.oauth_flows = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Account resolution (X-Account-ID enforcement) ----------------------
    def _resolve_account(x_account_id: str | None) -> tuple[AccountInfo | None, Settings]:
        """Resolve the account selected by the header to its isolated Settings."""
        if x_account_id:
            account = account_manager.get_account(x_account_id)
            if account is None:
                raise HTTPException(status_code=404, detail=f"Unknown account '{x_account_id}'.")
            return account, runtime_settings.for_account(account.account_id)
        active = account_manager.get_active_account()
        if active is not None:
            return active, runtime_settings.for_account(active.account_id)
        return None, runtime_settings

    def account_ctx(
        x_account_id: Annotated[str | None, Header(alias="X-Account-ID")] = None,
    ) -> tuple[AccountInfo | None, Settings]:
        """FastAPI dependency enforcing account isolation across /api/* endpoints.

        ``X-Account-ID`` is authoritative: an unknown id yields 404. When the header is
        omitted the active account is used, so single-account and CLI callers keep working.
        """
        return _resolve_account(x_account_id)

    def _connector_for_account(acc_settings: Settings) -> GmailConnector:
        """Build a Gmail connector bound to the account's stored OAuth token."""
        return GmailConnector(
            acc_settings.google_client_secrets_file,
            acc_settings.oauth_token_dir / "gmail_token.json",
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Report local inference, GPU, and embedding-cache readiness without downloading models."""
        retrieval_info: dict[str, Any] = {
            "embedder_loaded": bool(embedder and embedder.is_loaded),
            "embedder_cached": bool(embedder and embedder.is_model_cached()),
        }
        try:
            retrieval_info["vector_store_count"] = LanceDBVectorStore(runtime_settings).count()
        except Exception:
            retrieval_info["vector_store_count"] = 0

        qwen_avail = QwenStyleProfiler(runtime_settings).availability()
        gen_avail = QwenDrafter(runtime_settings).availability()
        gpu_info = _gpu_status()

        accounts = account_manager.list_accounts()
        active = account_manager.get_active_account()
        return {
            "status": "ok",
            "qwen": {
                **qwen_avail,
                "available": qwen_avail.get("preferred_ollama_model_available", False),
                "model_available": qwen_avail.get("preferred_ollama_model_available", False),
            },
            "generation": {
                **gen_avail,
                "available": gen_avail.get("preferred_ollama_model_available", False),
                "model_available": gen_avail.get("preferred_ollama_model_available", False),
            },
            "gpu": {
                **gpu_info,
                "gpu_name": gpu_info.get("name"),
            },
            "sentence_transformer": _sentence_transformer_cache_status(runtime_settings),
            "local_user_data_dir": str(runtime_settings.local_user_data_dir),
            "retrieval": retrieval_info,
            "automation": {
                "dispatcher_ready": True,
                "style_learner_ready": True,
            },
            "accounts": {
                "count": len(accounts),
                "active_account_id": active.account_id if active else None,
            },
        }

    # --- Google OAuth2 desktop connect --------------------------------------
    @app.post("/api/auth/google/start", response_model=GoogleAuthStartResponse)
    def google_auth_start() -> GoogleAuthStartResponse:
        """Begin the Google OAuth2 desktop flow and return the consent URL."""
        connector = GmailConnector(
            runtime_settings.google_client_secrets_file,
            runtime_settings.oauth_token_dir / "pending_token.json",
        )
        redirect_uri = runtime_settings.google_oauth_redirect_uri
        state = secrets.token_urlsafe(24)
        try:
            flow, auth_url, returned_state = connector.authorization_url(
                redirect_uri=redirect_uri, state=state
            )
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Persist the flow (with its PKCE verifier) until the callback arrives.
        cutoff = time.time() - 900
        flows = {k: v for k, v in app.state.oauth_flows.items() if v.get("created_at", 0) >= cutoff}
        flows[returned_state] = {"flow": flow, "created_at": time.time(), "redirect_uri": redirect_uri}
        app.state.oauth_flows = flows
        return GoogleAuthStartResponse(auth_url=auth_url, state=returned_state, redirect_uri=redirect_uri)

    @app.get("/api/auth/google/callback")
    def google_auth_callback(
        background_tasks: BackgroundTasks,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        """Exchange the code, create/activate the account, then redirect to the frontend."""
        frontend = runtime_settings.frontend_url.rstrip("/")
        if error:
            return RedirectResponse(url=f"{frontend}/?auth=error&reason={error}")
        if not code or not state:
            return RedirectResponse(url=f"{frontend}/?auth=error&reason=missing_code_or_state")

        pending = app.state.oauth_flows.pop(state, None)
        if pending is None:
            return RedirectResponse(url=f"{frontend}/?auth=error&reason=unknown_or_expired_state")

        client_secrets = runtime_settings.google_client_secrets_file
        connector = GmailConnector(client_secrets, runtime_settings.oauth_token_dir / "pending_token.json")
        try:
            credentials = connector.exchange_code(pending["flow"], code, pending.get("redirect_uri"))
        except ConnectorError:
            return RedirectResponse(url=f"{frontend}/?auth=error&reason=exchange_failed")

        try:
            info = connector.fetch_user_info(credentials)
        except ConnectorError:
            info = {}

        email = str(info.get("email") or "").strip().lower()
        if not email:
            return RedirectResponse(url=f"{frontend}/?auth=error&reason=no_email_returned")

        display_name = str(info.get("name") or email.split("@")[0])
        avatar_url = str(info.get("picture") or "")

        existing = account_manager.get_account_by_email(email)
        if existing is not None:
            account_manager.update_account(
                existing.account_id,
                display_name=display_name,
                avatar_url=avatar_url,
                provider="gmail",
            )
            account = account_manager.get_account(existing.account_id) or existing
        else:
            account = account_manager.create_account(
                email=email, display_name=display_name, provider="gmail", avatar_url=avatar_url
            )
        account_manager.set_active_account(account.account_id)

        acc_settings = runtime_settings.for_account(account.account_id)
        token_path = acc_settings.oauth_token_dir / "gmail_token.json"
        try:
            connector.save_credentials(credentials, token_path)
        except Exception:
            pass

        # Trigger extraction + profiling + indexing + contacts after the redirect.
        background_tasks.add_task(
            _run_post_connect_pipeline,
            acc_settings,
            client_secrets,
            token_path,
            runtime_settings.default_extract_limit,
        )
        return RedirectResponse(url=f"{frontend}/?auth=success&account_id={account.account_id}")

    @app.get("/api/auth/google/status", response_model=GoogleOAuthCredentialsStatus)
    def google_auth_status() -> GoogleOAuthCredentialsStatus:
        """Check if Google OAuth client_secret.json is configured."""
        client_secrets_path = runtime_settings.local_user_data_dir / "client_secret.json"
        if client_secrets_path.exists():
            return GoogleOAuthCredentialsStatus(configured=True, message="Google OAuth credentials are configured")
        return GoogleOAuthCredentialsStatus(configured=False, message="Google OAuth credentials not found. Please upload client_secret.json")

    @app.post("/api/auth/google/upload-credentials", response_model=GoogleOAuthCredentialsStatus)
    def google_auth_upload_credentials(request: GoogleOAuthCredentialsUpload) -> GoogleOAuthCredentialsStatus:
        """Upload and validate Google OAuth client_secret.json."""
        import json
        try:
            creds = json.loads(request.client_secret_json)
            # Validate it has the required structure for a desktop OAuth client
            if "installed" not in creds and "web" not in creds:
                raise ValueError("Invalid client_secret.json: must contain 'installed' or 'web' client configuration")
            client_secrets_path = runtime_settings.local_user_data_dir / "client_secret.json"
            client_secrets_path.write_text(request.client_secret_json, encoding="utf-8")
            return GoogleOAuthCredentialsStatus(configured=True, message="Google OAuth credentials uploaded successfully")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to save credentials: {exc}")

    # --- Account management -------------------------------------------------
    @app.get("/api/accounts", response_model=AccountListResponse)
    def list_accounts() -> AccountListResponse:
        """List every connected account and the active one."""
        accounts = account_manager.list_accounts()
        active = account_manager.get_active_account()
        return AccountListResponse(
            accounts=[account.to_dict() for account in accounts],
            active_account_id=active.account_id if active else None,
        )

    @app.post("/api/accounts/switch")
    def switch_account(request: AccountSwitchRequest) -> dict[str, Any]:
        """Mark an account as the active one (only one active at a time)."""
        account = account_manager.set_active_account(request.account_id)
        if account is None:
            raise HTTPException(status_code=404, detail=f"Unknown account '{request.account_id}'.")
        return account.to_dict()

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: str) -> dict[str, Any]:
        """Delete an account and all of its isolated data."""
        if not account_manager.delete_account(account_id):
            raise HTTPException(status_code=404, detail=f"Unknown account '{account_id}'.")
        return {"deleted": True, "account_id": account_id}

    # --- Onboarding ---------------------------------------------------------
    @app.post("/api/onboarding/connect-and-extract", response_model=OnboardingStatus)
    def connect_and_extract(
        request: OnboardingRequest, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> OnboardingStatus:
        """Fetch Sent mail from the selected provider and retain cleaned local records."""
        _, acc_settings = ctx
        try:
            connector = _connector_from_request(request, acc_settings)
            raw_records = connector.fetch_sent_emails(request.limit)
            store = ProfileStore(acc_settings)
            status = _clean_and_persist(raw_records, store, acc_settings)
            return status.model_copy(update={"provider": request.provider})
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/build-profile", response_model=UserStyleProfile)
    def build_profile(
        _: BuildProfileRequest | None = None,
        ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx),
    ) -> UserStyleProfile:
        """Build and persist a merged deterministic + local-Qwen profile from cleaned Sent mail."""
        _, acc_settings = ctx
        store = ProfileStore(acc_settings)
        cleaned = store.load_cleaned_emails()
        if not cleaned:
            raise HTTPException(status_code=404, detail="No cleaned Sent corpus found. Extract or demo-seed first.")
        metrics = compute_stylometry(cleaned)
        try:
            global_style_card = QwenStyleProfiler(acc_settings).profile(cleaned, metrics)
        except ProfilerUnavailable as exc:
            raise HTTPException(status_code=503, detail=f"Local Qwen profiler unavailable: {exc}") from exc
        profile = UserStyleProfile(
            profile_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            deterministic_stylometry=metrics,
            global_style_card=global_style_card,
            corpus_statistics=store.corpus_statistics(cleaned),
        )
        store.save_profile(profile)
        if embedder is not None:
            try:
                LanceDBVectorStore(acc_settings).index_emails(cleaned, embedder)
            except Exception:
                pass
        return profile

    @app.get("/api/profile", response_model=UserStyleProfile)
    def get_profile(ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)) -> UserStyleProfile:
        """Return the active account's locally stored style profile."""
        _, acc_settings = ctx
        profile = ProfileStore(acc_settings).load_profile()
        if profile is None:
            raise HTTPException(status_code=404, detail="No profile has been built yet.")
        return profile

    @app.post("/api/onboarding/demo-seed", response_model=OnboardingStatus)
    def demo_seed() -> OnboardingStatus:
        """Create the two demo accounts and seed each from a local JSON fixture.

        Runs without OAuth credentials or an X-Account-ID header so a fresh install can
        be exercised end-to-end. The first demo account is left active.
        """
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "demo_sent_emails.json"
        records = [RawSentEmail.model_validate(item) for item in json.loads(fixture_path.read_text(encoding="utf-8"))]

        last_status: OnboardingStatus | None = None
        created_ids: list[str] = []
        total_extracted = 0
        total_clean = 0
        total_dropped = 0
        for spec in DEMO_ACCOUNTS:
            account = account_manager.get_account_by_email(spec["email"])
            if account is None:
                account = account_manager.create_account(
                    email=spec["email"], display_name=spec["display_name"], provider="gmail"
                )
            created_ids.append(account.account_id)
            acc_settings = runtime_settings.for_account(account.account_id)
            status = _clean_and_persist(records, ProfileStore(acc_settings), acc_settings)
            last_status = status
            total_extracted += status.extracted_emails
            total_clean += status.clean_emails_retained
            total_dropped += status.dropped_emails

        if created_ids:
            account_manager.set_active_account(created_ids[0])

        if last_status is None:  # pragma: no cover - DEMO_ACCOUNTS is never empty
            raise HTTPException(status_code=500, detail="No demo accounts configured.")
        return last_status.model_copy(
            update={
                "provider": "demo",
                "extracted_emails": total_extracted,
                "clean_emails_retained": total_clean,
                "dropped_emails": total_dropped,
            }
        )

    # --- Tier 2: Retrieval endpoints ---------------------------------------
    @app.post("/api/retrieval/reindex", response_model=ReindexResponse)
    def reindex(
        _: ReindexRequest | None = None,
        ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx),
    ) -> ReindexResponse:
        """Re-index all cleaned emails into the account's LanceDB vector store."""
        _, acc_settings = ctx
        cleaned = ProfileStore(acc_settings).load_cleaned_emails()
        if not cleaned:
            raise HTTPException(status_code=404, detail="No cleaned corpus found. Extract or demo-seed first.")
        if embedder is None:
            raise HTTPException(status_code=503, detail="Embedder unavailable: sentence-transformers not installed.")
        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc
        indexed = LanceDBVectorStore(acc_settings).index_emails(cleaned, embedder, force_recreate=True)
        return ReindexResponse(indexed_count=indexed, table_name=acc_settings.lancedb_table_name)

    @app.post("/api/retrieval/search", response_model=RetrieveResponse)
    def search(
        request: RetrieveRequest, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> RetrieveResponse:
        """Search for few-shot examples using semantic similarity with time-decayed reranking."""
        _, acc_settings = ctx
        if embedder is None:
            raise HTTPException(status_code=503, detail="Embedder unavailable: sentence-transformers not installed.")
        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc
        vector_store = LanceDBVectorStore(acc_settings)
        examples = vector_store.retrieve_few_shot_examples(
            embedder=embedder,
            recipient_email=request.recipient_email,
            recipient_domain=request.recipient_domain,
            query_text=request.query_text,
            k=request.k,
            min_word_count=request.min_word_count,
            target_audience_mode=request.audience_mode or "1on1_private",
        )
        clean_examples = [
            {k: v for k, v in ex.items() if k in RetrievedExample.model_fields} for ex in examples
        ]
        return RetrieveResponse(
            examples=[RetrievedExample(**ex) for ex in clean_examples],
            total_indexed=vector_store.count(),
        )

    # --- Tier 3: Generation endpoint with audience topology -----------------
    @app.post("/api/draft/generate", response_model=DraftResponse)
    def generate_draft(
        request: DraftRequest, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> DraftResponse:
        """Generate a personalized email draft using the fine-tuned Qwen model with audience topology."""
        _, acc_settings = ctx
        store = ProfileStore(acc_settings)
        profile = store.load_profile()
        if profile is None:
            raise HTTPException(status_code=404, detail="No profile has been built yet. Run /api/onboarding/build-profile first.")
        if embedder is None:
            raise HTTPException(status_code=503, detail="Embedder unavailable: sentence-transformers not installed.")
        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc

        vector_store = LanceDBVectorStore(acc_settings)
        to_recipients = [request.recipient_email] if request.recipient_email else []
        cc_recipients = request.cc or []
        bcc_recipients = request.bcc or []

        recipient_profiles = {}
        for email in to_recipients + cc_recipients:
            if email:
                rp = store.get_recipient_profile(email)
                if rp:
                    recipient_profiles[email.lower()] = rp

        try:
            draft = QwenDrafter(acc_settings).generate_draft(
                profile=profile,
                cleaned_emails=store.load_cleaned_emails(),
                intent_bullets=request.intent_bullets,
                recipient_email=request.recipient_email,
                incoming_context=request.incoming_context,
                model_name=request.model_name,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                recipient_profiles=recipient_profiles,
            )
        except DrafterUnavailable:
            # Offline installs still get a deterministic, clearly-shaped skeleton draft
            # rather than a hard failure, mirroring the chat-turn fallback path.
            draft = _fallback_draft(
                profile, _first_name_from_email(request.recipient_email), request.intent_bullets
            )

        recipient_domain = None
        if request.recipient_email:
            recipient_domain = request.recipient_email.split("@")[-1] if "@" in request.recipient_email else None
        query_text = " ".join([request.incoming_context or "", request.intent_bullets]).strip()

        target_audience_mode = "1on1_private"
        if cc_recipients:
            target_audience_mode = "group_cc"
        elif bcc_recipients and len(bcc_recipients) >= 2:
            target_audience_mode = "broadcast_bcc"

        examples = vector_store.retrieve_few_shot_examples(
            embedder=embedder,
            recipient_email=request.recipient_email,
            recipient_domain=recipient_domain,
            query_text=query_text,
            k=2,
            target_audience_mode=target_audience_mode,
        )
        clean_examples = [
            {k: v for k, v in ex.items() if k in RetrievedExample.model_fields} for ex in examples
        ]

        return DraftResponse(
            draft=draft,
            model_used=acc_settings.model_name,
            retrieved_examples=[RetrievedExample(**ex) for ex in clean_examples],
            profile_id=profile.profile_id,
        )

    # --- Tier 4: Autonomous dispatch endpoints ------------------------------
    @app.post("/api/email/dispatch", response_model=DispatchResponse)
    def dispatch_email(
        request: DispatchRequest, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> DispatchResponse:
        """Autonomous email dispatch with first-recipient gate."""
        _, acc_settings = ctx
        return Dispatcher(acc_settings).dispatch(request)

    @app.post("/api/email/approve-and-learn", response_model=ApproveAndLearnResponse)
    def approve_and_learn(
        request: ApproveAndLearnRequest, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> ApproveAndLearnResponse:
        """Approve a pending draft and extract style rules from user edits."""
        _, acc_settings = ctx
        return StyleLearner(acc_settings).approve_and_learn(request)

    # --- Chat sessions ------------------------------------------------------
    @app.get("/api/chat/sessions", response_model=ChatSessionListResponse)
    def list_chat_sessions(
        ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx),
    ) -> ChatSessionListResponse:
        """List chat sessions for the resolved account, newest first."""
        account, acc_settings = ctx
        if account is None:
            return ChatSessionListResponse(sessions=[])
        sessions = ChatSessionStore(acc_settings.chat_sessions_path).list_sessions(account.account_id)
        return ChatSessionListResponse(sessions=[ChatSessionSummary.model_validate(s) for s in sessions])

    @app.post("/api/chat/sessions", response_model=ChatSessionSummary)
    def create_chat_session(
        request: ChatSessionCreateRequest,
        ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx),
    ) -> ChatSessionSummary:
        """Create a new chat session for the resolved account."""
        account, acc_settings = ctx
        if account is None:
            raise HTTPException(status_code=400, detail="X-Account-ID header is required to create a session.")
        session = ChatSessionStore(acc_settings.chat_sessions_path).create_session(
            account.account_id, title=request.title
        )
        return ChatSessionSummary.model_validate(session)

    @app.get("/api/chat/sessions/{session_id}", response_model=ChatSessionDetailResponse)
    def get_chat_session(
        session_id: str, ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx)
    ) -> ChatSessionDetailResponse:
        """Return a session with its messages and draft cards."""
        _, acc_settings = ctx
        detail = ChatSessionStore(acc_settings.chat_sessions_path).get_session(session_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        return ChatSessionDetailResponse(**detail)

    @app.post("/api/chat/turn", response_model=ChatTurnResponse)
    def chat_turn(
        request: ChatTurnRequest,
        x_account_id: Annotated[str | None, Header(alias="X-Account-ID")] = None,
        ctx: tuple[AccountInfo | None, Settings] = Depends(account_ctx),
    ) -> ChatTurnResponse:
        """Parse NL -> resolve contacts -> RAG -> draft -> first-recipient gate."""
        account, acc_settings = ctx
        # The X-Account-ID header is authoritative: when it resolves to a valid
        # account, a conflicting account_id in the body is rejected instead of
        # switching stores. Without a header the body may still select one.
        if request.account_id and request.account_id != (account.account_id if account else None):
            if x_account_id:
                raise HTTPException(
                    status_code=403,
                    detail="account_id in the body conflicts with the X-Account-ID header.",
                )
            resolved = account_manager.get_account(request.account_id)
            if resolved is None:
                raise HTTPException(status_code=404, detail=f"Unknown account '{request.account_id}'.")
            account = resolved
            acc_settings = runtime_settings.for_account(resolved.account_id)
        if account is None:
            raise HTTPException(
                status_code=400,
                detail="X-Account-ID header (or account_id in the body) is required.",
            )

        store = ProfileStore(acc_settings)
        sessions = ChatSessionStore(acc_settings.chat_sessions_path)

        if request.session_id:
            session = sessions.get_session_summary(request.session_id)
            if session is not None and session["account_id"] != account.account_id:
                raise HTTPException(status_code=404, detail="Session not found for this account.")
            if session is None:
                session = sessions.create_session(account.account_id, session_id=request.session_id)
        else:
            session = sessions.create_session(account.account_id, title=request.user_message[:60])
        session_id = session["session_id"]
        sessions.append_message(session_id, "user", request.user_message)

        # Contact registry (rebuild once from the corpus when empty).
        resolver = ContactResolver(acc_settings.contacts_path)
        try:
            if resolver.is_empty():
                resolver.rebuild_from_emails(store.load_cleaned_emails())
        except Exception:
            pass

        parsed = _parse_chat_intent(
            acc_settings,
            request.user_message,
            resolver.contact_names(),
            _build_contact_gazetteer(resolver),
        )

        to_res = resolver.resolve_many(parsed["to_names"])
        cc_res = resolver.resolve_many(parsed["cc_names"])
        bcc_res = resolver.resolve_many(parsed["bcc_names"])
        resolution_lists = {"to": to_res, "cc": cc_res, "bcc": bcc_res}

        def _schema_resolution(resolution: Any) -> ContactResolution:
            matched = resolution.matched
            return ContactResolution(
                query=resolution.query,
                status=resolution.status,
                matched_email=matched.email if matched else None,
                matched_name=(matched.full_name or matched.email) if matched else None,
                candidates=[c.to_dict() for c in resolution.candidates],
                reason=resolution.reason,
            )

        def _schemas(lists: dict[str, list[Any]]) -> dict[str, list[ContactResolution]]:
            return {key: [_schema_resolution(r) for r in value] for key, value in lists.items()}

        # No recipient at all -> ask immediately.
        if not to_res:
            message = "I couldn't find a recipient. Who should I send this to?"
            sessions.append_message(session_id, "assistant", message, metadata={"status": "NEEDS_CLARIFICATION"})
            return ChatTurnResponse(
                session_id=session_id,
                status="NEEDS_CLARIFICATION",
                assistant_message=message,
                parsed=parsed,
                resolutions=_schemas(resolution_lists),
            )

        # Unknown or ambiguous names -> ask for clarification instead of guessing.
        unresolved = [r for r in (to_res + cc_res + bcc_res) if r.status != "MATCHED"]
        if unresolved:
            lines: list[str] = []
            for resolution in unresolved:
                if resolution.candidates:
                    options = ", ".join(
                        f"{c.full_name or c.email} <{c.email}>" for c in resolution.candidates
                    )
                    lines.append(f"'{resolution.query}' is ambiguous - did you mean: {options}?")
                else:
                    lines.append(
                        f"I don't have a contact matching '{resolution.query}'. Please confirm their email address."
                    )
            message = "I need clarification before drafting:\n" + "\n".join(lines)
            sessions.append_message(session_id, "assistant", message, metadata={"status": "NEEDS_CLARIFICATION"})
            return ChatTurnResponse(
                session_id=session_id,
                status="NEEDS_CLARIFICATION",
                assistant_message=message,
                parsed=parsed,
                resolutions=_schemas(resolution_lists),
            )

        to_emails = [r.matched.email for r in to_res if r.matched]
        cc_emails = [r.matched.email for r in cc_res if r.matched]
        bcc_emails = [r.matched.email for r in bcc_res if r.matched]

        # Tier 4: first-recipient gate.
        review_reasons: list[str] = []
        for email in to_emails + cc_emails:
            recipient_profile = store.get_recipient_profile(email)
            if recipient_profile is None or recipient_profile.sent_count == 0:
                review_reasons.append(f"first contact with {email}")
        if not request.auto_send:
            review_reasons.append("auto_send is False (first-recipient gate)")

        profile = store.load_profile()
        draft_body: str | None = None
        draft_source = "model"
        if profile is None:
            review_reasons.append("no style profile built yet")
        else:
            try:
                recipient_profiles = {}
                for email in to_emails + cc_emails:
                    recipient_profile = store.get_recipient_profile(email)
                    if recipient_profile:
                        recipient_profiles[email.lower()] = recipient_profile
                draft_body = QwenDrafter(acc_settings).generate_draft(
                    profile=profile,
                    cleaned_emails=store.load_cleaned_emails(),
                    intent_bullets=parsed["intent_bullets"],
                    recipient_email=to_emails[0] if to_emails else None,
                    incoming_context=None,
                    cc_recipients=cc_emails,
                    bcc_recipients=bcc_emails,
                    recipient_profiles=recipient_profiles,
                )
            except DrafterUnavailable as exc:
                draft_source = "fallback_template"
                review_reasons.append(f"drafting model unavailable ({exc})")
                draft_body = _fallback_draft(profile, _resolve_primary_name(to_res), parsed["intent_bullets"])
            except Exception as exc:
                draft_source = "fallback_template"
                review_reasons.append(f"draft generation error ({exc})")
                draft_body = _fallback_draft(profile, _resolve_primary_name(to_res), parsed["intent_bullets"])

        subject = parsed.get("subject_hint") or ""
        if parsed["action"] == "reply" and subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        will_send = request.auto_send and not review_reasons and bool(draft_body)
        status = "SENT" if will_send else "PENDING_REVIEW"
        if will_send:
            try:
                receipt: SendReceipt = _connector_for_account(acc_settings).send_email(
                    OutboundEmailRequest(
                        to=to_emails, cc=cc_emails, bcc=bcc_emails, subject=subject, body=draft_body or ""
                    )
                )
                if receipt.status == "sent":
                    for email in to_emails + cc_emails:
                        store.increment_recipient_sent_count(email)
                else:
                    status = "PENDING_REVIEW"
                    review_reasons.append(f"send failed: {receipt.error}")
            except Exception as exc:
                status = "PENDING_REVIEW"
                review_reasons.append(f"send error: {exc}")

        # Generate a draft_id for pending drafts so they can be approved later
        draft_id = str(uuid.uuid4()) if not will_send else None

        card = sessions.upsert_draft_card(
            session_id=session_id,
            to=to_emails,
            cc=cc_emails,
            bcc=bcc_emails,
            subject=subject,
            body=draft_body or "",
            status=status,
            draft_id=draft_id,
        )

        # If pending review, save to pending_drafts for approve-and-learn
        if not will_send and draft_id and draft_body:
            import json
            recipient_profiles_data = {}
            for email in to_emails + cc_emails:
                rp = store.get_recipient_profile(email)
                if rp:
                    recipient_profiles_data[email.lower()] = rp.model_dump(mode="json")
            with sqlite3.connect(acc_settings.sqlite_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_drafts (
                        draft_id TEXT PRIMARY KEY,
                        profile_id TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        draft TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        recipient_profiles_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO pending_drafts (draft_id, profile_id, request_json, draft, created_at, recipient_profiles_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_id,
                        profile.profile_id if profile else "",
                        json.dumps({
                            "to": to_emails,
                            "cc": cc_emails,
                            "bcc": bcc_emails,
                            "subject": subject,
                            "intent_bullets": parsed["intent_bullets"],
                            "provider": "demo",
                            "thread_id": None,
                            "in_reply_to": None,
                        }),
                        draft_body,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(recipient_profiles_data),
                    ),
                )

        if status == "SENT":
            assistant_message = f"Sent your email to {', '.join(to_emails)}."
        else:
            assistant_message = (
                f"Drafted an email to {', '.join(to_emails)} and held it for review: "
                + "; ".join(review_reasons)
            )
        sessions.append_message(
            session_id,
            "assistant",
            assistant_message,
            metadata={"status": status, "card_id": card["card_id"], "draft_source": draft_source},
        )

        return ChatTurnResponse(
            session_id=session_id,
            status=status,
            assistant_message=assistant_message,
            parsed=parsed,
            resolutions=_schemas(resolution_lists),
            draft_card=card,
            review_reason="; ".join(review_reasons) if review_reasons else None,
        )

    # SPA static file serving (must be last to catch all non-API routes)
    frontend_dist = runtime_settings.local_user_data_dir.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="spa")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
