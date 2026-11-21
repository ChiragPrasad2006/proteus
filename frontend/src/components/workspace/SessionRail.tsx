import { Check, ChevronsUpDown, LogOut, MessageSquarePlus, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Pencil, Pin, PinOff, Plus, Search, Trash2, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { ConnectGmailModal } from '@/components/auth/ConnectGmailModal'
import { Avatar } from '@/components/ui/Avatar'
import { IconButton } from '@/components/ui/IconButton'
import { Wordmark } from '@/components/ui/Wordmark'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useDraftState } from '@/hooks/useDraftState'
import { formatRelativeTime, sessionBucket, type SessionBucket } from '@/lib/format'
import { getPinnedSessions, togglePinnedSession } from '@/lib/localAdapter'
import { deriveSessionTitle, friendlyName } from '@/lib/status'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { useToastStore } from '@/stores/useToastStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'
import type { Provider, Session } from '@/types'

const PROVIDER_LABEL: Record<Provider, string> = { gmail: 'Gmail', outlook: 'Outlook', imap: 'IMAP', mbox: 'Mbox', demo: 'Demo' }
const BUCKET_ORDER: SessionBucket[] = ['Today', 'Yesterday', 'Previous 7 Days', 'Older']

export interface SessionRailProps {
  collapsed: boolean
  onToggleCollapsed: () => void
  /** Full-screen mode (mobile Sessions tab). */
  fullscreen?: boolean
  onClose?: () => void
}

interface RowMeta {
  recipientInitial: string | null
  recipientName: string | null
  dot: 'ember' | 'foam' | null
}

export function SessionRail({ collapsed, onToggleCollapsed, fullscreen = false, onClose }: SessionRailProps) {
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const messages = useAppStore((state) => state.messages)
  const selectSession = useAppStore((state) => state.selectSession)
  const createSession = useAppStore((state) => state.createSession)
  const renameSession = useAppStore((state) => state.renameSession)
  const deleteSession = useAppStore((state) => state.deleteSession)
  const styleProfile = useAppStore((state) => state.styleProfile)
  const accounts = useAppStore((state) => state.accounts)
  const activeAccountId = useAppStore((state) => state.activeAccountId)
  const setActiveAccount = useAppStore((state) => state.setActiveAccount)
  const setAccounts = useAppStore((state) => state.setAccounts)
  const clearAccountState = useAppStore((state) => state.clearAccountState)
  const account = useActiveAccount()
  const drafts = useDraftState((state) => state.drafts)
  const setProfileOpen = useWorkspaceUI((state) => state.setProfileOpen)
  const setPaletteOpen = useWorkspaceUI((state) => state.setPaletteOpen)
  const pushToast = useToastStore((state) => state.push)
  const dismissToast = useToastStore((state) => state.dismiss)

  const [searchQuery, setSearchQuery] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [hiddenIds, setHiddenIds] = useState<string[]>([])
  const [pins, setPins] = useState<string[]>(() => activeAccountId ? getPinnedSessions(activeAccountId) : [])
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [connectOpen, setConnectOpen] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)
  const navRef = useRef<HTMLElement>(null)
  const deleteTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const accountMenuRef = useClickOutside<HTMLDivElement>(accountMenuOpen, () => setAccountMenuOpen(false))
  const menuRef = useClickOutside<HTMLDivElement>(menuId !== null, () => setMenuId(null))

  // Pins are per-account: reload when the account changes (render-phase adjustment).
  const [pinsAccount, setPinsAccount] = useState<string | null>(activeAccountId)
  if (pinsAccount !== activeAccountId) {
    setPinsAccount(activeAccountId)
    setPins(activeAccountId ? getPinnedSessions(activeAccountId) : [])
    setHiddenIds([])
  }

  useEffect(() => {
    if (renamingId) { renameInputRef.current?.focus(); renameInputRef.current?.select() }
  }, [renamingId])

  useEffect(() => () => {
    for (const timer of deleteTimers.current.values()) clearTimeout(timer)
  }, [])

  /** Never show "New session" once content exists — derive a sentence-case title. */
  const [derivedTitles, setDerivedTitles] = useState<Record<string, string>>({})
  const fetchedTitlesRef = useRef(new Set<string>())
  useEffect(() => {
    if (!activeAccountId) return
    const untitled = sessions.filter((session) =>
      (!session.title?.trim() || session.title.trim().toLowerCase() === 'new session') && !fetchedTitlesRef.current.has(session.id),
    )
    if (untitled.length === 0) return
    let cancelled = false
    for (const session of untitled.slice(0, 12)) {
      fetchedTitlesRef.current.add(session.id)
      void api.getSession(session.id, activeAccountId).then((detail) => {
        if (cancelled) return
        const firstUser = detail.messages.find((message) => message.role === 'user')
        const draftSubject = detail.drafts.find((draft) => draft.subject)?.subject
        const source = firstUser?.content || draftSubject || ''
        if (source) setDerivedTitles((current) => ({ ...current, [session.id]: deriveSessionTitle(source) }))
      }).catch(() => { /* keep fallback title */ })
    }
    return () => { cancelled = true }
  }, [sessions, activeAccountId])

  const effectiveTitle = useCallback((session: Session): string => {
    const raw = session.title?.trim()
    if (raw && raw.toLowerCase() !== 'new session') return raw
    if (session.preview?.trim()) return deriveSessionTitle(session.preview)
    if (session.id === activeSessionId) {
      const firstUser = messages.find((message) => message.role === 'user')
      if (firstUser) return deriveSessionTitle(firstUser.content)
      const firstDraft = Object.values(drafts).find((draft) => draft.sessionId === session.id)
      if (firstDraft?.subject) return deriveSessionTitle(firstDraft.subject)
    }
    return derivedTitles[session.id] ?? 'New session'
  }, [activeSessionId, messages, drafts, derivedTitles])

  const rowMeta = useCallback((session: Session): RowMeta => {
    const sessionDrafts = Object.values(drafts).filter((draft) => draft.sessionId === session.id)
    const recipient = sessionDrafts[0]?.to[0]
    const awaiting = sessionDrafts.some((draft) => draft.status === 'pending_review')
    const sent = sessionDrafts.some((draft) => draft.status === 'sent')
    return {
      recipientInitial: recipient ? friendlyName(recipient).charAt(0).toUpperCase() : null,
      recipientName: recipient ? friendlyName(recipient) : null,
      dot: awaiting ? 'ember' : sent ? 'foam' : null,
    }
  }, [drafts])

  const filteredSessions = useMemo(() => {
    const visible = sessions.filter((session) => !hiddenIds.includes(session.id))
    if (!searchQuery.trim()) return visible
    const query = searchQuery.toLowerCase()
    return visible.filter((session) => effectiveTitle(session).toLowerCase().includes(query) || (session.preview ?? '').toLowerCase().includes(query))
  }, [sessions, hiddenIds, searchQuery, effectiveTitle])

  const grouped = useMemo(() => {
    const pinned = filteredSessions.filter((session) => pins.includes(session.id))
    const rest = filteredSessions.filter((session) => !pins.includes(session.id))
    const map = new Map<SessionBucket, Session[]>()
    for (const session of rest) {
      const key = sessionBucket(session.updatedAt)
      const list = map.get(key) ?? []
      list.push(session)
      map.set(key, list)
    }
    const groups: { name: string; items: Session[] }[] = []
    if (pinned.length > 0) groups.push({ name: 'Pinned', items: pinned })
    for (const bucket of BUCKET_ORDER) {
      const items = map.get(bucket)
      if (items && items.length > 0) groups.push({ name: bucket, items })
    }
    return groups
  }, [filteredSessions, pins])

  const flatVisible = useMemo(() => grouped.flatMap((group) => collapsedGroups[group.name] ? [] : group.items), [grouped, collapsedGroups])

  const handleRenameCommit = useCallback(async (sessionId: string) => {
    const title = renameDraft.trim()
    if (title && title.length <= 100) {
      try { await renameSession(sessionId, title) } catch { /* keep previous title */ }
    }
    setRenamingId(null)
    setRenameDraft('')
  }, [renameDraft, renameSession])

  /** 8-second Undo window before the DELETE actually fires. */
  const handleDelete = useCallback((session: Session) => {
    setMenuId(null)
    setHiddenIds((current) => [...current, session.id])
    const wasActive = session.id === activeSessionId
    const nextSession = sessions.find((item) => item.id !== session.id && !hiddenIds.includes(item.id))
    if (wasActive && nextSession) void selectSession(nextSession.id)
    const toastId = pushToast({
      message: `Deleting “${effectiveTitle(session)}”…`,
      tone: 'neutral',
      durationMs: 8000,
      actionLabel: 'Undo',
      onAction: () => {
        const timer = deleteTimers.current.get(session.id)
        if (timer) { clearTimeout(timer); deleteTimers.current.delete(session.id) }
        setHiddenIds((current) => current.filter((id) => id !== session.id))
        if (wasActive) void selectSession(session.id)
      },
    })
    deleteTimers.current.set(session.id, setTimeout(() => {
      deleteTimers.current.delete(session.id)
      dismissToast(toastId)
      setHiddenIds((current) => current.filter((id) => id !== session.id))
      void deleteSession(session.id).catch(() => {
        pushToast({ message: 'Could not delete the session.', tone: 'warning', durationMs: 5000 })
      })
    }, 8000))
  }, [activeSessionId, sessions, hiddenIds, selectSession, pushToast, dismissToast, effectiveTitle, deleteSession])

  const handlePin = useCallback((sessionId: string) => {
    if (!activeAccountId) return
    // TODO(backend): PATCH /api/chat/sessions/{session_id}/pin — pins are local per account until then.
    setPins(togglePinnedSession(activeAccountId, sessionId))
    setMenuId(null)
  }, [activeAccountId])

  const handleNavKeyDown = (event: KeyboardEvent) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const ids = flatVisible.map((session) => session.id)
    if (ids.length === 0) return
    const currentIndex = ids.indexOf(activeSessionId ?? '')
    const nextIndex = event.key === 'ArrowDown'
      ? Math.min(ids.length - 1, currentIndex + 1)
      : Math.max(0, currentIndex - 1)
    const target = navRef.current?.querySelector<HTMLButtonElement>(`[data-session-row="${ids[nextIndex]}"]`)
    target?.focus()
  }

  const handleSignOut = () => {
    setAccountMenuOpen(false)
    clearAccountState()
    setAccounts(accounts, null)
  }

  const handleAddAccountClose = () => {
    setConnectOpen(false)
    void (async () => {
      try {
        const result = await api.listAccounts()
        const known = new Set(accounts.map((item) => item.id))
        const created = result.accounts.find((item) => !known.has(item.id))
        setAccounts(result.accounts, created?.id ?? result.active_account_id)
        if (created) await setActiveAccount(created.id)
      } catch { /* keep current accounts */ }
    })()
  }

  const profileStats = styleProfile
    ? `${styleProfile.corpus_statistics.total_sent_emails} sent emails · ${styleProfile.global_learned_rules.length} learned rules`
    : 'Calibrate voice'

  const renderRow = (session: Session) => {
    const isActive = session.id === activeSessionId
    const isRenaming = renamingId === session.id
    const meta = rowMeta(session)
    const title = effectiveTitle(session)
    const isPinned = pins.includes(session.id)
    return (
      <li key={session.id} className="relative">
        {isRenaming ? (
          <div className="px-2 py-1.5">
            <input
              ref={renameInputRef}
              value={renameDraft}
              onChange={(event) => setRenameDraft(event.target.value)}
              onBlur={() => void handleRenameCommit(session.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleRenameCommit(session.id)
                if (event.key === 'Escape') { setRenamingId(null); setRenameDraft('') }
              }}
              aria-label="Rename session"
              className="w-full rounded-card border border-foam/60 bg-cobalt px-2 py-1.5 text-[13px] text-paper focus:outline-none"
            />
          </div>
        ) : (
          <div className={cn('group flex items-start gap-1 rounded-card transition-colors', isActive ? 'bg-paper/10' : 'hover:bg-paper/[0.06]')}>
            <button
              type="button"
              data-session-row={session.id}
              onClick={() => { void selectSession(session.id); onClose?.() }}
              onDoubleClick={() => { setRenamingId(session.id); setRenameDraft(title) }}
              title={title}
              className="min-w-0 flex-1 px-2.5 py-2 text-left"
            >
              <span className="line-clamp-2 text-[13px] leading-snug text-paper">{title}</span>
              <span className="mt-1 flex items-center gap-1.5 font-mono text-[12px] text-paper-muted">
                {meta.recipientInitial ? (
                  <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-pill bg-paper/15 text-[12px] uppercase text-paper" title={meta.recipientName ?? undefined} aria-hidden>
                    {meta.recipientInitial}
                  </span>
                ) : null}
                <span className="truncate">{meta.recipientName ? `${meta.recipientName} · ` : ''}{formatRelativeTime(session.updatedAt)}</span>
                {meta.dot ? <span className={cn('ml-auto h-1.5 w-1.5 shrink-0 rounded-pill', meta.dot === 'ember' ? 'bg-ember' : 'bg-foam')} aria-label={meta.dot === 'ember' ? 'Awaiting approval' : 'Sent'} /> : null}
              </span>
            </button>
            <div className="shrink-0 pr-1 pt-1.5">
              <button
                type="button"
                aria-label={`Session actions for ${title}`}
                aria-haspopup="menu"
                aria-expanded={menuId === session.id}
                onClick={(event) => { event.stopPropagation(); setMenuId(menuId === session.id ? null : session.id) }}
                className={cn('inline-flex h-7 w-7 items-center justify-center rounded-pill text-paper-muted transition-opacity hover:bg-paper/10 hover:text-paper', menuId === session.id ? 'opacity-100' : 'opacity-0 focus-visible:opacity-100 group-hover:opacity-100')}
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
        {menuId === session.id ? (
          <div ref={menuRef} role="menu" aria-label="Session actions" className="absolute right-1 top-9 z-40 w-40 overflow-hidden rounded-card border border-hairline bg-cobalt-deep">
            <button type="button" role="menuitem" onClick={() => { setMenuId(null); setRenamingId(session.id); setRenameDraft(title) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-paper hover:bg-paper/10">
              <Pencil className="h-3.5 w-3.5" aria-hidden /> Rename
            </button>
            <button type="button" role="menuitem" onClick={() => handlePin(session.id)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-paper hover:bg-paper/10">
              {isPinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
              {isPinned ? 'Unpin' : 'Pin'}
            </button>
            <button type="button" role="menuitem" onClick={() => handleDelete(session)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-paper hover:bg-ember/15">
              <Trash2 className="h-3.5 w-3.5 text-ember" aria-hidden /> Delete
            </button>
          </div>
        ) : null}
      </li>
    )
  }

  /* ── Collapsed 56px icon rail ─────────────────────────────────────────── */
  if (collapsed && !fullscreen) {
    return (
      <aside className="flex h-full w-14 shrink-0 flex-col items-center border-r border-hairline bg-cobalt-deep py-3" aria-label="Session rail (collapsed)" data-tour="rail">
        <Wordmark to="/" size="sm" className="text-base" />
        <div className="mt-4 flex flex-col items-center gap-2">
          <IconButton label="New session" shortcut="⌘N" onClick={() => void createSession()}>
            <MessageSquarePlus className="h-4 w-4" />
          </IconButton>
          <IconButton label="Search sessions" shortcut="⌘K" onClick={() => setPaletteOpen(true)}>
            <Search className="h-4 w-4" />
          </IconButton>
          <IconButton label="Expand sidebar" onClick={onToggleCollapsed}>
            <PanelLeftOpen className="h-4 w-4" />
          </IconButton>
        </div>
        <div className="mt-4 flex flex-1 flex-col items-center gap-1.5 overflow-y-auto scrollbar-none">
          {sessions.slice(0, 8).map((session) => (
            <button
              key={session.id}
              type="button"
              onClick={() => void selectSession(session.id)}
              title={effectiveTitle(session)}
              aria-label={effectiveTitle(session)}
              className={cn('inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-pill font-mono text-[12px] uppercase', session.id === activeSessionId ? 'bg-paper text-ink' : 'bg-paper/10 text-paper-muted hover:bg-paper/20 hover:text-paper')}
            >
              {effectiveTitle(session).charAt(0)}
            </button>
          ))}
        </div>
        <div className="flex flex-col items-center gap-2">
          <IconButton label="Style Profile" onClick={() => setProfileOpen(true)}>
            <UserRound className="h-4 w-4" />
          </IconButton>
          {account ? <Avatar initials={account.initials} size="sm" /> : null}
        </div>
      </aside>
    )
  }

  return (
    <aside className={cn('flex h-full shrink-0 flex-col border-r border-hairline bg-cobalt-deep', fullscreen ? 'w-full' : 'w-full')} aria-label="Session rail" data-tour="rail">
      <div className="flex h-[60px] items-center justify-between border-b border-hairline px-4">
        <Wordmark to="/" size="sm" />
        <div className="flex items-center gap-1">
          {fullscreen && onClose ? (
            <IconButton label="Close sessions" onClick={onClose}><X className="h-4 w-4" /></IconButton>
          ) : (
            <IconButton label="Collapse sidebar" onClick={onToggleCollapsed}><PanelLeftClose className="h-4 w-4" /></IconButton>
          )}
        </div>
      </div>

      <div className="px-3 pt-3">
        <button
          type="button"
          onClick={() => { void createSession(); onClose?.() }}
          className="flex w-full items-center justify-center gap-2 rounded-pill bg-paper px-4 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-foam"
        >
          <MessageSquarePlus className="h-4 w-4" aria-hidden /> New session
        </button>
        <div className="relative mt-2.5 flex items-center">
          <Search className="pointer-events-none absolute left-3 h-3.5 w-3.5 text-paper-muted" aria-hidden />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search sessions"
            aria-label="Search sessions"
            className="w-full rounded-pill border border-hairline bg-cobalt py-2 pl-9 pr-3 text-[12px] text-paper placeholder:text-paper-muted focus:border-foam/70 focus:outline-none"
          />
          {searchQuery ? (
            <button type="button" onClick={() => setSearchQuery('')} aria-label="Clear search" className="absolute right-3 text-paper-muted hover:text-paper">
              <X className="h-3 w-3" />
            </button>
          ) : null}
        </div>
      </div>

      <nav ref={navRef} onKeyDown={handleNavKeyDown} className="scrollbar-none mt-3 flex-1 overflow-y-auto px-2 pb-3" aria-label="Session history">
        {flatVisible.length === 0 ? (
          <p className="px-3 py-6 text-center text-[12px] text-paper-muted">{searchQuery ? 'No matching sessions' : 'No sessions yet'}</p>
        ) : grouped.map((group) => (
          <div key={group.name} className="mb-3">
            <button
              type="button"
              onClick={() => setCollapsedGroups((current) => ({ ...current, [group.name]: !current[group.name] }))}
              aria-expanded={!collapsedGroups[group.name]}
              className="flex w-full items-center gap-1.5 px-2.5 pb-1.5 font-mono text-[12px] uppercase tracking-[0.14em] text-paper-muted hover:text-paper"
            >
              {group.name === 'Pinned' ? <Pin className="h-3 w-3" aria-hidden /> : null}
              {group.name}
              <span className={cn('ml-auto transition-transform', collapsedGroups[group.name] && '-rotate-90')} aria-hidden>▾</span>
            </button>
            {!collapsedGroups[group.name] ? <ul className="space-y-0.5">{group.items.map(renderRow)}</ul> : null}
          </div>
        ))}
      </nav>

      {/* Style Profile row — real stats, never a fake percentage. */}
      <div className="border-t border-hairline px-3 pt-2.5">
        <button
          type="button"
          onClick={() => { setProfileOpen(true); onClose?.() }}
          className="flex w-full items-center gap-2.5 rounded-card border border-hairline px-3 py-2 text-left transition-colors hover:border-paper-label hover:bg-paper/[0.06]"
        >
          <UserRound className="h-4 w-4 shrink-0 text-foam" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] text-paper">Style Profile</span>
            <span className="block truncate font-mono text-[12px] text-paper-muted">{profileStats}</span>
          </span>
        </button>
      </div>

      {/* Account card */}
      <div className="relative p-3" ref={accountMenuRef}>
        {accountMenuOpen ? (
          <div role="menu" aria-label="Account menu" className="absolute bottom-[calc(100%+6px)] left-3 right-3 z-40 overflow-hidden rounded-card border border-hairline bg-cobalt-deep">
            <p className="px-3 py-2 font-mono text-[12px] uppercase tracking-[0.14em] text-paper-muted">Switch account</p>
            {accounts.map((item) => (
              <button
                key={item.id}
                type="button"
                role="menuitem"
                onClick={() => { setAccountMenuOpen(false); void setActiveAccount(item.id) }}
                className={cn('flex w-full items-center gap-2.5 px-3 py-2 text-left', item.id === activeAccountId ? 'bg-paper/10' : 'hover:bg-paper/[0.06]')}
              >
                <Avatar initials={item.initials} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] text-paper">{item.name || item.email}</span>
                  <span className="block truncate font-mono text-[12px] text-paper-muted">{item.email}</span>
                </span>
                {item.id === activeAccountId ? <Check className="h-4 w-4 shrink-0 text-foam" aria-hidden /> : null}
              </button>
            ))}
            <div className="border-t border-hairline" />
            <button type="button" role="menuitem" onClick={() => { setAccountMenuOpen(false); setConnectOpen(true) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-foam hover:bg-foam/10">
              <Plus className="h-4 w-4" aria-hidden /> Add account
            </button>
            <button type="button" role="menuitem" onClick={() => { setAccountMenuOpen(false); setProfileOpen(true) }} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-paper hover:bg-paper/[0.06]">
              <UserRound className="h-4 w-4" aria-hidden /> Style Profile
            </button>
            <button type="button" role="menuitem" onClick={handleSignOut} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] text-paper hover:bg-ember/15">
              <LogOut className="h-4 w-4 text-ember" aria-hidden /> Sign out
            </button>
          </div>
        ) : null}
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={accountMenuOpen}
          onClick={() => setAccountMenuOpen((value) => !value)}
          disabled={!account}
          className="flex w-full items-center gap-2.5 rounded-card border border-hairline bg-cobalt p-2.5 text-left transition-colors hover:border-paper-label disabled:opacity-50"
        >
          {account ? (
            <>
              <span className="relative shrink-0">
                <Avatar initials={account.initials} size="sm" />
                <span className={cn('absolute -right-0.5 -top-0.5 h-2 w-2 rounded-pill border border-cobalt', account.mailboxConnected ? 'bg-foam' : 'bg-ember')} aria-label={account.mailboxConnected ? 'Synced' : 'Needs unlock'} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] font-medium text-paper">{account.name || account.email}</span>
                <span className="block truncate font-mono text-[12px] text-paper-muted" title={account.email}>{account.email}</span>
              </span>
              <span className="shrink-0 rounded-pill border border-hairline px-2 py-0.5 font-mono text-[12px] text-paper-muted">{PROVIDER_LABEL[account.provider]}</span>
              <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-paper-muted" aria-hidden />
            </>
          ) : (
            <span className="text-[12px] text-paper-muted">No account selected</span>
          )}
        </button>
      </div>
      <ConnectGmailModal isOpen={connectOpen} onClose={handleAddAccountClose} />
    </aside>
  )
}

export default SessionRail