/**
 * useDraftState — the single source of truth for the active session's drafts.
 *
 * Both the center chat's Activity Action Cards and the right Paper Letter
 * Draft Panel read from and write to this store, keyed by draft_id, so their
 * status, recipients, subject, body and timestamps can never disagree.
 *
 * Lifecycle: draft → pending_review → sending_countdown → sending → sent
 * (any pre-send state can fail → failed → retry re-enters the countdown).
 */

import { create } from 'zustand'
import { api } from '@/lib/api'
import { discardDraft, saveDraftEdits } from '@/lib/localAdapter'
import { audienceFor, friendlyName, unifiedFromWire } from '@/lib/status'
import { toast } from '@/stores/useToastStore'
import type { EmailDraft, LearnedRule, ResolutionMeta, UnifiedDraftStatus, WorkspaceDraft } from '@/types'
import { uid } from '@/lib/utils'

export const SEND_COUNTDOWN_SECONDS = 10

interface DraftState {
  drafts: Record<string, WorkspaceDraft>
  selectedDraftId: string | null
  /** Account scope guard — drafts from another account are never shown. */
  accountId: string | null
  hydrate: (cards: EmailDraft[], sessionId: string, accountId: string) => void
  ingestTurnDraft: (card: EmailDraft, sessionId: string, accountId: string) => void
  select: (draftId: string | null) => void
  update: (draftId: string, patch: Partial<Pick<WorkspaceDraft, 'to' | 'cc' | 'bcc' | 'subject' | 'body'>>) => void
  saveDraft: (draftId: string) => void
  discard: (draftId: string) => void
  refine: (draftId: string, instruction: string) => Promise<boolean>
  startCountdown: (draftId: string) => void
  undoSend: (draftId: string) => void
  sendNow: (draftId: string) => void
  retry: (draftId: string) => void
  reset: () => void
}

const countdownTimers = new Map<string, ReturnType<typeof setInterval>>()

function clearCountdownTimer(draftId: string): void {
  const timer = countdownTimers.get(draftId)
  if (timer) { clearInterval(timer); countdownTimers.delete(draftId) }
}

function makeVersion(draft: Pick<WorkspaceDraft, 'subject' | 'body' | 'versions'>, source: 'generated' | 'refined') {
  return {
    label: `v${draft.versions.length + 1}`,
    subject: draft.subject,
    body: draft.body,
    createdAt: new Date().toISOString(),
    source,
  }
}

function fromCard(card: EmailDraft, sessionId: string, accountId: string): WorkspaceDraft {
  const now = new Date().toISOString()
  const status = unifiedFromWire(card.status)
  const base: WorkspaceDraft = {
    id: card.id || uid('draft'),
    sessionId,
    accountId,
    to: card.to,
    cc: card.cc,
    bcc: card.bcc,
    subject: card.subject,
    body: card.body,
    status,
    audienceType: card.audienceType ?? audienceFor(card.to, card.cc, card.bcc).mode,
    resolutionMeta: card.resolutionMeta,
    reviewReason: card.reviewReason,
    modelUsed: card.modelUsed,
    createdAt: now,
    updatedAt: now,
    sentAt: status === 'sent' ? now : undefined,
    versions: [],
    learnedRules: [],
    generatedSubject: card.subject,
    generatedBody: card.body,
  }
  base.versions = [makeVersion(base, 'generated')]
  return base
}

/** Local lifecycle states that must never be regressed by a server re-hydrate. */
const IN_FLIGHT: UnifiedDraftStatus[] = ['sending_countdown', 'sending']

export const useDraftState = create<DraftState>((set, get) => {
  const patchDraft = (draftId: string, patch: Partial<WorkspaceDraft>) => {
    set((state) => {
      const existing = state.drafts[draftId]
      if (!existing) return {}
      return { drafts: { ...state.drafts, [draftId]: { ...existing, ...patch } } }
    })
  }

  const finalizeSend = async (draftId: string) => {
    clearCountdownTimer(draftId)
    const draft = get().drafts[draftId]
    if (!draft || draft.status === 'sent') return
    patchDraft(draftId, { status: 'sending', countdownEndsAt: undefined })
    try {
      const result = await api.approveAndLearn(
        { draft_id: draft.id, final_subject: draft.subject, final_body: draft.body },
        draft.accountId,
      )
      const current = get().drafts[draftId]
      if (!current) return
      if (result.status === 'SENT') {
        const learnedRules: LearnedRule[] = result.extracted_rules.map((text) => ({
          id: uid('rule'),
          text,
          scope: result.rule_scope === 'recipient' ? 'recipient' : 'global',
        }))
        patchDraft(draftId, {
          status: 'sent',
          sentAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          learnedRules,
          sendError: undefined,
        })
        toast(`Sent to ${current.to.map(friendlyName).join(', ') || 'your recipient'}.`, 'success')
      } else {
        patchDraft(draftId, {
          status: 'failed',
          sendError: result.receipt_error || 'The send did not go through. Your draft is safe — try again.',
          updatedAt: new Date().toISOString(),
        })
        toast('Send failed — the draft is still here for retry.', 'warning', 6000)
      }
    } catch (err) {
      patchDraft(draftId, {
        status: 'failed',
        sendError: err instanceof Error ? err.message : 'The send did not go through.',
        updatedAt: new Date().toISOString(),
      })
      toast('Send failed — the draft is still here for retry.', 'warning', 6000)
    }
  }

  return {
    drafts: {},
    selectedDraftId: null,
    accountId: null,

    hydrate: (cards, sessionId, accountId) => {
      set((state) => {
        const drafts = { ...state.drafts }
        for (const card of cards) {
          const incoming = fromCard(card, sessionId, accountId)
          const existing = drafts[incoming.id]
          if (!existing) {
            drafts[incoming.id] = incoming
            continue
          }
          // Server is authoritative for SENT; never regress an in-flight send;
          // otherwise keep local text edits and client lifecycle state.
          if (IN_FLIGHT.includes(existing.status)) continue
          if (incoming.status === 'sent' && existing.status !== 'sent') {
            drafts[incoming.id] = { ...existing, status: 'sent', sentAt: existing.sentAt ?? incoming.sentAt, reviewReason: incoming.reviewReason }
            continue
          }
          drafts[incoming.id] = {
            ...existing,
            reviewReason: incoming.reviewReason,
            modelUsed: incoming.modelUsed || existing.modelUsed,
            audienceType: incoming.audienceType ?? existing.audienceType,
            resolutionMeta: incoming.resolutionMeta ?? existing.resolutionMeta,
          }
        }
        const selected = state.selectedDraftId && drafts[state.selectedDraftId] ? state.selectedDraftId : null
        return { drafts, accountId, selectedDraftId: selected }
      })
    },

    ingestTurnDraft: (card, sessionId, accountId) => {
      const incoming = fromCard(card, sessionId, accountId)
      set((state) => {
        const existing = state.drafts[incoming.id]
        let next: WorkspaceDraft
        if (!existing) {
          next = incoming
        } else {
          const textChanged = existing.subject !== incoming.subject || existing.body !== incoming.body
          next = {
            ...existing,
            to: incoming.to,
            cc: incoming.cc,
            bcc: incoming.bcc,
            subject: incoming.subject,
            body: incoming.body,
            reviewReason: incoming.reviewReason,
            modelUsed: incoming.modelUsed || existing.modelUsed,
            audienceType: incoming.audienceType ?? existing.audienceType,
            resolutionMeta: incoming.resolutionMeta ?? existing.resolutionMeta,
            status: IN_FLIGHT.includes(existing.status) ? existing.status : incoming.status,
            sentAt: incoming.status === 'sent' ? (existing.sentAt ?? incoming.sentAt) : existing.sentAt,
            updatedAt: new Date().toISOString(),
            generatedSubject: incoming.subject,
            generatedBody: incoming.body,
            versions: textChanged
              ? [...existing.versions, makeVersion({ subject: incoming.subject, body: incoming.body, versions: existing.versions }, 'refined')]
              : existing.versions,
          }
        }
        return { drafts: { ...state.drafts, [next.id]: next }, selectedDraftId: next.id, accountId }
      })
    },

    select: (draftId) => set({ selectedDraftId: draftId }),

    update: (draftId, patch) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status === 'sent' || IN_FLIGHT.includes(draft.status)) return
      patchDraft(draftId, { ...patch, updatedAt: new Date().toISOString() })
      const touchesRecipients =
        Object.prototype.hasOwnProperty.call(patch, 'to') ||
        Object.prototype.hasOwnProperty.call(patch, 'cc') ||
        Object.prototype.hasOwnProperty.call(patch, 'bcc')
      if (!touchesRecipients) return

      // Predict the pill locally, then reconcile with the backend's authoritative
      // audience from PATCH /api/draft/{id}. No reload needed for the chip edit.
      const next = { ...draft, ...patch }
      patchDraft(draftId, { audienceType: audienceFor(next.to, next.cc, next.bcc).mode })
      void saveDraftEdits(draft.accountId, draftId, {
        to: next.to,
        cc: next.cc,
        bcc: next.bcc,
        subject: next.subject,
        body: next.body,
      }).then((result) => {
        const current = get().drafts[draftId]
        if (!current) return
        // Ignore a stale response if the user changed recipients again meanwhile.
        if (JSON.stringify([current.to, current.cc, current.bcc]) !== JSON.stringify([next.to, next.cc, next.bcc])) return
        patchDraft(draftId, {
          audienceType: result.audience_type ?? current.audienceType,
          resolutionMeta: result.resolution_meta ?? current.resolutionMeta,
        })
      }).catch(() => {
        // Keep the optimistic prediction; the next Save/Refine will reconcile.
      })
    },

    saveDraft: async (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status === 'sent' || IN_FLIGHT.includes(draft.status)) return
      let savedAudience = audienceFor(draft.to, draft.cc, draft.bcc).mode
      let savedMeta: ResolutionMeta | undefined
      try {
        const result = await saveDraftEdits(draft.accountId, draftId, {
          to: draft.to,
          cc: draft.cc,
          bcc: draft.bcc,
          subject: draft.subject,
          body: draft.body,
        })
        savedAudience = result.audience_type ?? savedAudience
        savedMeta = result.resolution_meta
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Could not save the draft.', 'warning', 6000)
        return
      }
      patchDraft(draftId, {
        status: 'draft',
        updatedAt: new Date().toISOString(),
        audienceType: savedAudience,
        resolutionMeta: savedMeta ?? draft.resolutionMeta,
      })
      toast('Draft saved.')
    },

    discard: async (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft) return
      clearCountdownTimer(draftId)
      try {
        await discardDraft(draft.accountId, draftId)
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Could not discard the draft.', 'warning', 6000)
        return
      }
      set((state) => {
        const drafts = { ...state.drafts }
        delete drafts[draftId]
        const remaining = Object.values(drafts)
          .filter((item) => item.sessionId === draft.sessionId)
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
        const selectedDraftId = state.selectedDraftId === draftId ? (remaining[0]?.id ?? null) : state.selectedDraftId
        return { drafts, selectedDraftId }
      })
      toast('Draft discarded.')
    },

    refine: async (draftId, instruction) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status === 'sent' || IN_FLIGHT.includes(draft.status)) return false
      try {
        const result = await api.tweakDraft({
          draft_id: draft.id,
          tweak_instruction: instruction,
          current_to: draft.to,
          current_cc: draft.cc,
          current_bcc: draft.bcc,
          current_subject: draft.subject,
          current_body: draft.body,
        }, draft.accountId)
        const current = get().drafts[draftId]
        if (!current) return false
        const version = makeVersion({ subject: result.subject, body: result.body, versions: current.versions }, 'refined')
        patchDraft(draftId, {
          subject: result.subject,
          body: result.body,
          generatedSubject: result.subject,
          generatedBody: result.body,
          status: 'pending_review',
          updatedAt: new Date().toISOString(),
          audienceType: result.audience_type ?? current.audienceType,
          resolutionMeta: result.resolution_meta ?? current.resolutionMeta,
          versions: [...current.versions, version],
        })
        toast(`Draft refined — ${version.label} ready for review.`)
        return true
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Could not refine the draft.', 'warning', 6000)
        return false
      }
    },

    startCountdown: (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status === 'sent' || IN_FLIGHT.includes(draft.status)) return
      if (draft.to.length === 0) {
        toast('Add at least one recipient before sending.', 'warning')
        return
      }
      clearCountdownTimer(draftId)
      const endsAt = Date.now() + SEND_COUNTDOWN_SECONDS * 1000
      patchDraft(draftId, {
        status: 'sending_countdown',
        preCountdownStatus: draft.status === 'failed' ? 'pending_review' : draft.status,
        countdownEndsAt: endsAt,
        sendError: undefined,
      })
      countdownTimers.set(draftId, setInterval(() => {
        const current = get().drafts[draftId]
        if (!current || current.status !== 'sending_countdown') {
          clearCountdownTimer(draftId)
          return
        }
        if (Date.now() >= (current.countdownEndsAt ?? 0)) void finalizeSend(draftId)
      }, 250))
    },

    undoSend: (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status !== 'sending_countdown') return
      clearCountdownTimer(draftId)
      patchDraft(draftId, {
        status: draft.preCountdownStatus ?? 'pending_review',
        countdownEndsAt: undefined,
        preCountdownStatus: undefined,
      })
      toast('Send cancelled — your draft is back in review.')
    },

    sendNow: (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status !== 'sending_countdown') return
      void finalizeSend(draftId)
    },

    retry: (draftId) => {
      const draft = get().drafts[draftId]
      if (!draft || draft.status !== 'failed') return
      get().startCountdown(draftId)
    },

    reset: () => {
      for (const draftId of countdownTimers.keys()) clearCountdownTimer(draftId)
      set({ drafts: {}, selectedDraftId: null, accountId: null })
    },
  }
})

/** Selector: the currently selected draft (or null). */
export const useSelectedDraft = () => useDraftState((state) =>
  state.selectedDraftId ? state.drafts[state.selectedDraftId] ?? null : null,
)

/** Selector: drafts belonging to a session, newest first. */
export function draftsForSession(drafts: Record<string, WorkspaceDraft>, sessionId: string | null): WorkspaceDraft[] {
  if (!sessionId) return []
  return Object.values(drafts)
    .filter((draft) => draft.sessionId === sessionId)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}