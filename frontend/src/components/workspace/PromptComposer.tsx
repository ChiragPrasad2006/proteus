import { ArrowUp, Lock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export interface PromptComposerProps { busy?: boolean; voiceLabel?: string; onSend: (text: string) => void; autoFocus?: boolean }
const MAX_HEIGHT = 200
export function PromptComposer({ busy = false, voiceLabel = 'Qwen3:8B · Voice locked', onSend, autoFocus = false }: PromptComposerProps) {
  const [value, setValue] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { const el = taRef.current; if (!el) return; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px` }, [value])
  const submit = () => { const text = value.trim(); if (!text || busy) return; onSend(text); setValue('') }
  return (
    <div className="border-t border-hairline bg-cobalt-deep px-4 py-4 lg:px-5">
      <div className="mx-auto max-w-3xl">
        <div className="group flex items-end gap-2 rounded-pill border border-hairline bg-cobalt px-3 py-2.5 transition-colors focus-within:border-foam/70">
          <textarea ref={taRef} value={value} autoFocus={autoFocus} rows={1} disabled={busy} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} placeholder="Ask Proteus to draft or send an email…" className="min-h-[2.25rem] max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[14px] leading-relaxed text-paper placeholder:text-paper-label focus:outline-none disabled:opacity-50" />
          <button type="button" onClick={submit} disabled={busy || !value.trim()} aria-label="Send" className={cn('mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill bg-paper text-ink transition-transform hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-40') }><ArrowUp className="h-4 w-4" strokeWidth={2.2} /></button>
        </div>
        <div className="mt-2.5 flex items-center justify-between gap-3 px-1.5"><span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-paper-label"><Lock className="h-3 w-3 text-foam" />{voiceLabel}</span><span className="hidden font-mono text-[9px] uppercase tracking-[0.1em] text-paper-label sm:inline">Enter to send · Shift+Enter for a new line</span></div>
      </div>
    </div>
  )
}
export default PromptComposer
