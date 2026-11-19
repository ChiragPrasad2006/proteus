import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { MailboxSetupGate } from '@/components/auth/MailboxSetupGate'
import { MessageThread } from '@/components/workspace/MessageThread'
import { PromptComposer } from '@/components/workspace/PromptComposer'
import { Sidebar } from '@/components/workspace/Sidebar'
import { WorkspaceHeader } from '@/components/workspace/WorkspaceHeader'
import { useHealth } from '@/hooks/useHealth'
import { ApiError, api } from '@/lib/api'
import { uid } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import type { Account, ChatMessage, EmailDraft } from '@/types'

/** Cached, clearly-labelled fallback shown when the local API is unreachable. */
function demoReply(): ChatMessage {
  return {
    id: uid('msg'),
    role: 'assistant',
    content:
      "I can't reach the local backend, so here's a cached demo draft instead. Start the API on 127.0.0.1:8000 and I'll generate a live, voice-matched reply from your corpus.",
    createdAt: new Date().toISOString(),
    status: 'done',
    reasoning: ['Backend offline — demo mode', 'Loaded a cached example draft'],
    contacts: [],
    draft: null,
  }
}

function humanError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

export function WorkspacePage() {
  const messages = useAppStore((s) => s.messages)
  const appendMessage = useAppStore((s) => s.appendMessage)
  const updateDraft = useAppStore((s) => s.updateDraft)
  const markDraftSent = useAppStore((s) => s.markDraftSent)
  const activeSessionId = useAppStore((s) => s.activeSessionId)
  const autoSend = useAppStore((s) => s.autoSend)
  const account = useActiveAccount()
  const setAccounts = useAppStore((s) => s.setAccounts)
  const updateAccount = useAppStore((s) => s.updateAccount)
  const setActiveAccount = useAppStore((s) => s.setActiveAccount)

  const handleMailboxConnected = useCallback((connectedAccount: Account) => {
    updateAccount({ ...connectedAccount, mailboxConnected: true })
    void (async () => {
      try {
        const result = await api.listAccounts()
        setAccounts(result.accounts, connectedAccount.id)
      } catch {
        // Keep the successful response's optimistic mailbox state.
      }
      await setActiveAccount(connectedAccount.id)
    })()
  }, [setAccounts, setActiveAccount, updateAccount])

  useEffect(() => {
    let disposed = false
    const hydrateFromRedirect = async () => {
      try {
        const result = await api.listAccounts()
        if (disposed) return
        const params = new URLSearchParams(window.location.search)
        const redirectAccountId = params.get('auth') === 'success' ? params.get('account_id') : null
        const activeId = redirectAccountId ?? result.active_account_id
        setAccounts(result.accounts, activeId)
        if (redirectAccountId) window.history.replaceState({}, '', '/workspace')
        if (activeId) await setActiveAccount(activeId)
      } catch (err) { if (!disposed) setBanner(humanError(err)) }
    }
    void hydrateFromRedirect()
    return () => { disposed = true }
  }, [setAccounts, setActiveAccount])

  const [banner, setBanner] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const health = useHealth()
  const offline = health.isError

  const chat = useMutation({
    mutationFn: (payload: { session_id: string; user_message: string; auto_send?: boolean }) =>
      api.chatTurn(payload, account?.id),
    onSuccess: (data) => {
      setBanner(null)
      const source = (data.parsed?.source as string) || 'ollama'
      appendMessage({
        id: uid('msg'),
        role: 'assistant',
        content: data.assistant_message,
        createdAt: new Date().toISOString(),
        status: 'done',
        reasoning: data.parsed ? [source] : [],
        contacts: data.contacts,
        draft: data.draft_card || null,
        clarification: data.clarification,
      })
      // Update session title if returned from backend (auto-summarized or renamed)
      if (data.session_title) {
        useAppStore.getState().renameSession(data.session_id, data.session_title)
      }
    },
    onError: (err) => {
      setBanner(humanError(err))
      appendMessage(demoReply())
    },
  })

  const approve = useMutation({
    mutationFn: ({ messageId: _messageId, ...payload }: { messageId: string; draft_id: string; final_subject: string; final_body: string }) =>
      api.approveAndLearn(payload, account?.id),
    onSuccess: (data, variables) => {
      if (data.status === 'SENT') {
        markDraftSent(variables.messageId)
        setBanner(null)
        const learned = data.extracted_rules.length > 0 ? ` Learned: ${data.extracted_rules.join(' · ')}` : ''
        setToast(`Email sent successfully.${learned}`)
      } else {
        updateDraft(variables.messageId, { status: 'FAILED' })
        setBanner(data.receipt_error || 'Email send failed. The draft remains available for retry.')
        setToast(null)
      }
    },
    onError: (err) => { setBanner(humanError(err)); setToast(null) },
  })

  const tweakDraft = useMutation({
    mutationFn: ({ messageId: _messageId, draft, instruction }: {
      messageId: string
      draft: EmailDraft
      instruction: string
    }) => api.tweakDraft({
      draft_id: draft.id,
      tweak_instruction: instruction,
      current_to: draft.to,
      current_cc: draft.cc,
      current_bcc: draft.bcc,
      current_subject: draft.subject,
      current_body: draft.body,
    }, account?.id),
    onSuccess: (data, variables) => {
      updateDraft(variables.messageId, { subject: data.subject, body: data.body, status: 'PENDING_REVIEW' })
      setBanner(null)
      setToast('Draft revised in place. Review it before sending.')
      // Note: tweakDraft endpoint doesn't return session_title/session_id
      // Session title updates happen via chat/turn when user tweaks via chat
    },
    onError: (err) => { setBanner(humanError(err)); setToast(null) },
  })

  const handleSend = useCallback(
    (text: string) => {
      appendMessage({
        id: uid('msg'),
        role: 'user',
        content: text,
        createdAt: new Date().toISOString(),
        status: 'done',
      })
      chat.mutate({
        session_id: activeSessionId ?? '',
        user_message: text,
        auto_send: autoSend,
      })
    },
    [appendMessage, chat, activeSessionId, autoSend],
  )

  const handleApprove = useCallback(
    (messageId: string, draft: EmailDraft) => {
      updateDraft(messageId, draft)
      approve.mutate({
        messageId,
        draft_id: draft.id,
        final_subject: draft.subject,
        final_body: draft.body,
      })
    },
    [updateDraft, approve],
  )

  const handleSave = useCallback(
    (messageId: string, draft: EmailDraft) => {
      updateDraft(messageId, { ...draft, status: 'DRAFT' })
    },
    [updateDraft],
  )

  const handleTweak = useCallback(
    async (messageId: string, text: string, draft: EmailDraft) => {
      await tweakDraft.mutateAsync({ messageId, draft, instruction: text })
    },
    [tweakDraft],
  )

  const handleResolve = useCallback(
    (_messageId: string, name: string, email: string) => {
      handleSend(`Use ${name} <${email}>`)
    },
    [handleSend],
  )

  const showBanner = banner !== null || offline

  return (
    <div className="flex h-screen overflow-hidden bg-ink text-fg">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <WorkspaceHeader />
        {toast ? (
          <div role="status" aria-live="polite" className="flex items-center justify-between gap-3 border-b border-accent/30 bg-accent/[0.08] px-5 py-2.5 text-[12.5px] text-accent">
            <p>{toast}</p>
            <button type="button" onClick={() => setToast(null)} className="shrink-0 text-accent/75 hover:text-accent">Dismiss</button>
          </div>
        ) : null}

        {account && !account.mailboxConnected ? (
          <MailboxSetupGate account={account} onConnected={handleMailboxConnected} />
        ) : (
          <>
            {showBanner ? (
          <div className="flex items-center gap-2.5 border-b border-hairline bg-[#f59e0b]/[0.07] px-4 py-2.5 lg:px-6">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[#fbbf24]" strokeWidth={1.8} />
            <p className="min-w-0 flex-1 truncate text-[12px] text-[#fbbf24]">
              {banner ??
                'Local backend offline — running in demo mode. Start the API on 127.0.0.1:8000 for live drafting.'}
            </p>
            {banner ? (
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => setBanner(null)}
                className="shrink-0 text-[#fbbf24]/70 transition-colors hover:text-[#fbbf24]"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        ) : null}

        <MessageThread
          messages={messages}
          busy={chat.isPending}
          approving={approve.isPending}
          revising={tweakDraft.isPending}
          onResolve={handleResolve}
          onApprove={handleApprove}
          onSave={handleSave}
          onTweak={handleTweak}
        />

            <PromptComposer busy={chat.isPending} onSend={handleSend} />
          </>
        )}
      </div>
    </div>
  )
}

export default WorkspacePage
