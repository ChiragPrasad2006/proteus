import { useMemo } from 'react'
import { wordDiff, type DiffSegment } from '@/lib/diff'
import { cn } from '@/lib/utils'

export interface DiffViewProps {
  before: string
  after: string
  className?: string
}

/**
 * Inline word diff: additions in foam + foam-ink, removals in pale ember +
 * ember-ink strikethrough. Both tones are WCAG AA on the paper surface.
 */
export function DiffView({ before, after, className }: DiffViewProps) {
  const segments = useMemo(() => wordDiff(before, after), [before, after])
  return (
    <p className={cn('whitespace-pre-wrap font-display text-[14px] leading-[1.65] text-ink', className)}>
      {segments.map((segment: DiffSegment, index: number) => {
        if (segment.type === 'add') {
          return <mark key={index} className="rounded-[2px] bg-foam px-0.5 text-foam-ink">{segment.text}</mark>
        }
        if (segment.type === 'del') {
          return <del key={index} className="rounded-[2px] bg-ember/14 px-0.5 text-ember-ink decoration-ember-ink/70">{segment.text}</del>
        }
        return <span key={index}>{segment.text}</span>
      })}
    </p>
  )
}

export default DiffView