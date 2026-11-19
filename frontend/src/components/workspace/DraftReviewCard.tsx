import { AlertTriangle, Check, Info, Send, Sparkles, Wand2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { DraftWarning, EmailDraft } from '@/types'

export interface DraftReviewCardProps {
  draft: EmailDraft
  /** Id of the parent chat message — passed through to the callbacks. */
  messageId: string
  /** Mono catalog tag shown in the header, e.g. "FIG.03". */
  catalogIndex?: string
  busy?: boolean
  onApprove: (messageId: string, draft: EmailDraft) => void
  onSave: (messageId: string, draft: EmailDraft) => void
  onTweak: (messageId: string, text: string) => void
}

const SEVERITY_STYLE: Record<DraftWarning['severity'], { ring: string; text: string; Icon: typeof Info }> = {
  info: { ring: 'border-hairline bg-white/[0.03]', text: 'text-fg-muted', Icon: Info },
  warning: { ring: 'border-[#92400e]/50 bg-[#f59e0b]/[0.07]', text: 'text-[#fbbf24]', Icon: AlertTriangle },
  danger: { ring: 'border-[#7f1d1d]/60 bg-[#ef4444]/[0.08]', text: 'text-[#fca5a5]', Icon: AlertTriangle },
}

/** "daniel.reyes@acme.com" → "Daniel Reyes"; falls back to the raw address. */
function friendlyName(email: string): string {
  const local = email.split('@')[0] ?? email
  const parts = local.split(/[._-]+/).filter(Boolean)
  if (parts.length === 0) return email
  return parts
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ')
}

const listToText = (list: unknown) => Array.isArray(list)
  ? list.filter((item): item is string => typeof item === 'string').join(', ')
  : ''
const textToList = (text: string) =>
  text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

/**
 * Interactive first-recipient review gate. Editable envelope + body, a
 * "suggest a tweak" channel back to the agent, and the explicit approve action.
 */
export function DraftReviewCard({
  draft,
  messageId,
  catalogIndex = 'FIG.03',
  busy = false,
  onApprove,
  onSave,
  onTweak,
}: DraftReviewCardProps) {
  const warnings = Array.isArray(draft?.warnings) ? draft.warnings : []
  const status = typeof draft?.status === 'string' ? draft.status : 'DRAFT'
  const retrievedExamples = Array.isArray(draft?.retrievedExamples) ? draft.retrievedExamples : []
  const [to, setTo] = useState(listToText(draft?.to))
  const [cc, setCc] = useState(listToText(draft?.cc))
  const [bcc, setBcc] = useState(listToText(draft?.bcc))
  const [subject, setSubject] = useState(typeof draft?.subject === 'string' ? draft.subject : '')
  const [body, setBody] = useState(typeof draft?.body === 'string' ? draft.body : '')
  const [tweak, setTweak] = useState('')
  const [saved, setSaved] = useState(false)

  // Initialised once per draft identity — the thread keys this card by draft.id
  // so a fresh draft remounts with a clean editable copy (no effect needed).

  const isPendingReview = status === 'PENDING_REVIEW'
  const isSent = status === 'SENT'

  const current = useMemo<EmailDraft>(
    () => ({
      ...draft,
      to: textToList(to),
      cc: textToList(cc),
      bcc: textToList(bcc),
      warnings,
      retrievedExamples,
      subject,
      body,
    }),
    [draft, to, cc, bcc, subject, body],
  )

  const firstRecipient = current.to[0] ?? 'this recipient'
  const displayName = current.to[0] ? friendlyName(current.to[0]) : 'this recipient'

  const handleTweak = () => {
    const text = tweak.trim()
    if (!text) return
    onTweak(messageId, text)
    setTweak('')
  }

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-3xl border border-hairline bg-surface',
        'shadow-[0_40px_90px_-60px_rgba(0,0,0,0.9)]',
      )}
    >
      {/* Left accent rule */}
      <span aria-hidden className="absolute inset-y-0 left-0 w-1 bg-accent" />

      {/* Header — serrated top edge with the catalog tag */}
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3.5 pl-6">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent/15">
            <Send className="h-3 w-3 text-accent" strokeWidth={1.8} />
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
            {catalogIndex} // Draft review
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={isSent ? 'success' : isPendingReview ? 'warning' : 'neutral'}>
            {status.replace('_', ' ')}
          </Badge>
          <span className="hidden font-mono text-[10px] uppercase tracking-wider text-fg-faint sm:inline">
            {draft.modelUsed ?? ''}
          </span>
        </div>
      </div>

      {/* Review banner */}
      {isPendingReview ? (
        <div className="flex items-start gap-3 border-b border-hairline bg-accent/[0.06] px-6 py-3.5">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" strokeWidth={1.7} />
          <p className="text-[13px] leading-relaxed text-fg-muted">
            First email to{' '}
            <span className="font-medium text-fg">{displayName}</span> — review or tweak
            before sending so Proteus learns your style for them.
          </p>
        </div>
      ) : null}

      {/* Envelope */}
      <div className="space-y-2.5 px-6 pb-1 pt-5">
        <Field label="To" value={to} onChange={setTo} placeholder="name@company.com" />
        <div className="grid gap-2.5 sm:grid-cols-2">
          <Field label="Cc" value={cc} onChange={setCc} placeholder="optional" />
          <Field label="Bcc" value={bcc} onChange={setBcc} placeholder="optional" />
        </div>
        <Field
          label="Subject"
          value={subject}
          onChange={setSubject}
          placeholder="Subject line"
          emphasis
        />
      </div>

      {/* Body */}
      <div className="px-6 pt-3">
        <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          Body
        </label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          spellCheck={false}
          rows={12}
          className={cn(
            'w-full resize-y rounded-2xl border border-hairline bg-ink/50 px-4 py-3.5',
            'text-[13.5px] leading-relaxed text-fg placeholder:text-fg-faint',
            'focus:border-accent/60 focus:outline-none',
          )}
        />
      </div>

      {/* Warnings */}
      {warnings.length > 0 ? (
        <ul className="space-y-2 px-6 pt-4">
          {warnings.map((w, index) => {
            const s = SEVERITY_STYLE[w.severity] ?? SEVERITY_STYLE.warning
            return (
              <li
                key={w.id || `warning-${index}`}
                className={cn('flex items-start gap-3 rounded-2xl border px-4 py-3', s.ring)}
              >
                <s.Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', s.text)} strokeWidth={1.8} />
                <div>
                  <p className={cn('text-[12.5px] font-medium', s.text)}>{w.title}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-fg-muted">{w.detail}</p>
                </div>
              </li>
            )
          })}
        </ul>
      ) : null}

      {/* Suggest a tweak */}
      <div className="px-6 pt-4">
        <div className="flex items-center gap-2 rounded-full border border-hairline bg-elevated/50 py-1.5 pl-3.5 pr-1.5 focus-within:border-accent/60">
          <Wand2 className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={1.7} />
          <input
            value={tweak}
            onChange={(e) => setTweak(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleTweak()
              }
            }}
            placeholder="Suggest a tweak to Proteus…"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-fg placeholder:text-fg-faint focus:outline-none"
          />
          <Button size="sm" variant="ghost" onClick={handleTweak} disabled={!tweak.trim() || busy}>
            Send
          </Button>
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3 px-6 pb-6 pt-5">
        <Button
          size="md"
          disabled={busy || isSent}
          onClick={() => onApprove(messageId, current)}
          leftIcon={<Send className="h-4 w-4" />}
        >
          {isSent ? 'Sent' : 'Approve & Send Now'}
        </Button>
        <Button
          size="md"
          variant="ghost"
          disabled={busy || isSent}
          onClick={() => {
            onSave(messageId, current)
            setSaved(true)
          }}
          leftIcon={saved ? <Check className="h-4 w-4 text-accent" /> : undefined}
        >
          {saved ? 'Draft saved' : 'Save Draft'}
        </Button>

        <span className="ml-auto hidden font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint sm:inline">
          {firstRecipient}
        </span>
      </div>
    </div>
  )
}

interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  emphasis?: boolean
}

function Field({ label, value, onChange, placeholder, emphasis }: FieldProps) {
  return (
    <label className="flex items-center gap-3 rounded-2xl border border-hairline bg-ink/40 px-4 py-2.5 focus-within:border-accent/60">
      <span className="w-14 shrink-0 font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
        {label}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          'min-w-0 flex-1 bg-transparent text-fg placeholder:text-fg-faint focus:outline-none',
          emphasis ? 'text-[14px] font-medium' : 'text-[13px]',
        )}
      />
    </label>
  )
}

export default DraftReviewCard
