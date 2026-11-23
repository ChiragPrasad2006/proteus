/**
 * Plain-language translation layer. Raw backend flags ("auto_send is False",
 * "first-recipient gate", "THINK=OFF") never reach normal UI copy — every
 * status and review reason is rendered as calm, human English here.
 */

import type { AudienceMode, DraftStatus, UnifiedDraftStatus, WorkspaceDraft } from '@/types'

export function unifiedFromWire(status: DraftStatus | string | undefined): UnifiedDraftStatus {
  switch (status) {
    case 'SENT': return 'sent'
    case 'FAILED': return 'failed'
    case 'PENDING_REVIEW': return 'pending_review'
    default: return 'draft'
  }
}

export function statusLabel(status: UnifiedDraftStatus, secondsLeft?: number): string {
  switch (status) {
    case 'draft': return 'Draft'
    case 'pending_review': return 'Awaiting approval'
    case 'sending_countdown': return `Sending in ${Math.max(0, secondsLeft ?? 10)}s…`
    case 'sending': return 'Sending…'
    case 'sent': return 'Sent'
    case 'failed': return 'Failed'
  }
}

/** Friendly display name from an email local-part ("kami.sama" → "Kami Sama"). */
export function friendlyName(email: string): string {
  const local = (email.split('@')[0] ?? email).replace(/^["']+|["']+$/g, '')
  const parts = local.split(/[._-]+/).filter(Boolean)
  return parts.length
    ? parts.map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
    : email
}

export function shortEmail(email: string): string {
  const [local, domain] = email.split('@')
  if (!domain) return email
  const head = (local ?? '').slice(0, 6)
  return `${head}@…`
}

/**
 * Translate the backend's semicolon-joined review reasons into one calm
 * sentence. Debug fragments are dropped, not shown.
 */
export function describeReviewReason(reviewReason: string | undefined, to: string[]): string {
  const name = to[0] ? friendlyName(to[0]) : 'this recipient'
  if (!reviewReason) return 'Take a look before sending.'
  const reasons = reviewReason.split(';').map((reason) => reason.trim()).filter(Boolean)
  const firstContact = reasons.some((reason) => reason.startsWith('first contact with'))
  const noProfile = reasons.some((reason) => reason.includes('no style profile'))
  const modelIssue = reasons.some((reason) => reason.includes('drafting model unavailable') || reason.includes('draft generation error'))
  const sendFailed = reasons.find((reason) => reason.startsWith('send failed') || reason.startsWith('send error'))
  if (sendFailed) return 'The last send attempt didn’t go through. Your draft is safe — review it and try again.'
  if (reasons.some((reason) => reason.startsWith('Revised draft'))) return 'I’ve updated the draft. Take a look before sending.'
  const parts: string[] = []
  if (firstContact) parts.push(`Since it’s your first email to ${name}, I’m waiting for your OK before sending.`)
  if (noProfile) parts.push('Your style profile isn’t built yet, so I used a safe default voice.')
  if (modelIssue) parts.push('The local model was unavailable, so I wrote a simple template you can edit.')
  if (parts.length === 0) parts.push('Review it, and send when you’re happy.')
  return parts.join(' ')
}

/** Calm chat copy for an assistant turn that produced (or sent) a draft. */
export function humanizeDraftTurn(wireStatus: DraftStatus | string, draft: { to: string[] }, reviewReason?: string): string {
  const names = draft.to.map(friendlyName)
  const who = names.length === 0 ? 'your recipient' : names.length === 1 ? names[0]! : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
  if (wireStatus === 'SENT') return `Sent your email to ${who}.`
  return `I’ve drafted this to ${who}. ${describeReviewReason(reviewReason, draft.to)}`
}

/**
 * Sanitize persisted assistant messages from older sessions that still carry
 * raw backend flags ("held it for review: … auto_send is False …").
 */
export function cleanAssistantContent(content: string, to: string[]): string {
  // Older turns stored a duplicated "I've drafted this to X." prefix — collapse it.
  const deduped = content.replace(/(I[’']ve drafted this to [^.]+)\.\s*\1\./i, '$1.')
  if (deduped !== content) return deduped
  const heldIndex = deduped.indexOf('held it for review:')
  if (heldIndex >= 0) {
    const reasons = deduped.slice(heldIndex + 'held it for review:'.length).trim()
    const names = to.map(friendlyName)
    const who = names.length === 0 ? 'your recipient' : names.join(', ')
    return `I’ve drafted this to ${who}. ${describeReviewReason(reasons, to)}`
  }
  if (content.includes('auto_send is False') || content.includes('first-recipient gate')) {
    return describeReviewReason(content, to)
  }
  return content
}

export interface AudienceInfo {
  mode: AudienceMode
  label: string
  why: string
}

export function audienceFor(to: string[], cc: string[], bcc: string[]): AudienceInfo {
  if (bcc.length >= 2) {
    return {
      mode: 'broadcast_bcc',
      label: 'Broadcast BCC',
      why: 'Several recipients are hidden in BCC, so Proteus keeps the tone neutral and impersonal — no single person is addressed, and nobody sees the others.',
    }
  }
  if (cc.length > 0 || to.length > 1) {
    return {
      mode: 'group_cc',
      label: 'Group CC',
      why: 'This email has a shared audience (multiple To or Cc recipients), so Proteus writes for the group — inclusive greetings and no private asides.',
    }
  }
  return {
    mode: '1on1_private',
    label: '1:1 Private',
    why: 'One recipient, no copies — Proteus matches your personal voice for this relationship, including your usual greeting and sign-off.',
  }
}

/** True when the user changed the machine-generated text before sending. */
export function draftWasEdited(draft: WorkspaceDraft): boolean {
  return draft.subject !== draft.generatedSubject || draft.body !== draft.generatedBody
}

/** Sentence-case title derived from the first user prompt or draft subject. */
export function deriveSessionTitle(source: string): string {
  const clean = source.replace(/\s+/g, ' ').trim()
  if (!clean) return 'New session'
  const clipped = clean.length > 64 ? `${clean.slice(0, 61).trimEnd()}…` : clean
  return clipped.charAt(0).toUpperCase() + clipped.slice(1)
}