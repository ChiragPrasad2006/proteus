import { LoaderCircle, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

export interface RefineBarProps {
  disabled?: boolean
  onRefine: (instruction: string) => Promise<boolean>
}

const QUICK_REFINES = ['Shorter', 'Warmer', 'More formal', 'Add a question'] as const

/**
 * Refine bar — replaces the old "Suggest a tweak" control. The action button
 * is always labeled "Refine" (never "Send"); only the primary action row sends.
 */
export function RefineBar({ disabled = false, onRefine }: RefineBarProps) {
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy || disabled) return
    setBusy(true)
    try {
      const ok = await onRefine(trimmed)
      if (ok) setInstruction('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn(disabled && 'pointer-events-none opacity-55')}>
      <div className="flex items-center gap-2 rounded-card border border-ink-hairline bg-white/30 py-1.5 pl-3 pr-1.5 transition-colors focus-within:border-ink/60">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-ember-ink" aria-hidden />
        <input
          value={instruction}
          disabled={disabled || busy}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void run(instruction) } }}
          placeholder="Make it warmer, shorter, more formal…"
          aria-label="Refine instruction"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void run(instruction)}
          disabled={disabled || busy || !instruction.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-pill border border-ink-hairline bg-paper px-3.5 py-1.5 text-[12px] font-medium text-ink transition-colors hover:border-ink/50 hover:bg-ink/5 disabled:opacity-45"
        >
          {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Sparkles className="h-3.5 w-3.5" aria-hidden />}
          {busy ? 'Refining…' : 'Refine'}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK_REFINES.map((chip) => (
          <button
            key={chip}
            type="button"
            disabled={disabled || busy}
            onClick={() => void run(chip)}
            className="rounded-pill border border-ink-hairline px-3 py-1 text-[12px] text-ink-muted transition-colors hover:border-ink/50 hover:text-ink disabled:opacity-45"
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  )
}

export default RefineBar