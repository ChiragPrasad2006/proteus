import { AlertTriangle, Check, Info, LoaderCircle, Send, Sparkles, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { DraftWarning, EmailDraft } from '@/types'

export interface DraftReviewCardProps {
  draft: EmailDraft
  messageId: string
  catalogIndex?: string
  busy?: boolean
  approving?: boolean
  revising?: boolean
  onApprove: (messageId: string, draft: EmailDraft) => void
  onSave: (messageId: string, draft: EmailDraft) => void
  onTweak: (messageId: string, text: string, draft: EmailDraft) => Promise<void>
}
const SEVERITY_STYLE: Record<DraftWarning['severity'], { ring: string; text: string; Icon: typeof Info }> = {
  info: { ring: 'border-ink/20 bg-ink/[0.03]', text: 'text-ink/70', Icon: Info },
  warning: { ring: 'border-ember-ink/50 bg-ember-ink/[0.07]', text: 'text-ember-ink', Icon: AlertTriangle },
  danger: { ring: 'border-ember-ink/70 bg-ember-ink/10', text: 'text-ember-ink', Icon: AlertTriangle },
}
function friendlyName(email: string): string { const local = email.split('@')[0] ?? email; const parts = local.split(/[._-]+/).filter(Boolean); return parts.length ? parts.map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ') : email }
const listToText = (list: unknown) => Array.isArray(list) ? list.filter((item): item is string => typeof item === 'string').join(', ') : ''
const textToList = (text: string) => text.split(',').map((value) => value.trim()).filter(Boolean)
function audienceMode(draft: EmailDraft): { label: string; detail: string } {
  if (draft.cc.length > 0) return { label: 'GROUP · CC', detail: 'Shared audience' }
  if (draft.bcc.length >= 2) return { label: 'BROADCAST · BCC', detail: 'Private recipients' }
  return { label: '1:1 · PRIVATE', detail: 'Direct audience' }
}
export function DraftReviewCard({ draft, messageId, catalogIndex = 'LETTER', busy = false, approving = false, revising = false, onApprove, onSave, onTweak }: DraftReviewCardProps) {
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
  const [localRevising, setLocalRevising] = useState(false)
  useEffect(() => { setSubject(typeof draft?.subject === 'string' ? draft.subject : ''); setBody(typeof draft?.body === 'string' ? draft.body : '') }, [draft?.id, draft?.subject, draft?.body])
  const isPendingReview = status === 'PENDING_REVIEW'
  const isSent = status === 'SENT'
  const current = useMemo<EmailDraft>(() => ({ ...draft, to: textToList(to), cc: textToList(cc), bcc: textToList(bcc), warnings, retrievedExamples, subject, body }), [draft, to, cc, bcc, subject, body, warnings, retrievedExamples])
  const firstRecipient = current.to[0] ?? 'this recipient'
  const displayName = current.to[0] ? friendlyName(current.to[0]) : 'this recipient'
  const audience = audienceMode(current)
  const handleTweak = async () => { const text = tweak.trim(); if (!text || busy || approving || revising || localRevising) return; setLocalRevising(true); try { await onTweak(messageId, text, current); setTweak('') } catch {} finally { setLocalRevising(false) } }
  return (
    <div className={cn('relative overflow-hidden rounded-sm border bg-paper text-ink', isPendingReview ? 'border-dashed border-ember' : isSent ? 'border-foam' : 'border-ink/20')}>
      <div className="flex items-center justify-between gap-3 border-b border-ink/15 px-5 py-3.5"><div className="flex items-center gap-2.5"><span className="inline-flex h-6 w-6 items-center justify-center rounded-pill bg-ink text-paper"><Send className="h-3 w-3" strokeWidth={1.8} /></span><span className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink/60">{catalogIndex} // Paper letter</span></div><div className="flex items-center gap-2"><Badge tone={isSent ? 'success' : isPendingReview ? 'warning' : 'neutral'}>{status.replace('_', ' ')}</Badge><span className="hidden font-mono text-[9px] uppercase tracking-wider text-ink/55 sm:inline">{draft.modelUsed ?? ''}</span></div></div>
      {isPendingReview ? <div className="flex items-start gap-3 border-b border-ink/15 bg-ember-ink/[0.06] px-5 py-3.5"><Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-ember-ink" strokeWidth={1.7} /><p className="text-[12.5px] leading-relaxed text-ink/75">First email to <span className="font-medium text-ink">{displayName}</span> — review or tweak before sending so Proteus learns your style for them.</p></div> : null}
      {isSent ? <div className="border-b border-ink/15 bg-foam/35 px-5 py-3 font-mono text-[9px] uppercase tracking-[0.16em] text-ink/75">Sent · edits learned into your style profile</div> : null}
      <div className="px-5 pb-1 pt-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><span className="rounded-pill border border-ink/20 px-3 py-1 font-mono text-[9px] uppercase tracking-[0.13em] text-ink/70">{audience.label}</span><span className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink/50">{audience.detail} · {draft.modelUsed || 'local model'}</span></div><Field label="To" value={to} onChange={setTo} placeholder="name@company.com" /><div className="grid gap-2.5 sm:grid-cols-2"><Field label="Cc" value={cc} onChange={setCc} placeholder="optional" /><Field label="Bcc" value={bcc} onChange={setBcc} placeholder="optional" /></div><Field label="Subject" value={subject} onChange={setSubject} placeholder="Subject line" emphasis /></div>
      <div className="px-5 pt-3"><label className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.14em] text-ink/55">Body</label><textarea value={body} onChange={(e) => setBody(e.target.value)} spellCheck={false} rows={12} className="w-full resize-y rounded-sm border border-ink/20 bg-white/35 px-4 py-3.5 font-display text-[15px] leading-relaxed text-ink placeholder:text-ink/35 focus:border-ink/50 focus:outline-none" /></div>
      {warnings.length > 0 ? <ul className="space-y-2 px-5 pt-4">{warnings.map((warning, index) => { const style = SEVERITY_STYLE[warning.severity] ?? SEVERITY_STYLE.warning; return <li key={warning.id || `warning-${index}`} className={cn('flex items-start gap-3 rounded-sm border px-4 py-3', style.ring)}><style.Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', style.text)} strokeWidth={1.8} /><div><p className={cn('text-[12px] font-medium', style.text)}>{warning.title}</p><p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/65">{warning.detail}</p></div></li> })}</ul> : null}
      <div className="px-5 pt-4"><div className="flex items-center gap-2 rounded-pill border border-ink/20 bg-white/25 py-1.5 pl-3.5 pr-1.5 focus-within:border-ink/50"><Wand2 className="h-3.5 w-3.5 shrink-0 text-ember-ink" strokeWidth={1.7} /><input value={tweak} disabled={busy || approving || revising || localRevising || isSent} onChange={(e) => setTweak(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void handleTweak() } }} placeholder={localRevising || revising ? 'Revising…' : 'Suggest a tweak to Proteus…'} className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink placeholder:text-ink/40 focus:outline-none" /><Button size="sm" variant="secondary" onClick={() => void handleTweak()} disabled={!tweak.trim() || busy || approving || revising || localRevising || isSent} className="bg-ink text-paper hover:bg-cobalt-deep">{localRevising || revising ? <><LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />Revising…</> : 'Send'}</Button></div></div>
      <div className="flex flex-wrap items-center gap-3 px-5 pb-6 pt-5"><Button size="md" disabled={busy || approving || revising || localRevising || isSent} onClick={() => onApprove(messageId, current)} leftIcon={approving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}>{isSent ? 'Sent ✓' : approving ? 'Sending…' : 'Approve & Send Now'}</Button><Button size="md" variant="outline" className="border-ink/25 text-ink hover:border-ink/55 hover:bg-ink/5" disabled={busy || isSent} onClick={() => { onSave(messageId, current); setSaved(true) }} leftIcon={saved ? <Check className="h-4 w-4 text-foam" /> : undefined}>{saved ? 'Draft saved' : 'Save Draft'}</Button><span className="ml-auto hidden font-mono text-[9px] uppercase tracking-[0.14em] text-ink/55 sm:inline">{firstRecipient}</span></div>
      <div className="border-t border-ink/15 bg-ink/[0.035] px-5 py-2 font-mono text-[8.5px] uppercase tracking-[0.14em] text-ink/50">THINK=OFF · DRAFT / THINK=ON · LEARN · read-only runtime metadata</div>
    </div>
  )
}
interface FieldProps { label: string; value: string; onChange: (value: string) => void; placeholder?: string; emphasis?: boolean }
function Field({ label, value, onChange, placeholder, emphasis }: FieldProps) {
  return <label className="flex items-center gap-3 rounded-sm border border-ink/15 bg-white/25 px-4 py-2.5 focus-within:border-ink/45"><span className="w-14 shrink-0 font-mono text-[9px] uppercase tracking-[0.14em] text-ink/55">{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cn('min-w-0 flex-1 bg-transparent text-ink placeholder:text-ink/35 focus:outline-none', emphasis ? 'text-[14px] font-medium' : 'text-[12.5px]')} /></label>
}
export default DraftReviewCard
