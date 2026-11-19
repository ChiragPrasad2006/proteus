import { Aperture, Sparkles } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { DraftReviewCard } from '@/components/workspace/DraftReviewCard'
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
  onApprove: (messageId: string, draft: EmailDraft) => void
  onSave: (messageId: string, draft: EmailDraft) => void
  onTweak: (messageId: string, text: string, draft: EmailDraft) => Promise<void>
}

function ProteusMonogram({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full border border-hairline bg-elevated/60',
        className,
      )}
      aria-hidden
    >
      <Aperture className="h-4 w-4 text-accent" strokeWidth={1.4} />
    </span>
  )
}

export function MessageThread({
  messages,
  busy = false,
  approving = false,
  revising = false,
  onResolve,
  onApprove,
  onSave,
  onTweak,
}: MessageThreadProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const safeMessages = Array.isArray(messages) ? messages : []
  const last = safeMessages[safeMessages.length - 1]

  // Pin to the newest content whenever the thread grows or an assistant turn settles.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [safeMessages.length, last?.id, last?.content, last?.draft?.id])

  if (safeMessages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6">
        <div className="flex max-w-sm flex-col items-center text-center">
          <span className="mb-5 inline-flex h-14 w-14 items-center justify-center rounded-full border border-hairline bg-elevated/50">
            <Aperture className="h-7 w-7 text-accent" strokeWidth={1.3} />
          </span>
          <h2 className="font-display text-2xl tracking-tight text-fg">
            Ask Proteus to draft or send an email
          </h2>
          <p className="mt-2.5 text-[13.5px] leading-relaxed text-fg-muted">
            Brief it on who you're writing to and what needs to land. It resolves contacts
            and matches your voice from the local corpus.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="scrollbar-none flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-8 lg:px-8">
        {safeMessages.map((message) => {
          const reasoning = Array.isArray(message.reasoning) ? message.reasoning : []
          const contacts = Array.isArray(message.contacts) ? message.contacts : []
          const clarificationCandidates = Array.isArray(message.clarification?.candidates)
            ? message.clarification.candidates : []
          if (message.role === 'user') {
            return (
              <div key={message.id} className="flex justify-end">
                <div className="flex max-w-[85%] flex-col items-end gap-1.5 sm:max-w-[75%]">
                  <div
                    className={cn(
                      'rounded-3xl border border-hairline bg-surface px-4 py-3',
                      'text-[13.5px] leading-relaxed text-fg',
                    )}
                  >
                    {message.content}
                  </div>
                  <span className="pr-1 font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                    {formatClock(message.createdAt)}
                  </span>
                </div>
              </div>
            )
          }

          // Assistant turn — left aligned with monogram gutter.
          const needsClarification =
            message.status === 'NEEDS_CLARIFICATION' || Boolean(message.clarification)

          return (
            <div key={message.id} className="flex gap-3">
              <ProteusMonogram className="mt-0.5 h-8 w-8" />

              <div className="flex min-w-0 flex-1 flex-col gap-3">
                <div className="max-w-[92%] rounded-3xl rounded-tl-md border border-hairline bg-elevated/40 px-4 py-3 sm:max-w-[85%]">
                  <p className="text-[13.5px] leading-relaxed text-fg">{message.content}</p>
                </div>

                {reasoning.length > 0 ? (
                  <ul className="flex flex-col gap-1.5 rounded-2xl border border-hairline bg-white/[0.02] px-4 py-3">
                    {reasoning.map((step, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-2 font-mono text-[10.5px] leading-relaxed text-fg-faint"
                      >
                        <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-accent/60" />
                        {step}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {needsClarification && message.clarification ? (
                  <div className="rounded-2xl border border-[#92400e]/50 bg-[#f59e0b]/[0.06] p-3.5">
                    <div className="mb-3 flex items-center gap-2">
                      <Sparkles className="h-3.5 w-3.5 text-[#fbbf24]" strokeWidth={1.7} />
                      <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#fbbf24]">
                        Which one did you mean?
                      </span>
                    </div>
                    <p className="mb-3 text-[13px] leading-relaxed text-fg-muted">
                      {message.clarification?.prompt ?? ''}
                    </p>
                    <ul className="flex flex-col gap-1.5">
                      {clarificationCandidates.map((c) => (
                        <li key={c.id}>
                          <button
                            type="button"
                            onClick={() => onResolve(message.id, c.name, c.email)}
                            className={cn(
                              'flex w-full items-center gap-3 rounded-2xl border border-hairline bg-white/[0.02] px-3 py-2.5 text-left',
                              'transition-colors duration-300 ease-proteus hover:border-accent/50 hover:bg-accent/[0.06]',
                            )}
                          >
                            <Avatar
                              initials={initialsFrom(c.name)}
                              hue="from-[#FCD34D] to-[#B45309]"
                              size="sm"
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[13px] text-fg">
                                {c.name}
                              </span>
                              <span className="block truncate font-mono text-[10.5px] text-fg-faint">
                                {c.email}
                              </span>
                            </span>
                            <span className="shrink-0 font-mono text-[10px] text-fg-faint">
                              {c.relationship} · {Math.round(c.confidence * 100)}%
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {contacts.length > 0 ? (
                  <ResolvedContactsStrip contacts={contacts} />
                ) : null}

                {message.draft ? (
                  <DraftReviewCard
                    key={message.draft.id}
                    draft={message.draft}
                    messageId={message.id}
                    busy={busy}
                    approving={approving}
                    revising={revising}
                    onApprove={onApprove}
                    onSave={onSave}
                    onTweak={onTweak}
                  />
                ) : null}

                <span className="pl-1 font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                  {formatClock(message.createdAt)}
                </span>
              </div>
            </div>
          )
        })}

        {busy ? (
          <div className="flex items-center gap-3">
            <ProteusMonogram className="h-8 w-8" />
            <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-elevated/40 px-3.5 py-2">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
                  style={{ animationDelay: `${i * 140}ms` }}
                />
              ))}
              <span className="ml-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
                drafting
              </span>
            </span>
          </div>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  )
}

export default MessageThread
