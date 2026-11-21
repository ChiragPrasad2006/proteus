import { useMemo } from 'react'
import { Composer } from '@/components/workspace/Composer'
import { MessageList } from '@/components/workspace/MessageList'
import { friendlyName } from '@/lib/status'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { useComposerBus } from '@/stores/useComposerBus'

export interface ChatPaneProps {
  busy: boolean
  onCancel: () => void
  onSend: (text: string) => void
  onSelectDraft: (draftId: string) => void
}

const SUGGESTIONS = [
  'Follow up with someone',
  'Send a quick project update',
  'Draft a polite decline',
  'Email a group with CC',
] as const

/** Center stage: empty state, message column (max 720px) and composer. */
export function ChatPane({ busy, onCancel, onSend, onSelectDraft }: ChatPaneProps) {
  const messages = useAppStore((state) => state.messages)
  const contacts = useAppStore((state) => state.contacts)
  const account = useActiveAccount()
  const insert = useComposerBus((state) => state.insert)
  const onEditResend = (text: string) => insert(text, 'replace')

  const firstName = useMemo(() => {
    const name = account?.name?.trim()
    if (!name) return null
    const first = name.split(/\s+/)[0] ?? ''
    return first ? first.charAt(0).toUpperCase() + first.slice(1) : null
  }, [account?.name])

  const recentContacts = useMemo(() => {
    return [...contacts]
      .filter((contact) => contact.email && contact.email.includes('@'))
      .sort((a, b) => b.sentCount - a.sentCount)
      .slice(0, 4)
  }, [contacts])

  const isEmpty = messages.length === 0 && !busy

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-cobalt">
      {isEmpty ? (
        <div className="flex flex-1 items-center justify-center overflow-y-auto px-6">
          <div className="flex w-full max-w-[720px] flex-col items-center py-10 text-center">
            <img src="/art/proteus-face.webp" alt="" aria-hidden className="engraving-multiply mb-6 h-24 w-24 rounded-pill object-cover opacity-70" />
            <h2 className="font-display text-3xl tracking-tight text-paper">
              What shall we write today{firstName ? `, ${firstName}` : ''}?
            </h2>
            <p className="mt-3 max-w-md text-[13px] leading-relaxed text-paper-muted">
              Brief Proteus on who you’re writing to and what needs to land. It resolves contacts and drafts in your local voice.
            </p>
            <div className="mt-7 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => insert(`${suggestion}: `)}
                  className="rounded-pill border border-hairline px-4 py-2 text-[13px] text-paper transition-colors hover:border-foam/70 hover:bg-foam/10"
                >
                  {suggestion}
                </button>
              ))}
            </div>
            {recentContacts.length > 0 ? (
              <div className="mt-6 flex flex-col items-center gap-2.5">
                <span className="font-mono text-[12px] uppercase tracking-[0.14em] text-paper-muted">Recent contacts</span>
                <div className="flex flex-wrap justify-center gap-2">
                  {recentContacts.map((contact) => (
                    <button
                      key={contact.id}
                      type="button"
                      onClick={() => insert(`Email ${contact.name} about `)}
                      title={contact.email}
                      className="inline-flex items-center gap-2 rounded-pill border border-hairline bg-cobalt-deep px-3.5 py-1.5 text-[12px] text-paper transition-colors hover:border-foam/70"
                    >
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-pill bg-foam font-mono text-[12px] uppercase text-ink" aria-hidden>
                        {friendlyName(contact.name).charAt(0)}
                      </span>
                      {contact.name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <MessageList
          messages={messages}
          busy={busy}
          onCancel={onCancel}
          onSendText={onSend}
          onSelectDraft={onSelectDraft}
          onEditResend={onEditResend}
        />
      )}
      <Composer busy={busy} onSend={onSend} contacts={contacts} autoFocus={!isEmpty} />
      {/* Waves engraving watermark — bottom-right of the chat pane. */}
      <img
        src="/art/proteus-waves.webp"
        alt=""
        aria-hidden
        className="engraving-multiply pointer-events-none absolute bottom-24 right-4 hidden h-20 w-32 object-contain opacity-[0.06] lg:block"
      />
    </div>
  )
}

export default ChatPane