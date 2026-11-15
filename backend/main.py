"""FastAPI entrypoint for the local-first email personalization backend."""

from __future__ import annotations

import json
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.automation import Dispatcher, StyleLearner
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
    ApproveAndLearnRequest,
    ApproveAndLearnResponse,
    BuildProfileRequest,
    DispatchRequest,
    DispatchResponse,
    DraftRequest,
    DraftResponse,
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
from backend.storage import ProfileStore


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
        client_path = credentials.get("client_secrets_file")
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance suitable for production or isolated tests."""
    runtime_settings = settings or Settings()
    store = ProfileStore(runtime_settings)
    profiler = QwenStyleProfiler(runtime_settings)
    embedder = LocalEmbedder()
    vector_store = LanceDBVectorStore(runtime_settings)
    drafter = QwenDrafter(runtime_settings)
    dispatcher = Dispatcher(runtime_settings)
    style_learner = StyleLearner(runtime_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime_settings.ensure_local_directories()
        # Load embedder model on startup
        try:
            embedder.load()
        except Exception:
            pass
        yield

    app = FastAPI(title="Personalized AI Email Writer Local Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = runtime_settings
    app.state.store = store
    app.state.profiler = profiler
    app.state.embedder = embedder
    app.state.vector_store = vector_store
    app.state.drafter = drafter
    app.state.dispatcher = dispatcher
    app.state.style_learner = style_learner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Report local inference, GPU, and embedding-cache readiness without downloading models."""
        return {
            "status": "ok",
            "qwen": profiler.availability(),
            "gpu": _gpu_status(),
            "sentence_transformer": _sentence_transformer_cache_status(runtime_settings),
            "local_user_data_dir": str(runtime_settings.local_user_data_dir),
            "retrieval": {
                "embedder_loaded": embedder.is_loaded,
                "embedder_cached": embedder.is_model_cached(),
                "vector_store_count": vector_store.count(),
            },
            "generation": drafter.availability(),
            "automation": {
                "dispatcher_ready": True,
                "style_learner_ready": True,
            },
        }

    @app.post("/api/onboarding/connect-and-extract", response_model=OnboardingStatus)
    def connect_and_extract(request: OnboardingRequest) -> OnboardingStatus:
        """Fetch Sent mail from the selected provider and retain cleaned local records."""
        try:
            connector = _connector_from_request(request, runtime_settings)
            raw_records = connector.fetch_sent_emails(request.limit)
            status = _clean_and_persist(raw_records, store, runtime_settings)
            return status.model_copy(update={"provider": request.provider})
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/build-profile", response_model=UserStyleProfile)
    def build_profile(_: BuildProfileRequest | None = None) -> UserStyleProfile:
        """Build and persist a merged deterministic + local-Qwen profile from cleaned Sent mail."""
        cleaned = store.load_cleaned_emails()
        if not cleaned:
            raise HTTPException(status_code=404, detail="No cleaned Sent corpus found. Extract or demo-seed first.")
        metrics = compute_stylometry(cleaned)
        try:
            global_style_card = profiler.profile(cleaned, metrics)
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
        # Auto-index into LanceDB
        try:
            indexed = vector_store.index_emails(cleaned, embedder)
        except Exception:
            indexed = 0
        return profile

    @app.get("/api/profile", response_model=UserStyleProfile)
    def get_profile() -> UserStyleProfile:
        """Return the one active locally stored style profile."""
        profile = store.load_profile()
        if profile is None:
            raise HTTPException(status_code=404, detail="No profile has been built yet.")
        return profile

    @app.post("/api/onboarding/demo-seed", response_model=OnboardingStatus)
    def demo_seed() -> OnboardingStatus:
        """Seed the full pipeline from a local JSON fixture without OAuth credentials."""
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "demo_sent_emails.json"
        records = [RawSentEmail.model_validate(item) for item in json.loads(fixture_path.read_text(encoding="utf-8"))]
        status = _clean_and_persist(records, store, runtime_settings)
        return status.model_copy(update={"provider": "mbox"})

    # Tier 2: Retrieval endpoints
    @app.post("/api/retrieval/reindex", response_model=ReindexResponse)
    def reindex(_: ReindexRequest | None = None) -> ReindexResponse:
        """Re-index all cleaned emails into LanceDB vector store."""
        cleaned = store.load_cleaned_emails()
        if not cleaned:
            raise HTTPException(status_code=404, detail="No cleaned corpus found. Extract or demo-seed first.")
        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc
        indexed = vector_store.index_emails(cleaned, embedder, force_recreate=True)
        return ReindexResponse(indexed_count=indexed, table_name=runtime_settings.lancedb_table_name)

    @app.post("/api/retrieval/search", response_model=RetrieveResponse)
    def search(request: RetrieveRequest) -> RetrieveResponse:
        """Search for few-shot examples using semantic similarity with time-decayed reranking."""
        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc
        examples = vector_store.retrieve_few_shot_examples(
            embedder=embedder,
            recipient_email=request.recipient_email,
            recipient_domain=request.recipient_domain,
            query_text=request.query_text,
            k=request.k,
            min_word_count=request.min_word_count,
            target_audience_mode=request.audience_mode or "1on1_private",
        )
        # LanceDB returns extra fields (vector, _distance) - strip them for schema compliance
        clean_examples = [
            {k: v for k, v in ex.items() if k in RetrievedExample.model_fields}
            for ex in examples
        ]
        return RetrieveResponse(
            examples=[RetrievedExample(**ex) for ex in clean_examples],
            total_indexed=vector_store.count(),
        )

    # Tier 3: Generation endpoint with audience topology
    @app.post("/api/draft/generate", response_model=DraftResponse)
    def generate_draft(request: DraftRequest) -> DraftResponse:
        """Generate a personalized email draft using the fine-tuned Qwen model with audience topology."""
        profile = store.load_profile()
        if profile is None:
            raise HTTPException(status_code=404, detail="No profile has been built yet. Run /api/onboarding/build-profile first.")

        try:
            embedder.load()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Embedder unavailable: {exc}") from exc

        try:
            # Load recipient profiles for To/Cc
            to_recipients = [request.recipient_email] if request.recipient_email else []
            cc_recipients = request.cc or []
            bcc_recipients = request.bcc or []

            recipient_profiles = {}
            for email in to_recipients + cc_recipients:
                if email:
                    rp = store.get_recipient_profile(email)
                    if rp:
                        recipient_profiles[email.lower()] = rp

            draft = drafter.generate_draft(
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
        except DrafterUnavailable as exc:
            raise HTTPException(status_code=503, detail=f"Local Qwen drafter unavailable: {exc}") from exc

        # Get the retrieved examples for the response
        recipient_domain = None
        if request.recipient_email:
            recipient_domain = request.recipient_email.split("@")[-1] if "@" in request.recipient_email else None
        query_text = " ".join([request.incoming_context or "", request.intent_bullets]).strip()

        # Determine target audience mode
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

        # LanceDB returns extra fields (vector, _distance) - strip them for schema compliance
        clean_examples = [
            {k: v for k, v in ex.items() if k in RetrievedExample.model_fields}
            for ex in examples
        ]

        return DraftResponse(
            draft=draft,
            model_used=runtime_settings.model_name,
            retrieved_examples=[RetrievedExample(**ex) for ex in clean_examples],
            profile_id=profile.profile_id,
        )

    # Tier 4: Autonomous dispatch endpoints
    @app.post("/api/email/dispatch", response_model=DispatchResponse)
    def dispatch_email(request: DispatchRequest) -> DispatchResponse:
        """Autonomous email dispatch with first-recipient gate."""
        return dispatcher.dispatch(request)

    @app.post("/api/email/approve-and-learn", response_model=ApproveAndLearnResponse)
    def approve_and_learn(request: ApproveAndLearnRequest) -> ApproveAndLearnResponse:
        """Approve a pending draft and extract style rules from user edits."""
        return style_learner.approve_and_learn(request)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)