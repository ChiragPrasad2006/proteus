/**
 * Typed adapter for the backend persistence endpoints. Every call is scoped to
 * the active account through the ``X-Account-ID`` header, so no state can leak
 * between accounts.
 *
 * Server-backed (real endpoints):
 *   PATCH  /api/chat/sessions/{session_id}/pin
 *   GET    /api/profile/recipient-rules
 *   PATCH  /api/profile/rules/{rule_id}
 *   DELETE /api/profile/rules/{rule_id}
 *   POST   /api/profile/reset
 *   PATCH  /api/draft/{draft_id}
 *   DELETE /api/draft/{draft_id}
 *
 * The remaining helpers are device-local UI preferences (tour, pane layout,
 * auto-send acknowledgement) — they are not server state.
 */

import type { Session, UserStyleProfile } from '@/types'

const BASE = '/api'

export class LocalAdapterError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'LocalAdapterError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit & { accountId?: string }): Promise<T> {
  const { accountId, headers, ...rest } = init ?? {}
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(accountId ? { 'X-Account-ID': accountId } : {}),
        ...(headers ?? {}),
      },
      ...rest,
    })
  } catch {
    throw new LocalAdapterError('Cannot reach the local backend.', 0)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new LocalAdapterError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return await response.json() as T
}

/* ── Session pinning ─────────────────────────────────────────────────────── */

/** Ids of the account's pinned sessions (server state). */
export async function listPinnedSessions(accountId: string): Promise<string[]> {
  const payload = await request<{ sessions: (Session & { pinned?: boolean })[] }>('/chat/sessions', { accountId })
  return (payload.sessions ?? []).filter((session) => session.pinned).map((session) => session.id)
}

/** Pin or unpin a session. Returns the updated session summary. */
export async function setPinnedSession(accountId: string, sessionId: string, pinned: boolean): Promise<Session> {
  return request<Session>(`/chat/sessions/${encodeURIComponent(sessionId)}/pin`, {
    method: 'PATCH',
    body: JSON.stringify({ pinned }),
    accountId,
  })
}

/* ── Learned style rules ─────────────────────────────────────────────────── */

export interface RecipientRule {
  rule_id: string
  recipient_email: string
  text: string
}

/** Every per-recipient learned rule of the account. */
export async function listRecipientRules(accountId: string): Promise<RecipientRule[]> {
  const payload = await request<{ rules: RecipientRule[] }>('/profile/recipient-rules', { accountId })
  return payload.rules ?? []
}

/** Edit a learned rule. ``rule_id`` is ``global:<index>`` or ``recipient:<email>:<index>``. */
export async function updateRule(
  accountId: string,
  ruleId: string,
  text: string,
  scope?: 'global' | 'recipient',
): Promise<{ rule_id: string; text: string }> {
  const query = scope ? `?scope=${scope}` : ''
  return request<{ rule_id: string; text: string }>(`/profile/rules/${encodeURIComponent(ruleId)}${query}`, {
    method: 'PATCH',
    body: JSON.stringify({ text }),
    accountId,
  })
}

/** Forget a learned rule. */
export async function forgetRule(
  accountId: string,
  ruleId: string,
  scope?: 'global' | 'recipient',
): Promise<{ forgotten: boolean; rule_id: string }> {
  const query = scope ? `?scope=${scope}` : ''
  return request<{ forgotten: boolean; rule_id: string }>(`/profile/rules/${encodeURIComponent(ruleId)}${query}`, {
    method: 'DELETE',
    accountId,
  })
}

/** Forget a global rule by its text (used by the post-send "What I learned" card). */
export async function forgetRuleByText(accountId: string, text: string): Promise<boolean> {
  const profile = await request<UserStyleProfile>('/profile', { accountId })
  const index = (profile.global_learned_rules ?? []).indexOf(text)
  if (index < 0) return false
  await forgetRule(accountId, `global:${index}`, 'global')
  return true
}

/** Reset learned rules and corpus-derived stylometry for the account. */
export async function resetProfile(accountId: string): Promise<UserStyleProfile> {
  return request<UserStyleProfile>('/profile/reset', { method: 'POST', body: '{}', accountId })
}

/* ── Staged drafts (Save draft / Discard) ────────────────────────────────── */

export interface DraftEdits {
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
}

/** Persist draft edits so they survive a reload. */
export async function saveDraftEdits(
  accountId: string,
  draftId: string,
  edits: DraftEdits,
): Promise<{ draft_id: string; updated_at: string }> {
  return request<{ draft_id: string; updated_at: string }>(`/draft/${encodeURIComponent(draftId)}`, {
    method: 'PATCH',
    body: JSON.stringify(edits),
    accountId,
  })
}

/** Discard a staged draft so it stays discarded after a reload. */
export async function discardDraft(accountId: string, draftId: string): Promise<{ deleted: boolean; draft_id: string }> {
  return request<{ deleted: boolean; draft_id: string }>(`/draft/${encodeURIComponent(draftId)}`, {
    method: 'DELETE',
    accountId,
  })
}

/* ── Device-local UI preferences (not server state) ──────────────────────── */

const PREFIX = 'proteus.local.v1'

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(`${PREFIX}.${key}`)
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`${PREFIX}.${key}`, JSON.stringify(value))
  } catch {
    /* Private mode / quota — local-only features degrade silently. */
  }
}

export function isTourDone(): boolean {
  return readJson<boolean>('proteus_tour_done', false) === true
}

export function setTourDone(): void {
  // Spec-mandated key: stored once, after mailbox unlock.
  try { window.localStorage.setItem('proteus_tour_done', 'true') } catch { /* ignore */ }
}

export function isAutoSendConfirmed(accountId: string): boolean {
  return readJson<boolean>(`autosend-confirmed.${accountId}`, false) === true
}

export function setAutoSendConfirmed(accountId: string): void {
  writeJson(`autosend-confirmed.${accountId}`, true)
}

export interface PaneLayout {
  leftWidth: number
  rightWidth: number
  leftCollapsed: boolean
  rightCollapsed: boolean
}

export const DEFAULT_PANE_LAYOUT: PaneLayout = {
  leftWidth: 260,
  rightWidth: 440,
  leftCollapsed: false,
  rightCollapsed: false,
}

export function getPaneLayout(): PaneLayout {
  const stored = readJson<Partial<PaneLayout>>('pane-layout', {})
  return {
    leftWidth: clampWidth(stored.leftWidth, 220, 360, DEFAULT_PANE_LAYOUT.leftWidth),
    rightWidth: clampWidth(stored.rightWidth, 360, 620, DEFAULT_PANE_LAYOUT.rightWidth),
    leftCollapsed: stored.leftCollapsed === true,
    rightCollapsed: stored.rightCollapsed === true,
  }
}

export function setPaneLayout(layout: PaneLayout): void {
  writeJson('pane-layout', layout)
}

function clampWidth(value: unknown, min: number, max: number, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback
}
