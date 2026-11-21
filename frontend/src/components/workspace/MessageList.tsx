import { Copy, CornerUpLeft, PencilLine, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ActionCard } from '@/components/workspace/ActionCard'
import { formatClock } from '@/lib/format'
import { cleanAssistantContent } from '@/lib/status'
import { cn, isValidEmail } from '@/lib/utils'
import { useDraftState } from '@/hooks/useDraftState'
import { toast } from '@/stores/useToastStore'
import type { ChatMessage, RecipientContact } from '@/types'

export interface MessageListProps {
  messages: ChatMessage[]
  busy: boolean
  onCancel: () => void
  /** Send a chat turn (clarification answers, regenerate, edit & resend). */
  onSendText: (text: string) => void
  onSelectDraft: (draftId: string) => void
  onEditResend: (text: string) => void
}

function ProteusFace({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center overflow-hidden rounded-pill border border-hairline bg-cobalt', className)} aria-hidden>
      <img src="/art/proteus-face.webp" alt="" className="engraving-multiply h-full w-full object-cover" />
    </span>
  )
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast('Copied to clipboard.')
  } catch {
    toast('Could not copy — select the text manually.', 'warning')
  }
}

function HoverAction({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-pill border border-hairline px-2.5 py-1 font-mono text-[12px] text-paper-muted transition-colors hover:border-paper-label hover:text-paper"
    >
      {children}
      {label}
    </button>
  )
}

function ClarificationCard({ message, onSendText }: { message: ChatMessage; onSendText: (text: string) => void }) {
  const [email, setEmail] = useState('')
  const [invalid, setInvalid] = useState(false)
  const candidates = message.clarification?.candidates ?? []
  const save = () => {
    const trimmed = email.trim()
    if (!isValidEmail(trimmed)) { setInvalid(true); return }
    setInvalid(false)
    onSendText(trimmed)
    setEmail('')
  }
  return (
    <div className="on-paper rounded-card border border-ember-ink/50 bg-paper p-4 text-ink">
      <p className="flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.12em] text-ember-ink">
        <Sparkles className="h-3.5 w-3.5" aria-hidden />
        Which one did you mean?
      </p>
      <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-muted">{message.clarification?.prompt ?? message.content}</p>
      {candidates.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {candidates.map((contact: RecipientContact) => (
            <li key={contact.id}>
              <button
                type="button"
                onClick={() => onSendText(`Use ${contact.name} <${contact.email}>`)}
                className="flex w-full items-baseline justify-between gap-3 rounded-card border border-ink-hairline px-3 py-2 text-left transition-colors hover:border-ink/50 hover:bg-ink/5"
              >
                <span className="truncate text-[13px] font-medium">{contact.name}</span>
                <span className="shrink-0 font-mono text-[12px] text-ink-muted">{contact.email}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-3 flex items-center gap-2">
        <input
          value={email}
          onChange={(event) => { setEmail(event.target.value); setInvalid(false) }}
          onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); save() } }}
          placeholder="Enter email address…"
          aria-label="Recipient email address"
          aria-invalid={invalid}
          className={cn('min-w-0 flex-1 rounded-card border bg-white/40 px-3 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none', invalid ? 'border-ember-ink' : 'border-ink-hairline focus:border-ink/60')}
        />
        <button type="button" onClick={save} className="shrink-0 rounded-pill bg-ink px-4 py-2 text-[12px] font-medium text-paper transition-colors hover:bg-send-hover">
          Save &amp; draft
        </button>
      </div>
      {invalid ? <p className="mt-1.5 text-[12px] text-ember-ink">That doesn’t look like an email address yet.</p> : null}
    </div>
  )
}

function ThinkingState({ onCancel }: { onCancel: () => void }) {
  return (
    <div className="flex gap-3" role="status" aria-live="polite">
      <ProteusFace className="mt-0.5 h-8 w-8" />
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div className="space-y-2" aria-hidden>
          <div className="shimmer-line h-3 w-3/4 rounded-pill" />
          <div className="shimmer-line h-3 w-1/2 rounded-pill" />
        </div>
        <div className="flex items-center gap-3">
          <span className="font-display text-[15px] italic text-paper-muted">Drafting in your voice…</span>
          <button type="button" onClick={onCancel} className="rounded-pill border border-hairline px-3 py-1 font-mono text-[12px] text-paper-muted transition-colors hover:border-paper-label hover:text-paper">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

export function MessageList({ messages, busy, onCancel, onSendText, onSelectDraft, onEditResend }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const drafts = useDraftState((state) => state.drafts)
  const last = messages[messages.length - 1]
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, last?.id, last?.content, busy])

  return (
    <div className="scrollbar-none flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[720px] flex-col gap-7 px-4 py-8 lg:px-6">
        {messages.map((message, index) => {
          if (message.role === 'user') {
            return (
              <div key={message.id} className="group flex flex-col items-end gap-1.5">
                <div className="max-w-[85%] rounded-card border border-ink-hairline bg-paper px-4 py-3 text-[13.5px] leading-relaxed text-ink sm:max-w-[75%]">
                  {message.content}
                </div>
                <div className="flex items-center gap-2 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  <span className="font-mono text-[12px] text-paper-muted">{formatClock(message.createdAt)}</span>
                  <HoverAction label="Copy" onClick={() => void copyText(message.content)}><Copy className="h-3 w-3" aria-hidden /></HoverAction>
                  <HoverAction label="Edit & resend" onClick={() => onEditResend(message.content)}><PencilLine className="h-3 w-3" aria-hidden /></HoverAction>
                </div>
              </div>
            )
          }

          const isClarification = message.status === 'NEEDS_CLARIFICATION' || Boolean(message.clarification)
          const draft = message.draftId ? drafts[message.draftId] : undefined
          const content = draft ? cleanAssistantContent(message.content, draft.to) : message.content
          const previousUser = [...messages.slice(0, index)].reverse().find((item) => item.role === 'user')

          return (
            <div key={message.id} className="group flex gap-3">
              <ProteusFace className="mt-0.5 h-8 w-8" />
              <div className="flex min-w-0 flex-1 flex-col gap-3">
                {isClarification ? (
                  <ClarificationCard message={message} onSendText={onSendText} />
                ) : (
                  <>
                    <p className="max-w-[92%] whitespace-pre-wrap font-display text-[16px] leading-relaxed text-paper">{content}</p>
                    <div className="flex items-center gap-2 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                      <span className="font-mono text-[12px] text-paper-muted">{formatClock(message.createdAt)}</span>
                      <HoverAction label="Copy" onClick={() => void copyText(content)}><Copy className="h-3 w-3" aria-hidden /></HoverAction>
                      {previousUser ? (
                        <HoverAction label="Regenerate" onClick={() => onSendText(previousUser.content)}><RefreshCw className="h-3 w-3" aria-hidden /></HoverAction>
                      ) : null}
                      {message.draftId ? (
                        <HoverAction label="Focus draft" onClick={() => onSelectDraft(message.draftId!)}><CornerUpLeft className="h-3 w-3" aria-hidden /></HoverAction>
                      ) : null}
                    </div>
                  </>
                )}
                {message.draftId ? <ActionCard draftId={message.draftId} onSelect={onSelectDraft} /> : null}
              </div>
            </div>
          )
        })}
        {busy ? <ThinkingState onCancel={onCancel} /> : null}
        <div ref={endRef} />
      </div>
    </div>
  )
}

export default MessageList