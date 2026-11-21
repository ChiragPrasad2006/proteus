import { Check, Info, TriangleAlert, X } from 'lucide-react'
import { useCountdownSeconds } from '@/hooks/useCountdown'
import { useDraftState } from '@/hooks/useDraftState'
import { shortEmail } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'

/** Bottom-center paper toasts with inline Undo actions (never window.alert). */
export function Toasts() {
  const toasts = useToastStore((state) => state.toasts)
  const dismiss = useToastStore((state) => state.dismiss)
  const drafts = useDraftState((state) => state.drafts)
  const undoSend = useDraftState((state) => state.undoSend)
  const sendNow = useDraftState((state) => state.sendNow)

  const countdownDraft = Object.values(drafts).find((draft) => draft.status === 'sending_countdown')

  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-[75] flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 px-4" aria-live="polite">
      {countdownDraft ? <SendCountdownBar draftId={countdownDraft.id} onUndo={undoSend} onSendNow={sendNow} /> : null}
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className="on-paper pointer-events-auto flex w-full items-center gap-3 rounded-card border border-ink-hairline bg-paper px-4 py-3 text-ink"
        >
          {toast.tone === 'success' ? <Check className="h-4 w-4 shrink-0 text-foam-ink" aria-hidden /> : toast.tone === 'warning' ? <TriangleAlert className="h-4 w-4 shrink-0 text-ember-ink" aria-hidden /> : <Info className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />}
          <p className="min-w-0 flex-1 text-[13px] leading-snug">{toast.message}</p>
          {toast.actionLabel && toast.onAction ? (
            <button
              type="button"
              onClick={() => { toast.onAction?.(); dismiss(toast.id) }}
              className="shrink-0 rounded-pill border border-ink-hairline px-3 py-1 text-[12px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5"
            >
              {toast.actionLabel}
            </button>
          ) : null}
          <button type="button" onClick={() => dismiss(toast.id)} aria-label="Dismiss notification" className="shrink-0 text-ink-muted hover:text-ink">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}

function SendCountdownBar({ draftId, onUndo, onSendNow }: { draftId: string; onUndo: (id: string) => void; onSendNow: (id: string) => void }) {
  const draft = useDraftState((state) => state.drafts[draftId])
  const secondsLeft = useCountdownSeconds(draft?.countdownEndsAt)
  if (!draft) return null
  const recipient = draft.to[0] ? shortEmail(draft.to[0]) : 'your recipient'
  return (
    <div role="status" className="on-paper pointer-events-auto flex w-full items-center gap-3 rounded-card border border-ink-hairline bg-paper px-4 py-3 text-ink">
      <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-pill bg-ember" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-pill bg-ember" />
      </span>
      <p className="min-w-0 flex-1 text-[13px]">
        Sending to <span className="font-medium">{recipient}</span> in <span className={cn('font-mono', secondsLeft <= 3 && 'text-ember-ink')}>{secondsLeft}s</span>
      </p>
      <button type="button" onClick={() => onUndo(draftId)} className="shrink-0 rounded-pill bg-ink px-3.5 py-1.5 text-[12px] font-medium text-paper hover:bg-send-hover">
        Undo
      </button>
      <button type="button" onClick={() => onSendNow(draftId)} className="shrink-0 rounded-pill border border-ink-hairline px-3 py-1.5 text-[12px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
        Send now
      </button>
    </div>
  )
}

export default Toasts