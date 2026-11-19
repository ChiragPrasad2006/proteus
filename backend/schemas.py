"""Pydantic v2 schemas for local email extraction and style profiling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Formality = Literal["casual", "semi-formal", "strict-executive", "blunt-technical"]
Directness = Literal["low", "balanced", "high"]
VocabularyLevel = Literal["simple", "standard-professional", "advanced-technical"]
SentenceStructure = Literal["short & punchy", "detailed & analytical", "warm & conversational"]
AudienceMode = Literal["1on1_private", "group_cc", "broadcast_bcc"]
RelationshipTier = Literal["executive_or_client", "peer", "direct_report", "external", "unknown"]


class StrictModel(BaseModel):
    """Base model that rejects unintended client fields."""

    model_config = ConfigDict(extra="forbid")


class EmailMessage(StrictModel):
    """Normalized sent-email record independent of its source provider."""

    message_id: str
    recipient_email: str = ""
    recipient_domain: str = ""
    subject: str = ""
    raw_body: str
    timestamp: datetime | None = None
    thread_id: str = ""

    @field_validator("recipient_domain", mode="before")
    @classmethod
    def derive_domain(cls, value: str, info: Any) -> str:
        """Derive a recipient domain when a connector supplied only an address."""
        if value:
            return value.lower()
        recipient = str(info.data.get("recipient_email", ""))
        return recipient.rsplit("@", 1)[-1].lower() if "@" in recipient else ""


class RawSentEmail(EmailMessage):
    """Semantic alias for raw, uncleaned Sent-mail records."""


class CleanedSentEmail(EmailMessage):
    """Sent email with reply history removed and signature preserved separately."""

    clean_body: str
    signature: str = ""
    word_count: int = Field(ge=0)


class GreetingFrequency(StrictModel):
    pattern: str
    pct: float = Field(ge=0, le=100)


class StylometryMetrics(StrictModel):
    top_greetings: list[GreetingFrequency] = Field(default_factory=list)
    exact_signoff: str = ""
    avg_sentence_length_words: float = 0.0
    avg_email_length_words: float = 0.0
    avg_paragraph_count: float = 0.0
    exclamation_rate: float = 0.0
    emoji_rate: float = 0.0
    uses_bullet_lists_pct: float = 0.0


class GlobalStyleCard(StrictModel):
    """LLM-derived global traits using the fields required by Tier 1."""

    formality: Formality
    tone: str
    directness: Directness
    vocabulary_level: VocabularyLevel
    sentence_structure: SentenceStructure
    formatting_preferences: list[str] = Field(max_length=6)
    characteristic_phrases: list[str] = Field(max_length=5)
    source: Literal["ollama", "transformers", "llama_cpp", "heuristic"]
    model: str = ""
    sampled_email_count: int = Field(ge=0)


class CorpusStatistics(StrictModel):
    total_sent_emails: int = Field(ge=0)
    clean_emails_retained: int = Field(ge=0)
    top_recipients: list[dict[str, Any]] = Field(default_factory=list)


class RecipientProfile(StrictModel):
    """Per-recipient learned style profile stored in SQLite."""

    recipient_email: str
    recipient_domain: str
    relationship_tier: RelationshipTier = "unknown"
    preferred_greeting: str = ""
    sent_count: int = 0
    learned_rules_json: list[str] = Field(default_factory=list, max_length=2)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserStyleProfile(StrictModel):
    profile_id: str
    created_at: datetime
    deterministic_stylometry: StylometryMetrics
    global_style_card: GlobalStyleCard
    corpus_statistics: CorpusStatistics
    # Global learned rules (capped at 10 active atomic rules)
    global_learned_rules: list[str] = Field(default_factory=list, max_length=10)


class OnboardingRequest(StrictModel):
    provider: Literal["gmail", "outlook", "imap", "mbox"]
    limit: int = Field(default=300, ge=1, le=500)
    credentials: dict[str, Any] = Field(default_factory=dict)
    file_path: str | None = None


class OnboardingStatus(StrictModel):
    provider: str
    extracted_emails: int = Field(ge=0)
    clean_emails_retained: int = Field(ge=0)
    dropped_emails: int = Field(ge=0)
    storage_path: str


class BuildProfileRequest(StrictModel):
    """Reserved for explicit future options; model selection remains local-only."""

    force_refresh: bool = False


class RetrievedExample(StrictModel):
    """A retrieved few-shot example for draft generation."""

    message_id: str
    recipient_email: str
    recipient_domain: str
    subject: str
    clean_body: str
    greeting: str
    signoff: str
    word_count: int
    timestamp: str
    # New fields for audience-aware retrieval
    audience_mode: AudienceMode = "1on1_private"
    cc_count: int = 0
    bcc_count: int = 0
    timestamp_epoch: float = 0.0


class RetrieveRequest(StrictModel):
    """Request for few-shot example retrieval."""

    query_text: str = ""
    recipient_email: str | None = None
    recipient_domain: str | None = None
    k: int = Field(default=2, ge=1, le=10)
    min_word_count: int = Field(default=25, ge=0)
    audience_mode: AudienceMode = "1on1_private"


class RetrieveResponse(StrictModel):
    """Response with retrieved few-shot examples."""

    examples: list[RetrievedExample] = Field(default_factory=list)
    total_indexed: int = 0


class DraftRequest(StrictModel):
    """Request for personalized draft generation."""

    intent_bullets: str
    recipient_email: str | None = None
    incoming_context: str | None = None
    model_name: str | None = None
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class DraftResponse(StrictModel):
    """Response with generated email draft."""

    draft: str
    model_used: str
    retrieved_examples: list[RetrievedExample] = Field(default_factory=list)
    profile_id: str


class ReindexRequest(StrictModel):
    """Request to reindex the vector store."""

    force: bool = False


class ReindexResponse(StrictModel):
    """Response after reindexing."""

    indexed_count: int
    table_name: str


# Tier 1 Upgrade: Outbound email schemas
class OutboundEmailRequest(StrictModel):
    """Request to send an email via a provider."""

    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    in_reply_to: str | None = None


class SendReceipt(StrictModel):
    """Receipt returned after sending an email."""

    message_id: str
    thread_id: str | None = None
    status: Literal["sent", "failed"]
    error: str | None = None


# Tier 4: Automation & Self-Improving Dispatch
class DispatchRequest(StrictModel):
    """Request for autonomous email dispatch with first-recipient gate."""

    provider: Literal["gmail", "outlook", "imap", "demo"]
    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    intent_bullets: str
    incoming_email_context: str | None = None
    thread_id: str | None = None
    in_reply_to: str | None = None
    attachments: list[str] = Field(default_factory=list)
    auto_send: bool = False


class DispatchResponse(StrictModel):
    """Response from autonomous dispatch."""

    draft_id: str
    status: Literal["SENT", "PENDING_REVIEW"]
    review_reason: str | None = None
    draft: str | None = None
    receipt: SendReceipt | None = None


class ApproveAndLearnRequest(StrictModel):
    """Request to approve a pending draft and extract style rules from user edits."""

    draft_id: str
    final_subject: str
    final_body: str
    relationship_tier_override: RelationshipTier | None = None


class ApproveAndLearnResponse(StrictModel):
    """Response after approving and learning from user edits."""

    status: Literal["SENT", "FAILED"]
    receipt: SendReceipt | None = None
    extracted_rules: list[str] = Field(default_factory=list)
    rule_scope: Literal["recipient", "global"] = "global"


# Imports needed for the new types
from datetime import timezone


# --- Multi-account, OAuth2 connect, contacts, and chat session schemas ---
class GoogleAuthStartResponse(StrictModel):
    """Authorization URL + state for the Google OAuth2 desktop flow."""

    auth_url: str
    state: str
    redirect_uri: str


class GoogleOAuthCredentialsUpload(StrictModel):
    """Upload Google OAuth client_secret.json content."""

    client_secret_json: str  # JSON content of client_secret.json


class GoogleOAuthCredentialsStatus(StrictModel):
    """Status of Google OAuth credentials."""

    configured: bool
    message: str


class IdentityLoginRequest(StrictModel):
    """Local identity fallback when a Google OAuth client is not configured."""

    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)


class ConnectAppPasswordRequest(StrictModel):
    """One Gmail App Password used only for local IMAP/SMTP verification."""

    app_password: str = Field(min_length=16, max_length=32)
    limit: int = Field(default=300, ge=1, le=500)


class MailboxConnectResponse(StrictModel):
    """Mailbox setup completion summary; never includes credentials."""

    account: dict[str, Any]
    extracted_emails: int
    clean_emails_retained: int
    message: str


class AccountSwitchRequest(StrictModel):
    """Switch the active account."""

    account_id: str


class AccountListResponse(StrictModel):
    """All connected accounts plus the currently active one."""

    accounts: list[dict[str, Any]] = Field(default_factory=list)
    active_account_id: str | None = None


class ContactResolution(StrictModel):
    """Resolution of one free-text recipient name against the contacts registry."""

    query: str
    status: Literal["MATCHED", "NEEDS_CLARIFICATION"]
    matched_email: str | None = None
    matched_name: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


class DraftTweakRequest(StrictModel):
    """Revision of a staged draft without reparsing its recipient intent."""

    draft_id: str
    tweak_instruction: str = Field(min_length=1)
    current_to: list[str] | None = None
    current_cc: list[str] | None = None
    current_bcc: list[str] | None = None
    current_subject: str | None = None
    current_body: str | None = None


class DraftTweakResponse(StrictModel):
    draft_id: str
    subject: str
    body: str


class ChatTurnRequest(StrictModel):
    """One natural-language turn in a chat session."""

    account_id: str | None = None
    session_id: str | None = None
    user_message: str = Field(min_length=1)
    auto_send: bool = False


class ChatTurnResponse(StrictModel):
    """Result of parsing, resolving, drafting, and gating a chat turn."""

    session_id: str
    status: Literal["DRAFTED", "PENDING_REVIEW", "SENT", "NEEDS_CLARIFICATION", "ERROR"]
    assistant_message: str
    parsed: dict[str, Any] = Field(default_factory=dict)
    resolutions: dict[str, list[ContactResolution]] = Field(default_factory=dict)
    draft_card: dict[str, Any] | None = None
    review_reason: str | None = None
    session_title: str | None = None


class ChatSessionSummary(StrictModel):
    """Lightweight chat session row."""

    session_id: str
    account_id: str
    title: str = ""
    created_at: str
    updated_at: str
    message_count: int = 0
    pending_clarification: dict[str, Any] = {}
    is_custom_title: bool = False


class ChatSessionListResponse(StrictModel):
    sessions: list[ChatSessionSummary] = Field(default_factory=list)


class ChatSessionCreateRequest(StrictModel):
    title: str = ""


class ChatSessionRenameRequest(StrictModel):
    title: str = Field(min_length=1, max_length=100)


class ChatSessionDetailResponse(StrictModel):
    session: dict[str, Any]
    messages: list[dict[str, Any]] = Field(default_factory=list)
    draft_cards: list[dict[str, Any]] = Field(default_factory=list)