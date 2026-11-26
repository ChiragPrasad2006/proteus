import { ChevronDown, ChevronUp, Loader2, Mail, Reply, ReplyAll, SendHorizontal, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { formatRelativeTime } from '@/lib/format'
import { friendlyName } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import type { InboxThreadMessage, ReplyMode } from '@/types'

export interface InboxThreadPaneProps {
  busy: boolean
  onDraftReply: (threadId: string, replyMode: ReplyMode, instruction: string) => void
  onCancel: () => void
}

function computePreviewTargets(
  messages: InboxThreadMessage[],
  selfEmail: string,
  replyMode: ReplyMode,
): { to: string[]; cc: string[] } {
  if (messages.length === 0) return { to: [], cc: [] }
  const selfNorm = selfEmail.trim().toLowerCase()
  const latest = messages[messages.length - 1]!
  const latestExt = [...messages].reverse().find((m) => m.from_email.trim().toLowerCase() !== selfNorm) ?? latest

  const dedup = (addrs: string[], exclude: Set<string>) => {
    const out: string[] = []
    for (const raw of addrs) {
      const clean = raw.trim().toLowerCase()
      if (clean && clean.includes('@') && !exclude.has(clean) && !out.includes(clean)) {
        out.push(clean)
      }
    }
    return out
  }

  const excludeSelf = selfNorm ? new Set([selfNorm]) : new Set<string>()
  const sender = latestExt.from_email.trim().toLowerCase()

  if (replyMode === 'reply_all') {
    const to = dedup([...(sender && sender !== selfNorm ? [sender] : []), ...latestExt.to], excludeSelf)
    const cc = dedup(latestExt.cc, new Set([...excludeSelf, ...to]))
    return { to, cc }
  }

  const to = dedup(sender ? [sender] : latestExt.to, excludeSelf)
  return { to, cc: [] }
}

export function InboxThreadPane({ busy, onDraftReply, onCancel }: InboxThreadPaneProps) {
  const activeThread = useAppStore((state) => state.activeThread)
  const threadLoading = useAppStore((state) => state.threadLoading)
  const inboxError = useAppStore((state) => state.inboxError)
  const account = useActiveAccount()

  const [replyMode, setReplyMode] = useState<ReplyMode>('reply')
  const [instruction, setInstruction] = useState('')
  const [expandedOlder, setExpandedOlder] = useState(false)

  // Reset per-thread local UI state on thread change.
  const threadId = activeThread?.thread_id ?? null
  const [prevThreadId, setPrevThreadId] = useState<string | null>(threadId)
  if (prevThreadId !== threadId) {
    setPrevThreadId(threadId)
    setReplyMode('reply')
    setInstruction('')
    setExpandedOlder(false)
  }

  const messages = useMemo(() => activeThread?.messages ?? [], [activeThread])
  const hasCollapsedOlder = messages.length > 3 && !expandedOlder
  const olderCount = Math.max(0, messages.length - 2)
  const visibleMessages = hasCollapsedOlder ? messages.slice(-2) : messages

  const previewTargets = useMemo(
    () => computePreviewTargets(messages, account?.email ?? '', replyMode),
    [messages, account?.email, replyMode],
  )
  const replyAllTargets = useMemo(
    () => computePreviewTargets(messages, account?.email ?? '', 'reply_all'),
    [messages, account?.email],
  )
  const replyTargets = useMemo(
    () => computePreviewTargets(messages, account?.email ?? '', 'reply'),
    [messages, account?.email],
  )

  const totalSelectedCount = previewTargets.to.length + previewTargets.cc.length

  if (threadLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="flex items-center gap-2.5 text-[13px] text-paper-muted">
          <Loader2 className="h-4 w-4 animate-spin text-foam" aria-hidden />
          Loading thread…
        </div>
      </div>
    )
  }

  if (!activeThread) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="max-w-[460px] text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-pill border border-hairline bg-cobalt-deep text-foam">
            <Mail className="h-5 w-5" aria-hidden />
          </div>
          <h2 className="font-display text-2xl font-normal text-paper">Read-only Inbox</h2>
          <p className="mt-2 text-[13px] leading-relaxed text-paper-muted">
            {inboxError ?? 'Select a conversation from the Inbox rail to read the thread and manually draft a reply in your voice.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Scrollable chronological thread */}
      <div className="scrollbar-none flex-1 overflow-y-auto px-4 py-6 lg:px-6">
        <div className="mx-auto max-w-[720px] space-y-4">
          {messages.length > 3 ? (
            <button
              type="button"
              onClick={() => setExpandedOlder((v) => !v)}
              className="flex w-full items-center justify-center gap-2 rounded-card border border-hairline bg-cobalt-deep/80 px-4 py-2 font-mono text-[12px] text-paper-muted transition-colors hover:border-paper-label hover:text-paper"
            >
              {hasCollapsedOlder ? (
                <>
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                  Show {olderCount} older message{olderCount === 1 ? '' : 's'}
                </>
              ) : (
                <>
                  <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                  Hide older messages
                </>
              )}
            </button>
          ) : null}

          {visibleMessages.map((msg) => (
            <article
              key={msg.message_id}
              className="rounded-card border border-hairline bg-cobalt-deep p-5"
            >
              <header className="border-b border-hairline pb-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="min-w-0 font-mono text-[12px] text-paper">
                    <span className="font-medium">{msg.from_name || friendlyName(msg.from_email)}</span>
                    {msg.from_email ? (
                      <span className="ml-1.5 text-paper-muted">&lt;{msg.from_email}&gt;</span>
                    ) : null}
                  </div>
                  {msg.date ? (
                    <time
                      dateTime={msg.date}
                      title={new Date(msg.date).toLocaleString()}
                      className="shrink-0 font-mono text-[12px] text-paper-muted"
                    >
                      {formatRelativeTime(msg.date)}
                    </time>
                  ) : null}
                </div>
                {msg.to.length > 0 ? (
                  <p className="mt-1 truncate font-mono text-[12px] text-paper-muted" title={msg.to.join(', ')}>
                    To: {msg.to.join(', ')}
                  </p>
                ) : null}
                {msg.cc.length > 0 ? (
                  <p className="mt-0.5 truncate font-mono text-[12px] text-paper-muted" title={msg.cc.join(', ')}>
                    Cc: {msg.cc.join(', ')}
                  </p>
                ) : null}
              </header>
              <div className="mt-3.5 whitespace-pre-wrap font-display text-[15px] leading-[1.65] text-paper">
                {msg.body_text || '(empty message body)'}
              </div>
            </article>
          ))}
        </div>
      </div>

      {/* Pinned manual Reply Composer Bar */}
      <div className="shrink-0 border-t border-hairline bg-cobalt-deep px-4 py-3.5 lg:px-6">
        <div className="mx-auto max-w-[720px] space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-pill border border-hairline bg-cobalt p-0.5" role="group" aria-label="Reply mode">
              <button
                type="button"
                onClick={() => setReplyMode('reply')}
                aria-pressed={replyMode === 'reply'}
                disabled={busy}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-pill px-3 py-1 text-[12px] font-medium transition-colors',
                  replyMode === 'reply' ? 'bg-paper text-ink' : 'text-paper-muted hover:text-paper',
                )}
              >
                <Reply className="h-3.5 w-3.5" aria-hidden />
                Reply ({replyTargets.to.length})
              </button>
              <button
                type="button"
                onClick={() => setReplyMode('reply_all')}
                aria-pressed={replyMode === 'reply_all'}
                disabled={busy}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-pill px-3 py-1 text-[12px] font-medium transition-colors',
                  replyMode === 'reply_all' ? 'bg-paper text-ink' : 'text-paper-muted hover:text-paper',
                )}
              >
                <ReplyAll className="h-3.5 w-3.5" aria-hidden />
                Reply All ({replyAllTargets.to.length + replyAllTargets.cc.length})
              </button>
            </div>

            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              {previewTargets.to.map((addr) => (
                <span
                  key={`to-${addr}`}
                  className="inline-flex items-center gap-1 rounded-pill border border-hairline bg-cobalt px-2.5 py-0.5 font-mono text-[12px] text-paper"
                  title={`To: ${addr}`}
                >
                  To: {friendlyName(addr)}
                </span>
              ))}
              {previewTargets.cc.map((addr) => (
                <span
                  key={`cc-${addr}`}
                  className="inline-flex items-center gap-1 rounded-pill border border-hairline bg-cobalt px-2.5 py-0.5 font-mono text-[12px] text-paper-muted"
                  title={`Cc: ${addr}`}
                >
                  Cc: {friendlyName(addr)}
                </span>
              ))}
              {totalSelectedCount === 0 ? (
                <span className="font-mono text-[12px] text-paper-muted">No external recipients resolved</span>
              ) : null}
            </div>
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (!busy && activeThread) onDraftReply(activeThread.thread_id, replyMode, instruction)
            }}
            className="flex flex-col gap-2 sm:flex-row sm:items-center"
          >
            <input
              type="text"
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              disabled={busy}
              aria-label="Optional reply guidance"
              placeholder="Optional guidance for Proteus (e.g., confirm Tuesday 3 PM, ask for updated timeline)..."
              className="min-w-0 flex-1 rounded-pill border border-hairline bg-cobalt px-4 py-2 text-[13px] text-paper placeholder:text-paper-muted focus:border-foam/70 focus:outline-none disabled:opacity-60"
            />
            <div className="flex shrink-0 items-center gap-2">
              {busy ? (
                <button
                  type="button"
                  onClick={onCancel}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-hairline px-4 py-2 text-[13px] font-medium text-paper transition-colors hover:border-ember hover:text-ember"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                  Cancel
                </button>
              ) : null}
              <button
                type="submit"
                disabled={busy || totalSelectedCount === 0}
                className="inline-flex items-center gap-2 rounded-pill bg-paper px-5 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-foam disabled:opacity-50"
              >
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    Drafting…
                  </>
                ) : (
                  <>
                    <SendHorizontal className="h-4 w-4" aria-hidden />
                    Draft Reply
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

export default InboxThreadPane
