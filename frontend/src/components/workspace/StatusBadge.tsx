import { Check, LoaderCircle, RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import { useCountdownSeconds } from '@/hooks/useCountdown'
import { statusLabel } from '@/lib/status'
import { cn } from '@/lib/utils'
import type { WorkspaceDraft } from '@/types'

export interface StatusBadgeProps {
  draft: WorkspaceDraft
  onRetry?: (draftId: string) => void
  className?: string
}

/**
 * Single-source status pill (reads useDraftState via the passed draft).
 * All tones meet WCAG AA on the paper surface.
 */
export function StatusBadge({ draft, onRetry, className }: StatusBadgeProps) {
  const secondsLeft = useCountdownSeconds(draft.status === 'sending_countdown' ? draft.countdownEndsAt : undefined)
  const label = statusLabel(draft.status, secondsLeft)
  const base = 'inline-flex items-center gap-1.5 rounded-pill border px-3 py-1 font-mono text-[12px] uppercase tracking-[0.08em]'

  let pill: ReactNode
  switch (draft.status) {
    case 'pending_review':
      pill = <span className={cn(base, 'border-ember-ink/60 bg-ember/14 text-ember-ink')}>{label}</span>
      break
    case 'sending_countdown':
    case 'sending':
      pill = (
        <span className={cn(base, 'border-ink bg-ink text-paper')}>
          <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
          {label}
        </span>
      )
      break
    case 'sent':
      pill = (
        <span className={cn(base, 'border-foam-ink/50 bg-foam text-foam-ink')}>
          <Check className="h-3 w-3" aria-hidden />
          {label}
        </span>
      )
      break
    case 'failed':
      pill = (
        <span className={cn(base, 'border-ember-ink/60 bg-ember/14 text-ember-ink')}>
          {label}
          {onRetry ? (
            <button
              type="button"
              onClick={() => onRetry(draft.id)}
              className="ml-1 inline-flex items-center gap-1 rounded-pill border border-ember-ink/60 px-2 py-0.5 text-[12px] normal-case tracking-normal hover:bg-ember/15"
            >
              <RotateCcw className="h-3 w-3" aria-hidden />
              Retry
            </button>
          ) : null}
        </span>
      )
      break
    default:
      pill = <span className={cn(base, 'border-ink-hairline text-ink')}>{label}</span>
  }

  return (
    <span aria-live="polite" className={className}>
      {pill}
      {draft.status === 'sending_countdown' ? (
        <span className="sr-only">Send can be undone for {secondsLeft} more seconds.</span>
      ) : null}
    </span>
  )
}

export default StatusBadge