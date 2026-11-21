/**
 * Small typed local adapter for sub-features the backend does not expose yet.
 * Everything here is namespaced per account_id (strict multi-account
 * isolation) and falls back gracefully when localStorage is unavailable.
 *
 * TODO(backend) — endpoints needed to graduate these to server state:
 *   1. Session pinning:      PATCH /api/chat/sessions/{session_id}/pin
 *                            body { pinned: boolean } → ChatSessionSummary
 *   2. Forget learned rule:  DELETE /api/profile/rules/{rule_id}?scope=global|recipient
 *                            → { forgotten: true, rule_id }
 *   3. Edit learned rule:    PATCH /api/profile/rules/{rule_id}
 *                            body { text: string } → { rule_id, text }
 *   4. Per-recipient rules:  GET /api/profile/recipient-rules
 *                            → { rules: { recipient_email, rule_id, text }[] }
 *   5. Reset profile:        POST /api/profile/reset → UserStyleProfile
 *   6. Save draft edits:     PATCH /api/draft/{draft_id}
 *                            body { to, cc, bcc, subject, body } → { draft_id, updated_at }
 */

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

/* ── Session pins (per account) ─────────────────────────────────────────── */
// TODO(backend): replace with PATCH /api/chat/sessions/{session_id}/pin once available.

export function getPinnedSessions(accountId: string): string[] {
  const pins = readJson<string[]>(`pins.${accountId}`, [])
  return Array.isArray(pins) ? pins.filter((id): id is string => typeof id === 'string') : []
}

export function setPinnedSessions(accountId: string, sessionIds: string[]): void {
  writeJson(`pins.${accountId}`, sessionIds)
}

export function togglePinnedSession(accountId: string, sessionId: string): string[] {
  const pins = getPinnedSessions(accountId)
  const next = pins.includes(sessionId) ? pins.filter((id) => id !== sessionId) : [...pins, sessionId]
  setPinnedSessions(accountId, next)
  return next
}

/* ── Learned-rule overrides (per account) ───────────────────────────────── */
// TODO(backend): DELETE /api/profile/rules/{rule_id} and PATCH /api/profile/rules/{rule_id}.

export function getForgottenRules(accountId: string): string[] {
  const rules = readJson<string[]>(`forgotten-rules.${accountId}`, [])
  return Array.isArray(rules) ? rules.filter((rule): rule is string => typeof rule === 'string') : []
}

export function forgetRule(accountId: string, ruleText: string): void {
  const forgotten = getForgottenRules(accountId)
  if (!forgotten.includes(ruleText)) writeJson(`forgotten-rules.${accountId}`, [...forgotten, ruleText])
}

export function restoreRule(accountId: string, ruleText: string): void {
  writeJson(`forgotten-rules.${accountId}`, getForgottenRules(accountId).filter((rule) => rule !== ruleText))
}

export function getRuleOverrides(accountId: string): Record<string, string> {
  const overrides = readJson<Record<string, string>>(`rule-overrides.${accountId}`, {})
  return overrides && typeof overrides === 'object' && !Array.isArray(overrides) ? overrides : {}
}

export function setRuleOverride(accountId: string, originalText: string, newText: string): void {
  const overrides = getRuleOverrides(accountId)
  if (newText === originalText) delete overrides[originalText]
  else overrides[originalText] = newText
  writeJson(`rule-overrides.${accountId}`, overrides)
}

export function clearRuleOverrides(accountId: string): void {
  writeJson(`rule-overrides.${accountId}`, {})
  writeJson(`forgotten-rules.${accountId}`, [])
}

/* ── Saved draft edits (per account) ────────────────────────────────────── */
// TODO(backend): replace with PATCH /api/draft/{draft_id} once available.

export interface SavedDraftEdits {
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  updatedAt: string
}

export function getSavedDraftEdits(accountId: string): Record<string, SavedDraftEdits> {
  const edits = readJson<Record<string, SavedDraftEdits>>(`draft-edits.${accountId}`, {})
  return edits && typeof edits === 'object' && !Array.isArray(edits) ? edits : {}
}

export function saveDraftEdits(accountId: string, draftId: string, edits: SavedDraftEdits): void {
  const all = getSavedDraftEdits(accountId)
  all[draftId] = edits
  writeJson(`draft-edits.${accountId}`, all)
}

export function clearDraftEdits(accountId: string, draftId: string): void {
  const all = getSavedDraftEdits(accountId)
  delete all[draftId]
  writeJson(`draft-edits.${accountId}`, all)
}

/* ── One-time UX flags ──────────────────────────────────────────────────── */

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

/* ── Pane layout (global, per device) ───────────────────────────────────── */

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