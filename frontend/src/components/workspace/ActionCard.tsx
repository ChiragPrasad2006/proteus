import { Check, FileText, LoaderCircle } from 'lucide-react'
import { useCountdownSeconds } from '@/hooks/useCountdown'
import { useDraftState } from '@/hooks/useDraftState'
import { formatClock } from '@/lib/format'
import { describeReviewReason, friendlyName, shortEmail } from '@/lib/status'
import { cn } from '@/lib/utils'

export interface ActionCardProps {
  draftId: string
  onSelect: (draftId: string) => void
}

/**
 * Plain-language activity timeline embedded in Proteus's turn. Reads the
 * shared useDraftState store — the same source as the Paper Letter panel —
 * so chat and panel status can never disagree.
 */
export function ActionCard({ draftId, onSelect }: ActionCardProps) {
  const draft = useDraftState((state) => state.drafts[draftId])
  const secondsLeft = useCountdownSeconds(draft?.status === 'sending_countdown' ? draft.countdownEndsAt : undefined)
  if (!draft) return null

  const recipient = draft.to[0] ?? ''
  const recipientName = recipient ? friendlyName(recipient) : 'your recipient'

  let statusLine: string
  let dotClass = 'bg-ink/30'
  let icon = <FileText className="h-3.5 w-3.5" aria-hidden />
  switch (draft.status) {
    case 'pending_review':
      statusLine = 'Awaiting your approval'
      dotClass = 'bg-ember'
      break
    case 'sending_countdown':
      statusLine = `Sending in ${secondsLeft}s… (undo available)`
      dotClass = 'bg-ink'
      icon = <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
      break
    case 'sending':
      statusLine = 'Sending…'
      dotClass = 'bg-ink'
      icon = <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
      break
    case 'sent':
      statusLine = `Sent to ${recipient ? shortEmail(recipient) : 'recipient'} · ${draft.sentAt ? formatClock(draft.sentAt) : ''}`
      dotClass = 'bg-foam-ink'
      icon = <Check className="h-3.5 w-3.5" aria-hidden />
      break
    case 'failed':
      statusLine = 'Send failed — retry from the draft panel'
      dotClass = 'bg-ember-ink'
      break
    default:
      statusLine = 'Saved as draft'
  }

  const sentence = draft.status === 'pending_review'
    ? describeReviewReason(draft.reviewReason, draft.to)
    : draft.status === 'sent'
      ? `Delivered to ${recipientName}. Any edits you made were learned into your style.`
      : draft.status === 'failed'
        ? 'The send didn’t go through. Your letter is safe in the draft panel.'
        : draft.status === 'draft'
          ? 'This letter is saved. Open it any time to finish and send.'
          : 'Your letter is on its way.'

  return (
    <button
      type="button"
      onClick={() => onSelect(draft.id)}
      aria-label={`Open draft: ${draft.subject || recipientName} — ${statusLine}`}
      className={cn(
        'on-paper w-full rounded-card border border-ink-hairline bg-paper px-4 py-3 text-left text-ink transition-colors hover:border-ink/45',
        draft.status === 'pending_review' && 'border-dashed border-ember-ink/70',
      )}
    >
      <span className="flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-pill', dotClass)} aria-hidden />
        Draft created · {formatClock(draft.createdAt)}
        <span className="ml-auto inline-flex items-center gap-1.5 normal-case tracking-normal text-ink">{icon}{statusLine}</span>
      </span>
      {draft.subject ? <span className="mt-1.5 block truncate text-[13px] font-medium">{draft.subject}</span> : null}
      <span className="mt-1 block text-[12.5px] leading-relaxed text-ink-muted">{sentence}</span>
    </button>
  )
}

export default ActionCard