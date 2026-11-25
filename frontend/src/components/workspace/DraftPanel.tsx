import { Check, ChevronDown, ChevronLeft, ChevronRight, Copy, Redo2, Send, Undo2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { RecipientInput } from '@/components/workspace/RecipientInput'
import { RefineBar } from '@/components/workspace/RefineBar'
import { StatusBadge } from '@/components/workspace/StatusBadge'
import { DiffView } from '@/components/workspace/VersionDiff'
import { IconButton } from '@/components/ui/IconButton'
import { useCountdownSeconds } from '@/hooks/useCountdown'
import { draftsForSession, useDraftState, useSelectedDraft } from '@/hooks/useDraftState'
import { forgetRuleByText } from '@/lib/localAdapter'
import { audienceFor, audienceInfo, draftWasEdited, friendlyName } from '@/lib/status'
import { cn, isValidEmail } from '@/lib/utils'
import { useAppStore } from '@/stores/useAppStore'
import { toast } from '@/stores/useToastStore'

export interface DraftPanelProps {
  /** When set, renders a close button (slide-over sheet / mobile tab). */
  onClose?: () => void
}

/**
 * Paper Letter Draft Panel — reads and writes the shared useDraftState store
 * exclusively, so its status can never disagree with the chat Action Cards.
 */
export function DraftPanel({ onClose }: DraftPanelProps) {
  const draft = useSelectedDraft()
  const drafts = useDraftState((state) => state.drafts)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const contacts = useAppStore((state) => state.contacts)
  const accountId = useAppStore((state) => state.activeAccountId)
  const select = useDraftState((state) => state.select)
  const update = useDraftState((state) => state.update)
  const saveDraft = useDraftState((state) => state.saveDraft)
  const discard = useDraftState((state) => state.discard)
  const refine = useDraftState((state) => state.refine)
  const startCountdown = useDraftState((state) => state.startCountdown)
  const undoSend = useDraftState((state) => state.undoSend)
  const sendNow = useDraftState((state) => state.sendNow)
  const retry = useDraftState((state) => state.retry)

  const sessionDrafts = useMemo(() => draftsForSession(drafts, activeSessionId), [drafts, activeSessionId])
  const [ccBccOpen, setCcBccOpen] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [compareOn, setCompareOn] = useState(false)
  const [versionIndex, setVersionIndex] = useState<number | null>(null)
  const [forgotten, setForgotten] = useState<string[]>([])
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const historyRef = useRef<{ past: string[]; future: string[]; lastPush: number }>({ past: [], future: [], lastPush: 0 })
  const [historyTick, setHistoryTick] = useState(0)

  const draftId = draft?.id
  useEffect(() => {
    historyRef.current = { past: [], future: [], lastPush: 0 }
    setHistoryTick((tick) => tick + 1)
    setCompareOn(false)
    setVersionIndex(null)
    setCcBccOpen(Boolean(draft && (draft.cc.length > 0 || draft.bcc.length > 0)))
    setForgotten([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId])

  // Auto-grow the letter body (no browser resize handle, never clips sign-offs).
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight, 180)}px`
  }, [draft?.body, draftId])

  const secondsLeft = useCountdownSeconds(draft?.status === 'sending_countdown' ? draft.countdownEndsAt : undefined)

  if (!draft) {
    return (
      <div className="on-paper flex h-full flex-col items-center justify-center bg-paper px-8 text-center text-ink">
        <img src="/art/proteus-waves.webp" alt="" aria-hidden className="engraving-multiply mb-5 h-24 w-36 object-contain opacity-60" />
        <p className="font-display text-2xl">No draft open</p>
        <p className="mt-2 max-w-[26rem] text-[13px] leading-relaxed text-ink-muted">
          Ask Proteus to write an email in the chat. The letter will appear here, ready to refine and send.
        </p>
      </div>
    )
  }

  const editable = draft.status !== 'sent' && draft.status !== 'sending' && draft.status !== 'sending_countdown'
  const audience = audienceInfo(draft.audienceType ?? audienceFor(draft.to, draft.cc, draft.bcc).mode)
  const versions = draft.versions
  const currentVersionIndex = versionIndex === null ? versions.length - 1 : Math.min(versionIndex, versions.length - 1)
  const currentVersion = versions[currentVersionIndex]
  const previousVersion = currentVersionIndex > 0 ? versions[currentVersionIndex - 1] : null
  const wordCount = draft.body.trim() ? draft.body.trim().split(/\s+/).length : 0
  const history = historyRef.current
  void historyTick

  const pushHistory = (previousBody: string) => {
    const now = Date.now()
    if (now - history.lastPush > 500 || history.past.length === 0) {
      history.past.push(previousBody)
      if (history.past.length > 100) history.past.shift()
    }
    history.lastPush = now
    history.future = []
    setHistoryTick((tick) => tick + 1)
  }

  const handleBodyChange = (next: string) => {
    pushHistory(draft.body)
    update(draft.id, { body: next })
  }

  const handleUndo = () => {
    const previous = history.past.pop()
    if (previous === undefined) return
    history.future.push(draft.body)
    update(draft.id, { body: previous })
    setHistoryTick((tick) => tick + 1)
  }

  const handleRedo = () => {
    const next = history.future.pop()
    if (next === undefined) return
    history.past.push(draft.body)
    update(draft.id, { body: next })
    setHistoryTick((tick) => tick + 1)
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(draft.body)
      toast('Letter body copied.')
    } catch {
      toast('Could not copy — select the text manually.', 'warning')
    }
  }

  const handleSend = () => {
    const all = [...draft.to, ...draft.cc, ...draft.bcc]
    if (draft.to.length === 0) { toast('Add at least one To recipient before sending.', 'warning'); return }
    if (all.some((email) => !isValidEmail(email))) { toast('Fix the highlighted recipient addresses before sending.', 'warning'); return }
    startCountdown(draft.id)
  }

  const visibleRules = draft.learnedRules.filter((rule) => !forgotten.includes(rule.text))
  const showLearned = draft.status === 'sent' && (draftWasEdited(draft) || visibleRules.length > 0)

  return (
    <div className="on-paper flex h-full flex-col overflow-y-auto bg-paper text-ink">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-ink-hairline bg-paper px-5 py-3.5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 font-mono text-[12px] uppercase tracking-[0.16em] text-ink-muted">Paper letter</span>
          <StatusBadge draft={draft} onRetry={retry} />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {sessionDrafts.length > 1 ? (
            <select
              aria-label="Select draft"
              value={draft.id}
              onChange={(event) => select(event.target.value)}
              className="max-w-[11rem] rounded-card border border-ink-hairline bg-paper px-2 py-1 font-mono text-[12px] text-ink-muted focus:outline-none"
            >
              {sessionDrafts.map((item) => (
                <option key={item.id} value={item.id}>{item.subject || friendlyName(item.to[0] ?? 'Draft')}</option>
              ))}
            </select>
          ) : null}
          {onClose ? (
            <IconButton label="Close draft panel" surface="paper" onClick={onClose}>
              <X className="h-4 w-4" />
            </IconButton>
          ) : null}
        </div>
      </div>

      <div className={cn('m-4 flex-1 rounded-card border bg-paper', draft.status === 'pending_review' ? 'animate-pulse-once border-dashed border-ember-ink' : 'border-ink-hairline')}>
        {/* Sent confirmation */}
        {draft.status === 'sent' ? (
          <div className="flex items-center gap-2.5 rounded-t-card border-b border-foam-ink/30 bg-foam px-5 py-3 text-[13px] font-medium text-foam-ink" role="status">
            <Check className="h-4 w-4 shrink-0" aria-hidden />
            Sent to {draft.to.map(friendlyName).join(', ') || 'your recipient'}
            {draft.sentAt ? <span className="ml-auto font-mono text-[12px] font-normal">{new Date(draft.sentAt).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</span> : null}
          </div>
        ) : null}
        {draft.status === 'failed' && draft.sendError ? (
          <div className="rounded-t-card border-b border-ember-ink/30 bg-ember/14 px-5 py-3 text-[12.5px] leading-relaxed text-ember-ink" role="alert">
            {draft.sendError}
          </div>
        ) : null}
        {draft.status === 'pending_review' ? (
          <p className="border-b border-ink-hairline px-5 py-3 text-[12.5px] leading-relaxed text-ink-muted">
            Waiting for your OK. Review the letter, refine it, or send when you’re happy.
          </p>
        ) : null}

        {/* Recipients */}
        <div className="space-y-2.5 px-5 pt-5">
          <RecipientInput label="To" values={draft.to} onChange={(to) => update(draft.id, { to })} contacts={contacts} disabled={!editable} />
          {ccBccOpen ? (
            <>
              <RecipientInput label="Cc" values={draft.cc} onChange={(cc) => update(draft.id, { cc })} contacts={contacts} disabled={!editable} placeholder="optional" />
              <RecipientInput label="Bcc" values={draft.bcc} onChange={(bcc) => update(draft.id, { bcc })} contacts={contacts} disabled={!editable} placeholder="optional" />
            </>
          ) : (
            <button type="button" onClick={() => setCcBccOpen(true)} disabled={!editable} className="text-[12px] font-medium text-ink-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-45">
              Cc / Bcc
            </button>
          )}
          <div className="group/aud relative inline-flex">
            <span tabIndex={0} className="cursor-help rounded-pill border border-ink-hairline px-3 py-1 font-mono text-[12px] uppercase tracking-[0.08em] text-ink-muted">
              {audience.label}
            </span>
            <span role="tooltip" className="pointer-events-none absolute left-0 top-[calc(100%+6px)] z-30 w-64 rounded-card border border-ink-hairline bg-paper p-3 text-[12px] leading-relaxed text-ink opacity-0 transition-opacity group-hover/aud:opacity-100 group-focus-within/aud:opacity-100">
              {audience.why}
            </span>
          </div>
        </div>

        {/* Subject */}
        <div className="px-5 pt-4">
          <label htmlFor="draft-subject" className="mb-1.5 block font-mono text-[12px] uppercase tracking-[0.12em] text-ink-muted">Subject</label>
          <input
            id="draft-subject"
            value={draft.subject}
            disabled={!editable}
            onChange={(event) => update(draft.id, { subject: event.target.value })}
            placeholder="Subject line"
            className="w-full whitespace-nowrap rounded-card border border-ink-hairline bg-white/30 px-3.5 py-2.5 text-[14px] font-medium text-ink placeholder:text-ink-faint focus:border-ink/60 focus:outline-none disabled:opacity-60"
          />
        </div>

        {/* Body */}
        <div className="px-5 pt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="font-mono text-[12px] uppercase tracking-[0.12em] text-ink-muted">Body</span>
            <div className="flex items-center gap-0.5">
              <IconButton label="Undo" surface="paper" disabled={!editable || history.past.length === 0} onClick={handleUndo} className="h-7 w-7">
                <Undo2 className="h-3.5 w-3.5" />
              </IconButton>
              <IconButton label="Redo" surface="paper" disabled={!editable || history.future.length === 0} onClick={handleRedo} className="h-7 w-7">
                <Redo2 className="h-3.5 w-3.5" />
              </IconButton>
              <IconButton label="Copy body" surface="paper" onClick={() => void handleCopy()} className="h-7 w-7">
                <Copy className="h-3.5 w-3.5" />
              </IconButton>
              <span className="ml-1.5 font-mono text-[12px] text-ink-muted" aria-live="polite">{wordCount} words</span>
            </div>
          </div>
          <textarea
            ref={bodyRef}
            value={draft.body}
            disabled={!editable}
            onChange={(event) => handleBodyChange(event.target.value)}
            spellCheck={false}
            aria-label="Email body"
            className="w-full resize-none overflow-y-auto rounded-card border border-ink-hairline bg-white/30 px-4 py-3.5 font-display text-[15px] leading-[1.65] text-ink placeholder:text-ink-faint focus:border-ink/60 focus:outline-none disabled:opacity-60"
            style={{ maxHeight: '52svh' }}
          />
        </div>

        {/* Refine */}
        <div className="px-5 pt-4">
          <RefineBar disabled={!editable} onRefine={(instruction) => refine(draft.id, instruction)} />
        </div>

        {/* Version history */}
        {versions.length > 0 ? (
          <div className="px-5 pt-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[12px] uppercase tracking-[0.12em] text-ink-muted">Versions</span>
              <div className="ml-auto flex items-center gap-1">
                <IconButton label="Previous version" surface="paper" disabled={currentVersionIndex === 0} onClick={() => setVersionIndex(currentVersionIndex - 1)} className="h-7 w-7">
                  <ChevronLeft className="h-3.5 w-3.5" />
                </IconButton>
                <span className="min-w-[2.5rem] text-center font-mono text-[12px] text-ink">{currentVersion?.label ?? 'v1'}</span>
                <IconButton label="Next version" surface="paper" disabled={currentVersionIndex >= versions.length - 1} onClick={() => setVersionIndex(currentVersionIndex + 1)} className="h-7 w-7">
                  <ChevronRight className="h-3.5 w-3.5" />
                </IconButton>
                <button
                  type="button"
                  onClick={() => setCompareOn((value) => !value)}
                  disabled={!previousVersion}
                  aria-pressed={compareOn}
                  className={cn('ml-1 rounded-pill border px-3 py-1 text-[12px] font-medium transition-colors disabled:opacity-45', compareOn ? 'border-ink bg-ink text-paper' : 'border-ink-hairline text-ink-muted hover:border-ink/50 hover:text-ink')}
                >
                  Compare
                </button>
              </div>
            </div>
            {compareOn && previousVersion && currentVersion ? (
              <div className="mt-2 rounded-card border border-ink-hairline bg-white/30 p-3.5">
                <p className="mb-2 font-mono text-[12px] text-ink-muted">{previousVersion.label} → {currentVersion.label}</p>
                {previousVersion.subject !== currentVersion.subject ? (
                  <p className="mb-2 text-[13px] font-medium">
                    <DiffView before={previousVersion.subject} after={currentVersion.subject} className="text-[13px]" />
                  </p>
                ) : null}
                <DiffView before={previousVersion.body} after={currentVersion.body} />
              </div>
            ) : null}
          </div>
        ) : null}

        {/* What I learned */}
        {showLearned ? (
          <div className="mx-5 mt-4 rounded-card border border-foam-ink/30 bg-foam/45 p-4">
            <p className="font-mono text-[12px] uppercase tracking-[0.12em] text-foam-ink">What I learned</p>
            {draftWasEdited(draft) ? (
              <div className="mt-2.5">
                <p className="mb-1.5 text-[12px] text-ink-muted">Your edits before sending:</p>
                <DiffView before={draft.generatedBody} after={draft.body} className="text-[13px]" />
              </div>
            ) : null}
            {visibleRules.length > 0 ? (
              <ul className="mt-3 space-y-1.5">
                {visibleRules.map((rule) => (
                  <li key={rule.id} className="flex items-start justify-between gap-3 text-[13px] leading-relaxed text-ink">
                    <span>“{rule.text}”</span>
                    <button
                      type="button"
                      onClick={() => {
                        if (!accountId) return
                        void forgetRuleByText(accountId, rule.text)
                          .then((ok) => {
                            if (!ok) { toast('That rule is no longer active.', 'warning'); return }
                            setForgotten((current) => [...current, rule.text])
                            toast('Rule forgotten.')
                          })
                          .catch(() => toast('Could not forget the rule.', 'warning'))
                      }}
                      className="shrink-0 rounded-pill border border-ink-hairline px-2.5 py-0.5 text-[12px] text-ink-muted hover:border-ink/50 hover:text-ink"
                    >
                      Forget
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {/* Primary action row */}
        <div className="flex flex-wrap items-center gap-2.5 px-5 pb-5 pt-5">
          {draft.status === 'sending_countdown' ? (
            <>
              <span className="inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-[13px] font-medium text-paper" role="status">
                <span className="h-1.5 w-1.5 animate-pulse rounded-pill bg-ember" aria-hidden />
                Sending in {secondsLeft}s…
              </span>
              <button type="button" onClick={() => undoSend(draft.id)} className="rounded-pill border border-ink-hairline px-4 py-2.5 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
                Undo
              </button>
              <button type="button" onClick={() => sendNow(draft.id)} className="rounded-pill border border-ink-hairline px-4 py-2.5 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
                Send now
              </button>
            </>
          ) : draft.status === 'sent' ? (
            <span className="inline-flex items-center gap-2 rounded-pill bg-foam px-5 py-2.5 text-[13px] font-medium text-foam-ink">
              <Check className="h-4 w-4" aria-hidden /> Sent
            </span>
          ) : (
            <>
              <button
                type="button"
                onClick={handleSend}
                disabled={draft.status === 'sending'}
                className="inline-flex items-center gap-2 rounded-pill bg-ink px-6 py-2.5 text-[13px] font-medium text-paper transition-colors hover:bg-send-hover disabled:opacity-50"
              >
                <Send className="h-4 w-4" aria-hidden />
                {draft.status === 'sending' ? 'Sending…' : draft.status === 'failed' ? 'Retry send' : 'Send'}
              </button>
              <button
                type="button"
                onClick={() => saveDraft(draft.id)}
                disabled={!editable}
                className="rounded-pill border border-ink-hairline px-4 py-2.5 text-[13px] font-medium text-ink transition-colors hover:border-ink/50 hover:bg-ink/5 disabled:opacity-45"
              >
                Save draft
              </button>
              <button
                type="button"
                onClick={() => discard(draft.id)}
                disabled={draft.status === 'sending'}
                className="rounded-pill border border-ink-hairline px-4 py-2.5 text-[13px] font-medium text-ink-muted transition-colors hover:border-ember-ink/60 hover:text-ember-ink disabled:opacity-45"
              >
                Discard
              </button>
            </>
          )}
        </div>

        {/* Collapsible runtime details */}
        <div className="border-t border-ink-hairline">
          <button
            type="button"
            onClick={() => setDetailsOpen((value) => !value)}
            aria-expanded={detailsOpen}
            className="flex w-full items-center gap-1.5 px-5 py-2.5 font-mono text-[12px] uppercase tracking-[0.12em] text-ink-muted hover:text-ink"
          >
            Details
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', detailsOpen && 'rotate-180')} aria-hidden />
          </button>
          {detailsOpen ? (
            <dl className="space-y-1 px-5 pb-4 font-mono text-[12px] text-ink-muted">
              <div className="flex gap-2"><dt className="shrink-0">model</dt><dd className="truncate text-ink">{draft.modelUsed || 'qwen3:8b'}</dd></div>
              <div className="flex gap-2"><dt className="shrink-0">audience</dt><dd className="truncate text-ink">{audience.mode}</dd></div>
              {draft.resolutionMeta?.cold_start_fallback ? (
                <div className="flex gap-2"><dt className="shrink-0">baseline</dt><dd>formal cold-start (no matching examples)</dd></div>
              ) : null}
              <div className="flex gap-2"><dt className="shrink-0">mode</dt><dd>think=false draft / think=true learn</dd></div>
              <div className="flex gap-2"><dt className="shrink-0">draft_id</dt><dd className="truncate text-ink">{draft.id}</dd></div>
            </dl>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default DraftPanel