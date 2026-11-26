/**
 * Shared domain types for the Proteus front end. These mirror the FastAPI
 * schemas exposed by `backend/schemas.py` where a wire contract exists.
 */

export type Provider = 'gmail' | 'outlook' | 'imap' | 'mbox' | 'demo'

export type RelationshipTier =
  | 'executive_or_client'
  | 'peer'
  | 'direct_report'
  | 'external'
  | 'unknown'

export type AudienceMode = '1on1_private' | 'group_cc' | 'broadcast_bcc'

export interface Account {
  id: string
  name: string
  email: string
  provider: Provider
  mailboxConnected: boolean
  /** Two-letter monogram rendered inside the avatar disc. */
  initials: string
  /** Tailwind gradient token used for the avatar background. */
  hue: string
}

export interface Session {
  id: string
  title: string
  preview: string
  /** ISO-8601 timestamp of the last activity. */
  updatedAt: string
  accountId: string
  /** True if the title was explicitly set by the user (prevents auto-overwrites). */
  isCustomTitle?: boolean
  /** Server-side pin flag (per account). */
  pinned?: boolean
}

export interface RecipientContact {
  id: string
  name: string
  email: string
  tier: RelationshipTier
  /** Human label for the tier, e.g. "Executive / Client". */
  relationship: string
  /** 0–1 confidence that the tier inference is correct. */
  confidence: number
  /** Number of prior sent emails matched in the local corpus. */
  sentCount: number
  isNew?: boolean
}

export interface RetrievedExample {
  message_id: string
  recipient_email: string
  subject: string
  clean_body: string
  greeting: string
  signoff: string
  word_count: number
  timestamp: string
}

export type DraftStatus = 'DRAFT' | 'PENDING_REVIEW' | 'SENT' | 'FAILED'

/**
 * Unified client-side draft lifecycle. Both the chat Activity Action Cards
 * and the Paper Letter Draft Panel read/write this single status so they can
 * never disagree (e.g. "held for review" in chat while the panel says SENT).
 */
export type UnifiedDraftStatus =
  | 'draft'
  | 'pending_review'
  | 'sending_countdown'
  | 'sending'
  | 'sent'
  | 'failed'

export interface DraftVersion {
  /** v1, v2, v3 … */
  label: string
  subject: string
  body: string
  createdAt: string
  source: 'generated' | 'refined'
}

export interface LearnedRule {
  id: string
  text: string
  scope: 'global' | 'recipient'
}

/** A draft owned by the shared `useDraftState` store, keyed by draft_id. */
export interface WorkspaceDraft {
  id: string
  sessionId: string
  accountId: string
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  status: UnifiedDraftStatus
  /** Audience resolved by the backend's deterministic policy layer. */
  audienceType: AudienceMode
  resolutionMeta?: Record<string, unknown>
  /** Raw backend reason — internal only, never rendered verbatim. */
  reviewReason?: string
  modelUsed: string
  createdAt: string
  updatedAt: string
  sentAt?: string
  sendError?: string
  /** Epoch ms when the 10s undo-send countdown ends. */
  countdownEndsAt?: number
  /** Status to restore if the countdown is undone. */
  preCountdownStatus?: UnifiedDraftStatus
  versions: DraftVersion[]
  learnedRules: LearnedRule[]
  /** Last machine-generated text, for the "What I learned" edit diff. */
  generatedSubject: string
  generatedBody: string
}

export type WarningSeverity = 'info' | 'warning' | 'danger'

export interface DraftWarning {
  id: string
  severity: WarningSeverity
  title: string
  detail: string
}

export interface EmailDraft {
  id: string
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  warnings: DraftWarning[]
  retrievedExamples: RetrievedExample[]
  modelUsed: string
  status: DraftStatus
  reviewReason?: string
  /** Audience resolved by the backend's deterministic policy layer. */
  audienceType?: AudienceMode
  resolutionMeta?: Record<string, unknown>
}

export interface PersonalizationConfidence {
  level: 'high' | 'medium' | 'low'
  reason?: string
  fallback_applied?: boolean
  signals?: {
    usable_example_count?: number
    audience_matched_count?: number
    audience_mismatched_count?: number
    top_similarity?: number | null
    avg_similarity?: number | null
    newest_age_days?: number | null
    median_age_days?: number | null
  }
}

export interface ResolutionMeta extends Record<string, unknown> {
  confidence?: PersonalizationConfidence
  cold_start_fallback?: boolean
}

export type MessageRole = 'user' | 'assistant'


/**
 * Assistant-only: emitted when the agent cannot confidently resolve a name
 * from the local corpus and needs the user to disambiguate before drafting.
 */
export interface ClarificationRequest {
  /** The question shown above the candidate list, e.g. "Which Chiranth?". */
  prompt: string
  /** Ranked candidate contacts the agent matched the name against. */
  candidates: RecipientContact[]
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  /** ISO-8601 creation time. */
  createdAt: string
  status?: 'pending' | 'streaming' | 'done' | 'NEEDS_CLARIFICATION'
  /** Assistant-only: the short plan the agent narrates before drafting. */
  reasoning?: string[]
  /** Assistant-only: contacts resolved from the local corpus. */
  contacts?: RecipientContact[]
  /** Assistant-only: id of the draft in the shared useDraftState store. */
  draftId?: string | null
  /** Assistant-only: a name the agent needs the user to disambiguate. */
  clarification?: ClarificationRequest | null
}

/* ── Backend wire contracts (subset of backend/schemas.py) ─────────────── */

export interface ContactResolution {
  query: string
  status: 'MATCHED' | 'NEEDS_CLARIFICATION'
  matched_email: string | null
  matched_name: string | null
  candidates: { email: string; full_name: string; first_name?: string }[]
  reason: string | null
}

export interface OnboardingStatus {
  provider: string
  extracted_emails: number
  clean_emails_retained: number
  dropped_emails: number
  storage_path: string
}

export interface StylometryMetrics {
  top_greetings: { pattern: string; pct: number }[]
  exact_signoff: string
  avg_sentence_length_words: number
  avg_email_length_words: number
  avg_paragraph_count: number
  exclamation_rate: number
  emoji_rate: number
  uses_bullet_lists_pct: number
}

export interface GlobalStyleCard {
  formality: 'casual' | 'semi-formal' | 'strict-executive' | 'blunt-technical'
  tone: string
  directness: 'low' | 'balanced' | 'high'
  vocabulary_level: 'simple' | 'standard-professional' | 'advanced-technical'
  sentence_structure: 'short & punchy' | 'detailed & analytical' | 'warm & conversational'
  formatting_preferences: string[]
  characteristic_phrases: string[]
  source: 'ollama' | 'transformers' | 'llama_cpp' | 'heuristic'
  model: string
  sampled_email_count: number
}

export interface UserStyleProfile {
  profile_id: string
  created_at: string
  deterministic_stylometry: StylometryMetrics
  global_style_card: GlobalStyleCard
  corpus_statistics: {
    total_sent_emails: number
    clean_emails_retained: number
    top_recipients: Record<string, unknown>[]
  }
  global_learned_rules: string[]
}

export interface RuntimeStatus {
  label: string
  state: 'online' | 'offline' | 'loading'
  detail?: string
}

export interface HealthReport {
  status: string
  qwen: { available: boolean; model?: string; detail?: string }
  gpu: { available: boolean; name?: string; vram_total_mib?: number; vram_free_mib?: number }
  sentence_transformer: { model: string; cache_ready: boolean; cache_dir: string }
  local_user_data_dir: string
  retrieval: { embedder_loaded: boolean; embedder_cached: boolean; vector_store_count: number }
  generation: { available: boolean; model?: string; detail?: string }
  automation: { dispatcher_ready: boolean; style_learner_ready: boolean }
}

export type WorkspaceMode = 'compose' | 'inbox'
export type ReplyMode = 'reply' | 'reply_all'

export interface InboxThreadSummary {
  thread_id: string
  subject: string
  snippet: string
  last_message_at: string
  message_count: number
  participants: string[]
  unread: boolean
  latest_sender_name: string
  latest_sender_email: string
}

export interface InboxThreadMessage {
  message_id: string
  from_name: string
  from_email: string
  to: string[]
  cc: string[]
  date: string
  subject: string
  body_text: string
  in_reply_to: string
  references: string[]
}

export interface InboxThreadDetail {
  thread_id: string
  subject: string
  participants: string[]
  messages: InboxThreadMessage[]
}
