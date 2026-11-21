import { ArrowUp } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useDraftState, useSelectedDraft } from '@/hooks/useDraftState'
import { cn } from '@/lib/utils'
import { useComposerBus } from '@/stores/useComposerBus'
import type { RecipientContact } from '@/types'

export interface ComposerProps {
  busy: boolean
  onSend: (text: string) => void
  contacts: RecipientContact[]
  autoFocus?: boolean
}

const MAX_HEIGHT = 192 // ~8 lines

const MACROS = [
  { token: '/formal', label: 'Formal tone', instruction: 'Write this in a formal, professional tone.' },
  { token: '/casual', label: 'Casual tone', instruction: 'Write this in a relaxed, casual tone.' },
  { token: '/shorter', label: 'Shorter', instruction: 'Keep this short and to the point.' },
  { token: '/followup', label: 'Follow-up', instruction: 'Write this as a polite follow-up to my previous email.' },
] as const

/**
 * Chat composer: auto-growing textarea, Enter sends / Shift+Enter newline,
 * `@` contact autocomplete and `/` quick-macro menu.
 */
export function Composer({ busy, onSend, contacts, autoFocus = false }: ComposerProps) {
  const [value, setValue] = useState('')
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionIndex, setMentionIndex] = useState(0)
  const [macroIndex, setMacroIndex] = useState(0)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const request = useComposerBus((state) => state.request)
  const consume = useComposerBus((state) => state.consume)
  const refine = useDraftState((state) => state.refine)
  const activeDraft = useSelectedDraft()

  // Consume cross-component insert requests (chips, pills, edit & resend).
  // Render-phase adjustment (previous-value-in-state) avoids cascading effects.
  const [consumedNonce, setConsumedNonce] = useState(0)
  if (request && request.nonce !== consumedNonce) {
    setConsumedNonce(request.nonce)
    const incoming = request
    setValue((current) => incoming.mode === 'append' ? `${current}${current && !current.endsWith(' ') ? ' ' : ''}${incoming.text}` : incoming.text)
  }
  useEffect(() => {
    if (!request) return
    taRef.current?.focus()
    consume(request.nonce)
  }, [request, consume])

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  // `@mention` query = text after the last '@' that starts a word.
  const mentionQuery = useMemo(() => {
    const match = /(?:^|\s)@([\w.-]*)$/.exec(value)
    return match ? match[1]! : null
  }, [value])

  const mentionSuggestions = useMemo(() => {
    if (mentionQuery === null) return []
    const query = mentionQuery.toLowerCase()
    return contacts
      .filter((contact) => !query || contact.name.toLowerCase().includes(query) || contact.email.toLowerCase().includes(query))
      .slice(0, 6)
  }, [mentionQuery, contacts])

  const macroMatches = useMemo(() => {
    if (!value.startsWith('/')) return []
    const query = value.toLowerCase()
    return MACROS.filter((macro) => macro.token.startsWith(query))
  }, [value])

  const macroOpen = macroMatches.length > 0 && !value.includes(' ')
  const mentionVisible = mentionOpen && mentionQuery !== null && mentionSuggestions.length > 0

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    onSend(text)
    setValue('')
    setMentionOpen(false)
  }

  const insertMention = (contact: RecipientContact) => {
    setValue((current) => current.replace(/@([\w.-]*)$/, `${contact.name} <${contact.email}> `))
    setMentionOpen(false)
    taRef.current?.focus()
  }

  const applyMacro = (macro: typeof MACROS[number]) => {
    const draftEditable = activeDraft && activeDraft.status !== 'sent' && activeDraft.status !== 'sending' && activeDraft.status !== 'sending_countdown'
    if (draftEditable) {
      // Tweak the open draft instead of starting a new chat turn.
      void refine(activeDraft.id, macro.instruction)
      setValue('')
    } else {
      setValue(`${macro.instruction} `)
    }
    taRef.current?.focus()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionVisible) {
      if (event.key === 'ArrowDown') { event.preventDefault(); setMentionIndex((index) => (index + 1) % mentionSuggestions.length); return }
      if (event.key === 'ArrowUp') { event.preventDefault(); setMentionIndex((index) => (index - 1 + mentionSuggestions.length) % mentionSuggestions.length); return }
      if (event.key === 'Enter' || event.key === 'Tab') { event.preventDefault(); insertMention(mentionSuggestions[mentionIndex] ?? mentionSuggestions[0]!); return }
      if (event.key === 'Escape') { event.preventDefault(); setMentionOpen(false); return }
    }
    if (macroOpen) {
      if (event.key === 'ArrowDown') { event.preventDefault(); setMacroIndex((index) => (index + 1) % macroMatches.length); return }
      if (event.key === 'ArrowUp') { event.preventDefault(); setMacroIndex((index) => (index - 1 + macroMatches.length) % macroMatches.length); return }
      if (event.key === 'Enter' || event.key === 'Tab') { event.preventDefault(); applyMacro(macroMatches[macroIndex] ?? macroMatches[0]!); return }
      if (event.key === 'Escape') { event.preventDefault(); setValue(''); return }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-hairline bg-cobalt px-4 pb-3 pt-3 lg:px-6" data-tour="composer">
      <div className="relative mx-auto w-full max-w-[720px]">
        {mentionVisible ? (
          <ul role="listbox" aria-label="Contact suggestions" className="absolute bottom-[calc(100%+8px)] left-0 right-0 z-30 max-h-56 overflow-y-auto rounded-card border border-hairline bg-cobalt-deep">
            {mentionSuggestions.map((contact, index) => (
              <li key={contact.id} role="option" aria-selected={index === mentionIndex}>
                <button
                  type="button"
                  onMouseDown={(event) => { event.preventDefault(); insertMention(contact) }}
                  onMouseEnter={() => setMentionIndex(index)}
                  className={cn('flex w-full items-baseline justify-between gap-3 px-3.5 py-2 text-left', index === mentionIndex ? 'bg-paper/10' : 'hover:bg-paper/5')}
                >
                  <span className="truncate text-[13px] text-paper">{contact.name}</span>
                  <span className="shrink-0 font-mono text-[12px] text-paper-muted">{contact.email}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {macroOpen ? (
          <ul role="listbox" aria-label="Quick macros" className="absolute bottom-[calc(100%+8px)] left-0 right-0 z-30 overflow-hidden rounded-card border border-hairline bg-cobalt-deep">
            {macroMatches.map((macro, index) => (
              <li key={macro.token} role="option" aria-selected={index === macroIndex}>
                <button
                  type="button"
                  onMouseDown={(event) => { event.preventDefault(); applyMacro(macro) }}
                  onMouseEnter={() => setMacroIndex(index)}
                  className={cn('flex w-full items-baseline gap-3 px-3.5 py-2 text-left', index === macroIndex ? 'bg-paper/10' : 'hover:bg-paper/5')}
                >
                  <span className="font-mono text-[12px] text-foam">{macro.token}</span>
                  <span className="text-[12px] text-paper-muted">{macro.label}{activeDraft ? ' · applies to the open draft' : ''}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex items-end gap-2 rounded-card border border-hairline bg-cobalt-deep px-3 py-2.5 transition-colors focus-within:border-foam/70">
          <textarea
            ref={taRef}
            value={value}
            autoFocus={autoFocus}
            rows={1}
            disabled={busy}
            onChange={(event) => { setValue(event.target.value); setMentionOpen(true); setMentionIndex(0); setMacroIndex(0) }}
            onKeyDown={handleKeyDown}
            placeholder="Ask Proteus to draft an email… (@ for contacts, / for tone)"
            aria-label="Message Proteus"
            className="max-h-[192px] min-h-[2.25rem] flex-1 resize-none bg-transparent py-1.5 text-[14px] leading-relaxed text-paper placeholder:text-paper-muted focus:outline-none disabled:opacity-50"
          />
          <button
            type="button"
            onClick={submit}
            disabled={busy || !value.trim()}
            aria-label="Send message"
            className="mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-pill bg-paper text-ink transition-colors hover:bg-foam disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ArrowUp className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          </button>
        </div>
        <p className="mt-2 px-1 font-mono text-[12px] text-paper-muted">
          Enter to send · Shift+Enter for new line · Runs locally on your device
        </p>
      </div>
    </div>
  )
}

export default Composer