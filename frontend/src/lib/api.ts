/** Thin typed wrapper around the local FastAPI backend (proxied at /api). */

import type {
  Account,
  ChatMessage,
  ContactResolution,
  DraftStatus,
  DraftWarning,
  EmailDraft,
  HealthReport,
  OnboardingStatus,
  Provider,
  RecipientContact,
  RelationshipTier,
  Session,
  UserStyleProfile,
} from '@/types'

/* ── Chat / session / account wire contracts ───────────────────────────── */

export interface ChatTurnRequest {
  session_id: string
  account_id?: string
  user_message: string
  auto_send?: boolean
}

export interface ChatTurnResponse {
  session_id: string
  status: 'DRAFTED' | 'PENDING_REVIEW' | 'SENT' | 'NEEDS_CLARIFICATION' | 'ERROR'
  assistant_message: string
  parsed: Record<string, unknown>
  resolutions: Record<string, ContactResolution[]>
  draft_card: EmailDraft | null
  review_reason: string
  contacts: RecipientContact[]
  clarification: { prompt: string; candidates: RecipientContact[] } | null
  /** Updated session title if auto-summarized or renamed. */
  session_title?: string
}

export interface SessionListResponse {
  sessions: Session[]
}

export interface SessionDetailResponse {
  session: Session
  messages: ChatMessage[]
  /** Draft cards hydrated into the shared useDraftState store. */
  drafts: EmailDraft[]
}

export interface GoogleOAuthCredentialsStatus {
  configured: boolean
  message: string
}

export interface AccountListResponse {
  accounts: Account[]
  active_account_id: string | null
}

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
const asString = (value: unknown): string => typeof value === 'string' ? value : ''
const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(asString) : []
const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

function normalizeRecipient(value: unknown): RecipientContact {
  const raw = asRecord(value)
  // Legacy corpus rows can carry literal quotes around the address — strip them.
  const email = asString(raw.email ?? raw.matched_email).replace(/^["']+|["']+$/g, '')
  const name = asString(raw.name ?? raw.full_name ?? raw.matched_name).replace(/^["']+|["']+$/g, '') || email
  const tiers: RelationshipTier[] = ['executive_or_client', 'peer', 'direct_report', 'external', 'unknown']
  const rawTier = raw.tier ?? raw.relationship_tier
  const tier = tiers.includes(rawTier as RelationshipTier) ? rawTier as RelationshipTier : 'unknown'
  return {
    id: asString(raw.id) || email || name,
    name,
    email,
    tier,
    relationship: asString(raw.relationship) || 'Unknown',
    confidence: asNumber(raw.confidence),
    sentCount: asNumber(raw.sentCount ?? raw.sent_count ?? raw.interaction_count),
    isNew: Boolean(raw.isNew ?? raw.is_new),
  }
}

function normalizeResolution(value: unknown): ContactResolution {
  const raw = asRecord(value)
  const candidates = Array.isArray(raw.candidates) ? raw.candidates.map((candidate) => {
    const item = asRecord(candidate)
    return {
      email: asString(item.email),
      full_name: asString(item.full_name ?? item.name) || asString(item.email),
      first_name: asString(item.first_name),
    }
  }) : []
  return {
    query: asString(raw.query),
    status: raw.status === 'MATCHED' ? 'MATCHED' : 'NEEDS_CLARIFICATION',
    matched_email: typeof raw.matched_email === 'string' ? raw.matched_email : null,
    matched_name: typeof raw.matched_name === 'string' ? raw.matched_name : null,
    candidates,
    reason: typeof raw.reason === 'string' ? raw.reason : null,
  }
}

function normalizeDraftWarning(value: unknown, index: number): DraftWarning {
  const raw = asRecord(value)
  const severity = raw.severity === 'info' || raw.severity === 'danger' ? raw.severity : 'warning'
  return {
    id: asString(raw.id) || `review-${index}`,
    severity,
    title: asString(raw.title) || 'Review required',
    detail: asString(raw.detail),
  }
}

function normalizeEmailDraft(value: unknown, reviewReason: string): EmailDraft {
  const raw = asRecord(value)
  const stripQuotes = (list: unknown) => asStringArray(list).map((email) => email.replace(/^["']+|["']+$/g, ''))
  const rawWarnings = Array.isArray(raw.warnings) ? raw.warnings : []
  const warningInputs = rawWarnings.length > 0
    ? rawWarnings
    : reviewReason ? reviewReason.split(';').map((detail) => ({ detail: detail.trim() })) : []
  const statuses: DraftStatus[] = ['DRAFT', 'PENDING_REVIEW', 'SENT', 'FAILED']
  const status = statuses.includes(raw.status as DraftStatus) ? raw.status as DraftStatus : 'DRAFT'
  const rawExamples = raw.retrieved_examples ?? raw.retrievedExamples
  const examples = Array.isArray(rawExamples) ? rawExamples : []
  return {
    id: asString(raw.draft_id ?? raw.id ?? raw.card_id),
    to: stripQuotes(raw.to),
    cc: stripQuotes(raw.cc ?? raw.cc_emails),
    bcc: stripQuotes(raw.bcc ?? raw.bcc_emails),
    subject: asString(raw.subject),
    body: asString(raw.body ?? raw.draft),
    warnings: warningInputs.map(normalizeDraftWarning),
    retrievedExamples: (examples as unknown[]).map((item) => {
      const example = asRecord(item)
      return {
        message_id: asString(example.message_id),
        recipient_email: asString(example.recipient_email),
        subject: asString(example.subject),
        clean_body: asString(example.clean_body),
        greeting: asString(example.greeting),
        signoff: asString(example.signoff),
        word_count: asNumber(example.word_count),
        timestamp: asString(example.timestamp),
      }
    }),
    modelUsed: asString(raw.model_used ?? raw.modelUsed),
    status,
    reviewReason: asString(raw.review_reason ?? raw.reviewReason) || reviewReason || undefined,
  }
}

function normalizeSessionSummary(value: unknown): Session {
  const raw = asRecord(value)
  return {
    id: asString(raw.session_id ?? raw.id),
    title: asString(raw.title) || 'New session',
    preview: asString(raw.preview),
    updatedAt: asString(raw.updated_at ?? raw.updatedAt),
    accountId: asString(raw.account_id ?? raw.accountId),
    isCustomTitle: Boolean(raw.is_custom_title ?? raw.isCustomTitle),
  }
}

export function normalizeChatSessionDetail(value: unknown): SessionDetailResponse {
  const raw = asRecord(value)
  const session = normalizeSessionSummary(raw.session)
  const draftCards = Array.isArray(raw.draft_cards) ? raw.draft_cards : []
  const drafts = draftCards.map((card) => normalizeEmailDraft(card, asString(asRecord(card).review_reason)))
  const rawMessages = Array.isArray(raw.messages) ? raw.messages : []
  const messages = rawMessages.map((value): ChatMessage => {
    const message = asRecord(value)
    const metadata = asRecord(message.metadata)
    const messageId = asString(message.message_id ?? message.id)
    const cardId = asString(metadata.card_id ?? metadata.draft_id)
    const card = draftCards.map(asRecord).find((candidate) =>
      asString(candidate.card_id ?? candidate.draft_id ?? candidate.id) === cardId,
    )
    const clarification = metadata.status === 'NEEDS_CLARIFICATION'
      ? { prompt: asString(message.content), candidates: [] }
      : null
    return {
      id: messageId,
      role: message.role === 'user' ? 'user' : 'assistant',
      content: asString(message.content),
      createdAt: asString(message.created_at ?? message.createdAt),
      status: metadata.status === 'NEEDS_CLARIFICATION' ? 'NEEDS_CLARIFICATION' : 'done',
      reasoning: [],
      contacts: [],
      draftId: card ? asString(card.draft_id ?? card.card_id ?? card.id) || null : null,
      clarification,
    }
  })
  return { session, messages, drafts }
}

export function normalizeChatTurnResponse(value: unknown): ChatTurnResponse {
  const raw = asRecord(value)
  const statuses: ChatTurnResponse['status'][] = ['DRAFTED', 'PENDING_REVIEW', 'SENT', 'NEEDS_CLARIFICATION', 'ERROR']
  const status = statuses.includes(raw.status as ChatTurnResponse['status'])
    ? raw.status as ChatTurnResponse['status'] : 'ERROR'
  const reviewReason = asString(raw.review_reason ?? raw.reviewReason)
  const resolutions = Object.fromEntries(Object.entries(asRecord(raw.resolutions)).map(([key, entries]) => [
    key,
    Array.isArray(entries) ? entries.map(normalizeResolution) : [],
  ])) as Record<string, ContactResolution[]>
  const allResolutions = Object.values(resolutions).flat()
  const contacts = allResolutions
    .filter((resolution) => resolution.status === 'MATCHED' && resolution.matched_email)
    .map((resolution) => normalizeRecipient({
      email: resolution.matched_email,
      name: resolution.matched_name,
      relationship: 'Unknown',
    }))
  const clarificationCandidates = allResolutions
    .filter((resolution) => resolution.status === 'NEEDS_CLARIFICATION')
    .flatMap((resolution) => resolution.candidates)
    .map(normalizeRecipient)
  const assistantMessage = asString(raw.assistant_message ?? raw.assistantMessage)
  const draftCard = raw.draft_card ?? raw.draftCard
  return {
    session_id: asString(raw.session_id ?? raw.sessionId),
    status,
    assistant_message: assistantMessage,
    parsed: asRecord(raw.parsed),
    resolutions,
    draft_card: draftCard ? normalizeEmailDraft(draftCard, reviewReason) : null,
    review_reason: reviewReason,
    contacts,
    clarification: status === 'NEEDS_CLARIFICATION'
      ? { prompt: assistantMessage, candidates: clarificationCandidates }
      : null,
    session_title: typeof raw.session_title === 'string' ? raw.session_title : undefined,
  }
}

interface BackendAccount {
  account_id: string
  email: string
  display_name: string
  avatar_url?: string
  provider: Provider
  mailbox_connected: boolean
}

function initials(name: string, email: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || email.slice(0, 2).toUpperCase()
}

function toAccount(account: BackendAccount): Account {
  const name = asString(account?.display_name)
  const email = asString(account?.email)
  const provider = ['gmail', 'outlook', 'imap', 'mbox', 'demo'].includes(account?.provider)
    ? account.provider : 'gmail'
  return {
    id: asString(account?.account_id),
    name,
    email,
    provider,
    mailboxConnected: Boolean(account?.mailbox_connected),
    initials: initials(name, email),
    hue: 'from-[#D4F268] to-[#7C9B2E]',
  }
}

const BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit & { accountId?: string }): Promise<T> {
  const { accountId, headers, ...restInit } = init ?? {}
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(accountId ? { 'X-Account-ID': accountId } : {}),
        ...(headers ?? {}),
      },
      ...restInit,
    })
  } catch (err) {
    throw new ApiError(
      `Cannot reach the local backend. Is it running on 127.0.0.1:8000? (${String(err)})`,
      0,
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  health: () => request<HealthReport>('/health'),

  profile: (accountId?: string) => request<UserStyleProfile>('/profile', { accountId }),

  connectAndExtract: (payload: {
    provider: Provider
    limit?: number
    credentials?: Record<string, unknown>
    file_path?: string | null
  }, accountId?: string) =>
    request<OnboardingStatus>('/onboarding/connect-and-extract', {
      method: 'POST',
      body: JSON.stringify({ limit: 300, credentials: {}, ...payload }),
      accountId,
    }),

  demoSeed: (accountId?: string) =>
    request<OnboardingStatus>('/onboarding/demo-seed', { method: 'POST', body: '{}', accountId }),

  buildProfile: (forceRefresh = false, accountId?: string) =>
    request<UserStyleProfile>('/onboarding/build-profile', {
      method: 'POST',
      body: JSON.stringify({ force_refresh: forceRefresh }),
      accountId,
    }),

  generateDraft: (payload: {
    intent_bullets: string
    recipient_email?: string | null
    incoming_context?: string | null
    cc?: string[]
    bcc?: string[]
  }, accountId?: string) =>
    request<{ draft: string; model_used: string; profile_id: string }>('/draft/generate', {
      method: 'POST',
      body: JSON.stringify({ cc: [], bcc: [], ...payload }),
      accountId,
    }),

  dispatch: (payload: {
    provider: 'gmail' | 'outlook' | 'imap' | 'demo'
    to: string[]
    cc?: string[]
    bcc?: string[]
    subject: string
    intent_bullets: string
    incoming_email_context?: string | null
    auto_send?: boolean
  }, accountId?: string) =>
    request<{ draft_id: string; status: DraftStatus; review_reason?: string; draft?: string }>(
      '/email/dispatch',
      { method: 'POST', body: JSON.stringify({ cc: [], bcc: [], auto_send: false, ...payload }), accountId },
    ),

  approveAndLearn: async (payload: { draft_id: string; final_subject: string; final_body: string }, accountId?: string) => {
    const raw = asRecord(await request<unknown>('/email/approve-and-learn', {
      method: 'POST',
      body: JSON.stringify(payload),
      accountId,
    }))
    const receipt = asRecord(raw.receipt)
    return {
      status: raw.status === 'SENT' ? 'SENT' as const : 'FAILED' as const,
      extracted_rules: asStringArray(raw.extracted_rules),
      rule_scope: asString(raw.rule_scope) || 'global',
      receipt_error: asString(receipt.error) || asString(raw.detail),
    }
  },

  tweakDraft: async (payload: {
    draft_id: string
    tweak_instruction: string
    current_to: string[]
    current_cc: string[]
    current_bcc: string[]
    current_subject: string
    current_body: string
  }, accountId?: string): Promise<{ draft_id: string; subject: string; body: string }> => {
    const raw = asRecord(await request<unknown>('/draft/tweak', {
      method: 'POST',
      body: JSON.stringify(payload),
      accountId,
    }))
    return {
      draft_id: asString(raw.draft_id),
      subject: asString(raw.subject),
      body: asString(raw.body),
    }
  },

  /* ── Conversational workspace ───────────────────────────────────────── */

  chatTurn: async (payload: { session_id: string; user_message: string; auto_send?: boolean }, accountId?: string, signal?: AbortSignal) => {
    const response = await request<unknown>('/chat/turn', {
      method: 'POST',
      body: JSON.stringify(payload),
      accountId,
      signal,
    })
    return normalizeChatTurnResponse(response)
  },

  listSessions: async (accountId?: string): Promise<SessionListResponse> => {
    const raw = asRecord(await request<unknown>('/chat/sessions', { accountId }))
    const sessions = Array.isArray(raw.sessions) ? raw.sessions.map(normalizeSessionSummary) : []
    return { sessions }
  },

  createSession: async (payload: { title?: string }, accountId?: string): Promise<Session> => {
    const result = await request<unknown>('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
      accountId,
    })
    return normalizeSessionSummary(result)
  },

  getSession: async (id: string, accountId?: string): Promise<SessionDetailResponse> => {
    const result = await request<unknown>(`/chat/sessions/${id}`, { accountId })
    return normalizeChatSessionDetail(result)
  },

  /* ── Accounts ───────────────────────────────────────────────────────── */

  listAccounts: async (): Promise<AccountListResponse> => {
    const payload = asRecord(await request<unknown>('/accounts'))
    const rawAccounts = Array.isArray(payload.accounts) ? payload.accounts : []
    return {
      accounts: rawAccounts.map((account) => toAccount(account as BackendAccount)),
      active_account_id: typeof payload.active_account_id === 'string' ? payload.active_account_id : null,
    }
  },

  switchAccount: async (accountId: string): Promise<Account> => {
    const payload = await request<BackendAccount>('/accounts/switch', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId }),
    })
    return toAccount(payload)
  },

  identityLogin: async (payload: { email: string; display_name: string }): Promise<Account> => {
    const result = await request<{ account: BackendAccount }>('/auth/identity', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    return toAccount(result.account)
  },

  connectAppPassword: async (appPassword: string, accountId: string) => {
    const result = await request<{ account: BackendAccount; extracted_emails: number; clean_emails_retained: number; message: string }>(
      '/onboarding/connect-app-password',
      { method: 'POST', body: JSON.stringify({ app_password: appPassword }), accountId },
    )
    return { ...result, account: toAccount(result.account) }
  },

  /* ── Google OAuth ─────────────────────────────────────────────────────── */

  googleAuthStatus: () => request<GoogleOAuthCredentialsStatus>('/auth/google/status'),

  googleAuthStart: () => request<{ auth_url: string; state: string; redirect_uri: string }>('/auth/google/start', { method: 'POST' }),

  googleAuthUploadCredentials: (clientSecretJson: string) =>
    request<GoogleOAuthCredentialsStatus>('/auth/google/upload-credentials', {
      method: 'POST',
      body: JSON.stringify({ client_secret_json: clientSecretJson }),
    }),

  /* ── Contacts ──────────────────────────────────────────────────────────── */

  listContacts: async (accountId?: string): Promise<{ contacts: RecipientContact[] }> => {
    const raw = asRecord(await request<unknown>('/contacts', { accountId }))
    const contacts = Array.isArray(raw.contacts) ? raw.contacts.map(normalizeRecipient) : []
    return { contacts }
  },

  /* ── Session management ─────────────────────────────────────────────────── */

  renameSession: async (id: string, title: string, accountId?: string): Promise<Session> => {
    const result = await request<unknown>(`/chat/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
      accountId,
    })
    return normalizeSessionSummary(result)
  },

  deleteSession: async (id: string, accountId?: string): Promise<{ deleted: boolean; session_id: string }> => {
    const result = await request<{ deleted: boolean; session_id: string }>(`/chat/sessions/${id}`, {
      method: 'DELETE',
      accountId,
    })
    return { deleted: Boolean(result.deleted), session_id: result.session_id ?? id }
  },
}
