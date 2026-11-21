import { useEffect, useState, type CSSProperties } from 'react'
import { isTourDone, setTourDone } from '@/lib/localAdapter'
import { cn } from '@/lib/utils'

const STEPS = [
  {
    target: '[data-tour="rail"]',
    title: 'Your sessions live here',
    body: 'Pinned and grouped by day, searchable with ⌘K. Double-click any title to rename it; the ⋯ menu pins or deletes with an 8-second undo.',
  },
  {
    target: '[data-tour="composer"]',
    title: 'Brief Proteus in plain language',
    body: 'Type @ to mention a contact and / for tone macros. Enter sends your message; Shift+Enter adds a new line.',
  },
  {
    target: '[data-tour="draft"]',
    title: 'The paper letter & undo-send',
    body: 'Refine the letter, compare versions, then Send. Every send waits 10 seconds with an Undo button — nothing leaves without your OK.',
  },
] as const

/** Lightweight 3-step first-run tour, shown once after mailbox unlock. */
export function Coachmarks({ enabled }: { enabled: boolean }) {
  const [step, setStep] = useState<number | null>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)

  useEffect(() => {
    if (!enabled || isTourDone()) return
    const timer = setTimeout(() => setStep(0), 700)
    return () => clearTimeout(timer)
  }, [enabled])

  useEffect(() => {
    if (step === null) return
    const measure = () => {
      const el = document.querySelector(STEPS[step]!.target)
      setRect(el ? el.getBoundingClientRect() : null)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [step])

  if (step === null) return null
  const current = STEPS[step]!
  const finish = () => { setTourDone(); setStep(null) }

  // Anchor near the target when it is on screen; otherwise center the card.
  const CARD_W = 300
  let style: CSSProperties = { left: '50%', top: '30%', transform: 'translateX(-50%)' }
  if (rect && rect.width > 0 && window.innerWidth >= 768) {
    if (step === 0) {
      style = { left: Math.min(rect.right + 14, window.innerWidth - CARD_W - 16), top: Math.max(80, rect.top + 72) }
    } else if (step === 1) {
      style = { left: Math.max(16, Math.min(rect.left + 24, window.innerWidth - CARD_W - 16)), top: Math.max(16, rect.top - 170) }
    } else {
      style = { left: Math.max(16, rect.left - CARD_W - 14), top: Math.max(80, rect.top + 60) }
    }
  }

  return (
    <div
      role="dialog"
      aria-label={`Getting started, step ${step + 1} of ${STEPS.length}`}
      className="fixed z-[68] w-[300px] rounded-card border border-hairline bg-cobalt-deep p-4"
      style={style}
    >
      <p className="font-mono text-[12px] uppercase tracking-[0.14em] text-foam">Step {step + 1} of {STEPS.length}</p>
      <h3 className="mt-1.5 font-display text-lg leading-snug text-paper">{current.title}</h3>
      <p className="mt-2 text-[12.5px] leading-relaxed text-paper-muted">{current.body}</p>
      <div className="mt-4 flex items-center gap-2">
        <div className="flex gap-1" aria-hidden>
          {STEPS.map((_, index) => (
            <span key={index} className={cn('h-1.5 w-1.5 rounded-pill', index === step ? 'bg-foam' : 'bg-paper/25')} />
          ))}
        </div>
        <button type="button" onClick={finish} className="ml-auto text-[12px] text-paper-muted hover:text-paper">
          Skip tour
        </button>
        <button
          type="button"
          onClick={() => (step === STEPS.length - 1 ? finish() : setStep(step + 1))}
          className="rounded-pill bg-paper px-3.5 py-1.5 text-[12px] font-medium text-ink hover:bg-foam"
        >
          {step === STEPS.length - 1 ? 'Done' : 'Next'}
        </button>
      </div>
    </div>
  )
}

export default Coachmarks