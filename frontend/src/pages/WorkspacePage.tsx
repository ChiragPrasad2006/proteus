import { AlertTriangle, FileText, MessageSquare, MessagesSquare, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { MailboxSetupGate } from '@/components/auth/MailboxSetupGate'
import { AutoSendConfirmModal } from '@/components/workspace/AutoSendConfirmModal'
import { ChatPane } from '@/components/workspace/ChatPane'
import { Coachmarks } from '@/components/workspace/Coachmarks'
import { CommandPalette } from '@/components/workspace/CommandPalette'
import { DraftPanel } from '@/components/workspace/DraftPanel'
import { SessionRail } from '@/components/workspace/SessionRail'
import { ShortcutsModal } from '@/components/workspace/ShortcutsModal'
import { StyleProfile } from '@/components/workspace/StyleProfile'
import { Toasts } from '@/components/workspace/Toasts'
import { WorkspaceHeader } from '@/components/workspace/WorkspaceHeader'
import { useHealth } from '@/hooks/useHealth'
import { useDraftState, useSelectedDraft } from '@/hooks/useDraftState'
import { LEFT_COLLAPSED_WIDTH, usePaneLayout } from '@/hooks/usePaneLayout'
import { useIsMobile, useIsTablet } from '@/hooks/useMediaQuery'
import { ApiError, api } from '@/lib/api'
import { humanizeDraftTurn } from '@/lib/status'
import { cn, uid } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { toast } from '@/stores/useToastStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'
import type { Account } from '@/types'

function humanError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

/** Slim hairline drag handle between panes (pointer + keyboard resizable). */
function DragHandle({ label, value, min, max, onDrag }: { label: string; value: number; min: number; max: number; onDrag: (deltaX: number) => void }) {
  const dragging = useRef(false)
  const lastX = useRef(0)
  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = true
    lastX.current = event.clientX
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    onDrag(event.clientX - lastX.current)
    lastX.current = event.clientX
  }
  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false
    event.currentTarget.releasePointerCapture(event.pointerId)
  }
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') { event.preventDefault(); onDrag(-16) }
    if (event.key === 'ArrowRight') { event.preventDefault(); onDrag(16) }
  }
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onKeyDown={handleKeyDown}
      className="group z-10 -mx-1 w-2 shrink-0 cursor-col-resize touch-none"
    >
      <div className="mx-auto h-full w-px bg-hairline transition-colors group-hover:bg-foam/70 group-focus-visible:bg-foam" />
    </div>
  )
}

export function WorkspacePage() {
  const account = useActiveAccount()
  const accounts = useAppStore((state) => state.accounts)
  const setAccounts = useAppStore((state) => state.setAccounts)
  const updateAccount = useAppStore((state) => state.updateAccount)
  const setActiveAccount = useAppStore((state) => state.setActiveAccount)
  const selectedDraft = useSelectedDraft()
  const selectDraft = useDraftState((state) => state.select)

  const { layout, update } = usePaneLayout()
  const isMobile = useIsMobile()
  const isTablet = useIsTablet()
  const health = useHealth()

  const paletteOpen = useWorkspaceUI((state) => state.paletteOpen)
  const setPaletteOpen = useWorkspaceUI((state) => state.setPaletteOpen)
  const profileOpen = useWorkspaceUI((state) => state.profileOpen)
  const shortcutsOpen = useWorkspaceUI((state) => state.shortcutsOpen)
  const setShortcutsOpen = useWorkspaceUI((state) => state.setShortcutsOpen)
  const draftSheetOpen = useWorkspaceUI((state) => state.draftSheetOpen)
  const setDraftSheetOpen = useWorkspaceUI((state) => state.setDraftSheetOpen)
  const mobileTab = useWorkspaceUI((state) => state.mobileTab)
  const setMobileTab = useWorkspaceUI((state) => state.setMobileTab)

  const [banner, setBanner] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const locked = !account || !account.mailboxConnected || accounts.length === 0

  /* ── Account hydration + OAuth redirect (unchanged contract) ─────────── */
  const handleMailboxConnected = useCallback((connectedAccount: Account) => {
    updateAccount({ ...connectedAccount, mailboxConnected: true })
    void (async () => {
      const result = await api.listAccounts()
      setAccounts(result.accounts, connectedAccount.id)
      await setActiveAccount(connectedAccount.id)
    })()
  }, [setAccounts, setActiveAccount, updateAccount])

  const handleAccountCreated = useCallback((createdAccount: Account) => {
    void (async () => {
      const result = await api.listAccounts()
      setAccounts(result.accounts, createdAccount.id)
      await setActiveAccount(createdAccount.id)
    })()
  }, [setAccounts, setActiveAccount])

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
      } catch (err) {
        if (!disposed) setBanner(humanError(err))
      }
    }
    void hydrateFromRedirect()
    return () => { disposed = true }
  }, [setAccounts, setActiveAccount])

  /* ── Draft focus (chat Action Card → panel / sheet / mobile tab) ─────── */
  const focusDraft = useCallback((draftId: string) => {
    selectDraft(draftId)
    if (isMobile) setMobileTab('draft')
    else if (isTablet) setDraftSheetOpen(true)
    else if (layout.rightCollapsed) update({ rightCollapsed: false })
  }, [selectDraft, isMobile, isTablet, setMobileTab, setDraftSheetOpen, layout.rightCollapsed, update])

  /* ── Chat turn with AbortController cancel ───────────────────────────── */
  const handleSend = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    const appState = useAppStore.getState()
    const accountId = appState.activeAccountId
    if (!accountId) { setBanner('Connect an account before chatting.'); return }
    let sessionId = appState.activeSessionId
    if (!sessionId) sessionId = await appState.createSession()
    if (!sessionId) { setBanner('Could not create a session.'); return }

    appState.appendMessage({ id: uid('msg'), role: 'user', content: trimmed, createdAt: new Date().toISOString(), status: 'done' })
    appState.touchSession(sessionId, trimmed)
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(true)
    setBanner(null)
    try {
      const data = await api.chatTurn(
        { session_id: sessionId, user_message: trimmed, auto_send: useAppStore.getState().autoSend },
        accountId,
        controller.signal,
      )
      const current = useAppStore.getState()
      if (current.activeAccountId !== accountId || current.activeSessionId !== sessionId) return
      if (data.status === 'ERROR') {
        setBanner(data.assistant_message || 'The local model could not complete that request.')
        return
      }
      if (data.draft_card) {
        useDraftState.getState().ingestTurnDraft(data.draft_card, sessionId, accountId)
        focusDraft(data.draft_card.id)
      }
      const content = data.draft_card
        ? humanizeDraftTurn(data.status, data.draft_card, data.review_reason)
        : data.assistant_message
      current.appendMessage({
        id: uid('msg'),
        role: 'assistant',
        content,
        createdAt: new Date().toISOString(),
        status: data.status === 'NEEDS_CLARIFICATION' ? 'NEEDS_CLARIFICATION' : 'done',
        contacts: data.contacts,
        draftId: data.draft_card?.id ?? null,
        clarification: data.clarification,
      })
      if (data.session_title) current.applySessionTitle(sessionId, data.session_title)
      current.touchSession(sessionId)
    } catch (err) {
      if (controller.signal.aborted) toast('Drafting cancelled.')
      else setBanner(humanError(err))
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }, [busy, focusDraft])

  const handleCancel = useCallback(() => { abortRef.current?.abort() }, [])

  /* ── Global keyboard shortcuts ───────────────────────────────────────── */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey
      const target = event.target as HTMLElement | null
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable
      if (mod && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen(!useWorkspaceUI.getState().paletteOpen)
      } else if (mod && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        void useAppStore.getState().createSession()
      } else if (mod && event.key === 'Enter') {
        const draft = useDraftState.getState().selectedDraftId ? useDraftState.getState().drafts[useDraftState.getState().selectedDraftId!] : null
        if (draft && (draft.status === 'pending_review' || draft.status === 'draft' || draft.status === 'failed')) {
          event.preventDefault()
          useDraftState.getState().startCountdown(draft.id)
        }
      } else if (event.key === 'Escape') {
        useWorkspaceUI.getState().closeAll()
      } else if (event.key === '?' && !typing) {
        event.preventDefault()
        setShortcutsOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [setPaletteOpen, setShortcutsOpen])

  /* ── beforeunload guard while a send is pending ──────────────────────── */
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      const pending = Object.values(useDraftState.getState().drafts).some((draft) => draft.status === 'sending_countdown' || draft.status === 'sending')
      if (pending) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  const offline = health.isError
  const showBanner = banner !== null || offline

  const bannerStrip = showBanner ? (
    <div className="flex items-center gap-2.5 border-b border-hairline bg-cobalt-deep px-4 py-2.5 lg:px-5" role="alert">
      <AlertTriangle className="h-4 w-4 shrink-0 text-ember" aria-hidden />
      <p className="min-w-0 flex-1 truncate text-[12px] text-paper-muted">
        {banner ?? 'Local backend offline — start Proteus.exe on 127.0.0.1:8000 for live drafting.'}
      </p>
      {banner ? (
        <button type="button" aria-label="Dismiss message" onClick={() => setBanner(null)} className="shrink-0 text-paper-muted hover:text-paper">
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  ) : null

  /* ── Locked mailbox state ────────────────────────────────────────────── */
  if (locked) {
    return (
      <div className="flex h-svh overflow-hidden bg-cobalt-deep text-paper">
        {accounts.length > 0 && account ? (
          <div className="hidden shrink-0 md:block" style={{ width: layout.leftCollapsed ? LEFT_COLLAPSED_WIDTH : layout.leftWidth }}>
            <SessionRail collapsed={layout.leftCollapsed} onToggleCollapsed={() => update({ leftCollapsed: !layout.leftCollapsed })} />
          </div>
        ) : null}
        <MailboxSetupGate account={account} onConnected={handleMailboxConnected} onAccountCreated={handleAccountCreated} />
        <Toasts />
      </div>
    )
  }

  const chatStage = (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <WorkspaceHeader showDraftButton={isTablet && !isMobile} />
      {bannerStrip}
      <ChatPane busy={busy} onCancel={handleCancel} onSend={(text) => void handleSend(text)} onSelectDraft={focusDraft} />
    </main>
  )

  /* ── Mobile: single column + bottom tab bar ──────────────────────────── */
  if (isMobile) {
    return (
      <div className="flex h-svh flex-col overflow-hidden bg-cobalt text-paper">
        <div className="flex min-h-0 flex-1 flex-col">
          {mobileTab === 'chat' ? chatStage : null}
          {mobileTab === 'draft' ? (
            <div className="flex min-h-0 flex-1 flex-col" data-tour="draft">
              <DraftPanel onClose={() => setMobileTab('chat')} />
            </div>
          ) : null}
          {mobileTab === 'sessions' ? (
            <SessionRail collapsed={false} onToggleCollapsed={() => setMobileTab('chat')} fullscreen onClose={() => setMobileTab('chat')} />
          ) : null}
        </div>
        <nav className="flex shrink-0 border-t border-hairline bg-cobalt-deep" aria-label="Workspace sections">
          {([
            { tab: 'chat', label: 'Chat', icon: MessageSquare },
            { tab: 'draft', label: 'Draft', icon: FileText },
            { tab: 'sessions', label: 'Sessions', icon: MessagesSquare },
          ] as const).map(({ tab, label, icon: Icon }) => (
            <button
              key={tab}
              type="button"
              onClick={() => setMobileTab(tab)}
              aria-current={mobileTab === tab ? 'page' : undefined}
              className={cn('flex flex-1 flex-col items-center gap-1 py-2.5 text-[12px]', mobileTab === tab ? 'text-foam' : 'text-paper-muted hover:text-paper')}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </button>
          ))}
        </nav>
        <Toasts />
        <CommandPalette />
        <StyleProfile />
        <ShortcutsModal />
        <AutoSendConfirmModal />
        <Coachmarks enabled={!locked} />
      </div>
    )
  }

  /* ── Desktop / tablet: resizable 3-pane shell ────────────────────────── */
  return (
    <div className="flex h-svh overflow-hidden bg-cobalt text-paper">
      <div className="shrink-0" style={{ width: layout.leftCollapsed ? LEFT_COLLAPSED_WIDTH : layout.leftWidth }}>
        <SessionRail collapsed={layout.leftCollapsed} onToggleCollapsed={() => update({ leftCollapsed: !layout.leftCollapsed })} />
      </div>
      {!layout.leftCollapsed ? (
        <DragHandle label="Resize session rail" value={layout.leftWidth} min={220} max={360} onDrag={(delta) => update({ leftWidth: layout.leftWidth + delta })} />
      ) : null}

      {chatStage}

      {!isTablet ? (
        layout.rightCollapsed ? (
          <button
            type="button"
            onClick={() => update({ rightCollapsed: false })}
            aria-label="Expand draft panel"
            className="on-paper flex w-10 shrink-0 flex-col items-center gap-3 border-l border-ink-hairline bg-paper py-4 text-ink"
          >
            <span className={cn('h-2 w-2 rounded-pill', selectedDraft?.status === 'sent' ? 'bg-foam-ink' : selectedDraft?.status === 'pending_review' ? 'bg-ember-ink' : 'bg-ink/30')} aria-hidden />
            <span className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted" style={{ writingMode: 'vertical-rl' }}>
              {selectedDraft?.subject ? selectedDraft.subject.slice(0, 40) : 'Paper letter'}
            </span>
          </button>
        ) : (
          <>
            <DragHandle label="Resize draft panel" value={layout.rightWidth} min={360} max={620} onDrag={(delta) => update({ rightWidth: layout.rightWidth - delta })} />
            <div className="shrink-0 border-l border-hairline" style={{ width: layout.rightWidth }} data-tour="draft">
              <DraftPanel />
            </div>
          </>
        )
      ) : null}

      {/* Tablet slide-over sheet */}
      {isTablet && draftSheetOpen ? (
        <div className="fixed inset-0 z-[60] flex justify-end bg-ink/50" onMouseDown={(event) => { if (event.target === event.currentTarget) setDraftSheetOpen(false) }}>
          <div className="h-full w-[440px] max-w-full border-l border-ink-hairline" role="dialog" aria-modal="true" aria-label="Paper letter draft" data-tour="draft">
            <DraftPanel onClose={() => setDraftSheetOpen(false)} />
          </div>
        </div>
      ) : null}

      <Toasts />
      <CommandPalette />
      <StyleProfile />
      <ShortcutsModal />
      <AutoSendConfirmModal />
      <Coachmarks enabled={!locked && !paletteOpen && !profileOpen && !shortcutsOpen} />
    </div>
  )
}

export default WorkspacePage