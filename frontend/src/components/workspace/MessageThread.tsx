import { Sparkles } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { ResolvedContactsStrip } from '@/components/workspace/ResolvedContactsStrip'
import { Avatar } from '@/components/ui/Avatar'
import { formatClock } from '@/lib/format'
import { cn, initialsFrom } from '@/lib/utils'
import type { ChatMessage, EmailDraft } from '@/types'

export interface MessageThreadProps {
  messages: ChatMessage[]
  busy?: boolean
  approving?: boolean
  revising?: boolean
  onResolve: (messageId: string, name: string, email: string) => void
  onApprove?: (messageId: string, draft: EmailDraft) => void
  onSave?: (messageId: string, draft: EmailDraft) => void
  onTweak?: (messageId: string, text: string, draft: EmailDraft) => Promise<void>
  hideDraftCards?: boolean
  onSelectDraft?: (draftId: string) => void
}
function ProteusMonogram({ className }: { className?: string }) {
  return <span className={cn('inline-flex shrink-0 items-center justify-center rounded-pill border border-hairline bg-cobalt', className)} aria-hidden><img src="/art/proteus-face.webp" alt="" className="engraving-multiply h-full w-full rounded-pill object-cover" /></span>
}
export function MessageThread({ messages, busy = false, onResolve, hideDraftCards = false, onSelectDraft }: MessageThreadProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const safeMessages = Array.isArray(messages) ? messages : []
  const last = safeMessages[safeMessages.length - 1]
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [safeMessages.length, last?.id, last?.content, last?.draft?.id])
  if (safeMessages.length === 0) return <div className="flex flex-1 items-center justify-center px-6"><div className="flex max-w-sm flex-col items-center text-center"><img src="/art/proteus-tree.webp" alt="Proteus holding a tree in the engraving" className="engraving-multiply mb-5 h-28 w-24 object-contain opacity-80" /><h2 className="font-display text-2xl tracking-tight text-paper">Chat with your email brain.</h2><p className="mt-2.5 text-[13px] leading-relaxed text-paper-muted">Brief Proteus on who you’re writing to and what needs to land. It resolves contacts and matches your local voice.</p></div></div>
  return <div className="scrollbar-none flex-1 overflow-y-auto"><div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-8 lg:px-7">{safeMessages.map((message) => {
    const reasoning = Array.isArray(message.reasoning) ? message.reasoning : []
    const contacts = Array.isArray(message.contacts) ? message.contacts : []
    const clarificationCandidates = Array.isArray(message.clarification?.candidates) ? message.clarification.candidates : []
    if (message.role === 'user') return <div key={message.id} className="flex justify-end"><div className="flex max-w-[85%] flex-col items-end gap-1.5 sm:max-w-[75%]"><div className="rounded-sm border border-hairline bg-paper px-4 py-3 text-[13.5px] leading-relaxed text-ink">{message.content}</div><span className="pr-1 font-mono text-[9px] uppercase tracking-wider text-paper-label">{formatClock(message.createdAt)}</span></div></div>
    const needsClarification = message.status === 'NEEDS_CLARIFICATION' || Boolean(message.clarification)
    return <div key={message.id} className="flex gap-3"><ProteusMonogram className="mt-0.5 h-8 w-8" /><div className="flex min-w-0 flex-1 flex-col gap-3"><div className="max-w-[92%] rounded-sm border border-hairline bg-cobalt px-4 py-3 sm:max-w-[88%]"><p className="font-display text-[16px] leading-relaxed text-paper">{message.content}</p></div>{reasoning.length > 0 ? <ul className="flex flex-col gap-1.5 rounded-sm border border-hairline bg-cobalt/60 px-4 py-3">{reasoning.map((step, index) => <li key={index} className="flex items-start gap-2 font-mono text-[9.5px] leading-relaxed text-paper-label"><span className="mt-1 h-1 w-1 shrink-0 rounded-pill bg-foam" />{step}</li>)}</ul> : null}{needsClarification && message.clarification ? <div className="rounded-sm border border-ember/60 bg-ember/10 p-3.5"><div className="mb-3 flex items-center gap-2"><Sparkles className="h-3.5 w-3.5 text-ember" strokeWidth={1.7} /><span className="font-mono text-[9px] uppercase tracking-[0.18em] text-ember">Which one did you mean?</span></div><p className="mb-3 text-[13px] leading-relaxed text-paper-muted">{message.clarification?.prompt ?? ''}</p><ul className="flex flex-col gap-1.5">{clarificationCandidates.map((contact) => <li key={contact.id}><button type="button" onClick={() => onResolve(message.id, contact.name, contact.email)} className="flex w-full items-center gap-3 rounded-sm border border-hairline bg-cobalt px-3 py-2.5 text-left transition-colors hover:border-foam/60 hover:bg-foam/10"><Avatar initials={initialsFrom(contact.name)} size="sm" /><span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-paper">{contact.name}</span><span className="block truncate font-mono text-[9.5px] text-paper-label">{contact.email}</span></span><span className="shrink-0 font-mono text-[9px] text-paper-label">{contact.relationship} · {Math.round(contact.confidence * 100)}%</span></button></li>)}</ul></div> : null}{contacts.length > 0 ? <ResolvedContactsStrip contacts={contacts} /> : null}{message.draft && !hideDraftCards ? <button type="button" onClick={() => onSelectDraft?.(message.draft!.id)} className="w-fit rounded-pill border border-hairline px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.14em] text-paper-label hover:border-foam/60 hover:text-foam">Open paper letter · {message.draft.status.replace('_', ' ')}</button> : null}<span className="pl-1 font-mono text-[9px] uppercase tracking-wider text-paper-label">{formatClock(message.createdAt)}</span></div></div>
  })}{busy ? <div className="flex items-center gap-3"><ProteusMonogram className="h-8 w-8" /><span className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-cobalt px-3.5 py-2">{[0,1,2].map((index) => <span key={index} className="h-1.5 w-1.5 animate-pulse rounded-pill bg-foam" style={{ animationDelay: `${index * 140}ms` }} />)}<span className="ml-1 font-mono text-[9px] uppercase tracking-[0.16em] text-paper-label">drafting</span></span></div> : null}<div ref={endRef} /></div></div>
}
export default MessageThread
