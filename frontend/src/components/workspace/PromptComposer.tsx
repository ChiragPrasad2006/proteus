import { ArrowUp, Lock, Paperclip } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export interface PromptComposerProps {
  /** Disables input + send while the agent is working. */
  busy?: boolean
  /** Active voice-profile badge, e.g. "Qwen3:8B · Voice locked". */
  voiceLabel?: string
  onSend: (text: string) => void
  autoFocus?: boolean
}

const MAX_HEIGHT = 200

/** Floating composer: auto-growing textarea, decorative attach, circular send. */
export function PromptComposer({
  busy = false,
  voiceLabel = 'Qwen3:8B · Voice locked',
  onSend,
  autoFocus = false,
}: PromptComposerProps) {
  const [value, setValue] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)

  // Auto-grow up to a cap.
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    onSend(text)
    setValue('')
  }

  return (
    <div className="border-t border-hairline bg-ink/70 px-4 py-4 backdrop-blur-xl lg:px-8">
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            'group flex items-end gap-2 rounded-[26px] border border-hairline bg-surface px-3 py-2.5',
            'transition-colors duration-300 ease-proteus focus-within:border-accent/60',
          )}
        >
          {/* Decorative attachment */}
          <button
            type="button"
            tabIndex={-1}
            aria-label="Attach a file (coming soon)"
            className="mb-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors duration-300 ease-proteus hover:bg-white/[0.06] hover:text-fg-muted"
          >
            <Paperclip className="h-4 w-4" strokeWidth={1.7} />
          </button>

          <textarea
            ref={taRef}
            value={value}
            autoFocus={autoFocus}
            rows={1}
            disabled={busy}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder="Ask Proteus to draft or send an email (e.g., 'Email Manu and CC Jatin & Chiranth about…')"
            className={cn(
              'min-h-[2.25rem] max-h-[200px] flex-1 resize-none bg-transparent py-1.5',
              'text-[14px] leading-relaxed text-fg placeholder:text-fg-faint',
              'focus:outline-none disabled:opacity-50',
            )}
          />

          <button
            type="button"
            onClick={submit}
            disabled={busy || !value.trim()}
            aria-label="Send"
            className={cn(
              'mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
              'bg-accent text-ink transition-all duration-300 ease-proteus',
              'hover:bg-accent-dim active:scale-95',
              'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent',
            )}
          >
            <ArrowUp className="h-4.5 w-4.5" strokeWidth={2.2} />
          </button>
        </div>

        <div className="mt-2.5 flex items-center justify-between gap-3 px-1.5">
          <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.16em] text-fg-faint">
            <Lock className="h-3 w-3 text-accent/70" strokeWidth={1.7} />
            {voiceLabel}
          </span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint sm:inline">
            Enter to send · Shift+Enter for a new line
          </span>
        </div>
      </div>
    </div>
  )
}

export default PromptComposer
