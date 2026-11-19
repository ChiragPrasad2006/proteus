import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Search, Pencil, Trash2, Check, X } from 'lucide-react'
import { useMemo, useState, useRef, useEffect, useCallback } from 'react'
import { AccountSwitcher } from '@/components/workspace/AccountSwitcher'
import { Wordmark } from '@/components/ui/Wordmark'
import { Button } from '@/components/ui/Button'
import { formatRelativeTime, sessionBucket } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/stores/useAppStore'
import type { Session } from '@/types'

const BUCKET_ORDER = ['Today', 'Previous 7 Days', 'Earlier'] as const

export function Sidebar() {
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const sessions = useAppStore((s) => s.sessions)
  const activeSessionId = useAppStore((s) => s.activeSessionId)
  const selectSession = useAppStore((s) => s.selectSession)
  const createSession = useAppStore((s) => s.createSession)
  const renameSession = useAppStore((s) => s.renameSession)
  const deleteSession = useAppStore((s) => s.deleteSession)

  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Filter sessions based on search query
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions
    const query = searchQuery.toLowerCase()
    return sessions.filter((session) => {
      const title = session.title.toLowerCase()
      const preview = (session.preview ?? '').toLowerCase()
      return title.includes(query) || preview.includes(query)
    })
  }, [sessions, searchQuery])

  // Group filtered sessions
  const grouped = useMemo(() => {
    const map = new Map<string, Session[]>()
    for (const session of filteredSessions) {
      const key = sessionBucket(session.updatedAt)
      const list = map.get(key) ?? []
      list.push(session)
      map.set(key, list)
    }
    return BUCKET_ORDER.filter((b) => map.has(b)).map((b) => ({
      bucket: b,
      items: map.get(b)!,
    }))
  }, [filteredSessions])

  // Focus rename input when it appears
  useEffect(() => {
    if (renamingId && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [renamingId])

  // Focus search input when Ctrl+K is pressed
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
      if (e.key === 'Escape') {
        if (searchQuery) {
          setSearchQuery('')
          searchInputRef.current?.blur()
        } else if (renamingId) {
          handleRenameCancel()
        } else if (deletingId) {
          handleDeleteCancel()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [searchQuery, renamingId, deletingId])

  const handleRenameStart = useCallback((session: Session, e: React.MouseEvent) => {
    e.stopPropagation()
    setRenamingId(session.id)
    setRenameDraft(session.title)
  }, [])

  const handleRenameCommit = useCallback(async (sessionId: string) => {
    const title = renameDraft.trim()
    if (title && title.length <= 100) {
      try {
        await renameSession(sessionId, title)
      } catch {}
    }
    setRenamingId(null)
    setRenameDraft('')
  }, [renameDraft, renameSession])

  const handleRenameCancel = useCallback(() => {
    setRenamingId(null)
    setRenameDraft('')
  }, [])

  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent, sessionId: string) => {
    if (e.key === 'Enter') handleRenameCommit(sessionId)
    if (e.key === 'Escape') handleRenameCancel()
  }, [handleRenameCommit, handleRenameCancel])

  const handleDeleteConfirm = useCallback(async (sessionId: string) => {
    try {
      await deleteSession(sessionId)
    } catch {}
    setDeletingId(null)
  }, [deleteSession])

  const handleDeleteCancel = useCallback(() => {
    setDeletingId(null)
  }, [])

  // Check if any sessions match the search
  const hasMatchingSessions = filteredSessions.length > 0

  return (
    <aside
      className={cn(
        'relative z-30 flex shrink-0 flex-col border-r border-hairline bg-ink/80 backdrop-blur-xl',
        'transition-[width] duration-300 ease-proteus',
        collapsed ? 'w-[76px]' : 'w-[280px]',
      )}
    >
      {/* Brand */}
      <div
        className={cn(
          'flex h-[68px] items-center border-b border-hairline',
          collapsed ? 'justify-center px-2' : 'justify-between px-4',
        )}
      >
        {collapsed ? (
          <Wordmark to="/" size="sm" showIcon />
        ) : (
          <Wordmark to="/" size="sm" />
        )}
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={cn(
            'inline-flex h-8 w-8 items-center justify-center rounded-full text-fg-faint transition-colors duration-300 ease-proteus hover:bg-white/[0.06] hover:text-fg',
            collapsed && 'hidden',
          )}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {collapsed ? (
        <div className="flex justify-center py-3">
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label="Expand sidebar"
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-hairline text-fg-muted transition-colors duration-300 ease-proteus hover:border-hairline-strong hover:text-fg"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {/* New session */}
      <div className={cn('pt-4', collapsed ? 'px-2' : 'px-3')}>
        {collapsed ? (
          <button
            type="button"
            onClick={createSession}
            aria-label="New session"
            className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-accent text-ink transition-all duration-300 ease-proteus hover:bg-accent-dim"
          >
            <MessageSquarePlus className="h-4.5 w-4.5" />
          </button>
        ) : (
          <Button
            onClick={createSession}
            className="w-full"
            leftIcon={<MessageSquarePlus className="h-4 w-4" />}
          >
            New session
          </Button>
        )}
      </div>

      {/* Search (expanded only) */}
      {!collapsed ? (
        <div className="mt-3 px-3">
          <div className="relative flex items-center gap-2 rounded-xl border border-hairline bg-white/[0.03] px-3 py-2">
            <Search className="h-3.5 w-3.5 text-fg-faint absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
              placeholder="Search sessions"
              className="w-full pl-9 pr-8 bg-transparent text-[13px] text-fg placeholder:text-fg-faint focus:outline-none"
            />
            {searchQuery ? (
              <button
                type="button"
                onClick={() => { setSearchQuery(''); searchInputRef.current?.focus(); }}
                className="absolute right-3 top-1/2 -translate-y-1/2 inline-flex h-5 w-5 items-center justify-center rounded text-fg-faint hover:text-fg hover:bg-white/[0.06] transition-colors"
                aria-label="Clear search"
              >
                <X className="h-3 w-3" />
              </button>
            ) : (
              <kbd className="absolute right-3 top-1/2 -translate-y-1/2 rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] text-fg-faint">
                ⌘K
              </kbd>
            )}
          </div>
        </div>
      ) : null}

      {/* Sessions history */}
      <nav className="scrollbar-none mt-4 flex-1 overflow-y-auto px-2 pb-4">
        {!hasMatchingSessions && searchQuery ? (
          <div className="px-2.5 py-6 text-center text-[13px] text-fg-faint">
            No matching sessions
          </div>
        ) : (
          grouped.map(({ bucket, items }) => (
            <div key={bucket} className="mb-4">
              {!collapsed ? (
                <p className="px-2.5 pb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
                  {bucket}
                </p>
              ) : (
                <div className="mx-auto mb-2 h-px w-6 bg-hairline" />
              )}

              <ul className="space-y-0.5">
                {items.map((session) => {
                  const isActive = session.id === activeSessionId
                  const isRenaming = renamingId === session.id
                  const isDeleting = deletingId === session.id

                  return (
                    <li key={session.id}>
                      {isRenaming ? (
                        <div className="px-2.5 py-1.5">
                          <input
                            ref={renameInputRef}
                            type="text"
                            value={renameDraft}
                            onChange={(e) => setRenameDraft(e.target.value)}
                            onBlur={() => handleRenameCommit(session.id)}
                            onKeyDown={(e) => handleRenameKeyDown(e, session.id)}
                            className="w-full rounded-lg border border-accent/40 bg-ink/60 px-2 py-1 text-[13px] text-fg focus:outline-none"
                            autoFocus
                          />
                        </div>
                      ) : isDeleting ? (
                        <div className="px-2.5 py-1.5 flex items-center gap-2">
                          <span className="flex-1 text-[13px] text-fg-muted">Delete session?</span>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteConfirm(session.id); }}
                            className="inline-flex h-6 w-6 items-center justify-center rounded border border-accent/40 text-accent transition-colors hover:bg-accent/10"
                            aria-label="Confirm delete"
                          >
                            <Check className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteCancel(); }}
                            className="inline-flex h-6 w-6 items-center justify-center rounded border border-hairline text-fg-faint transition-colors hover:bg-white/[0.03]"
                            aria-label="Cancel delete"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => selectSession(session.id)}
                          title={collapsed ? session.title : undefined}
                          className={cn(
                            'group relative w-full rounded-[14px] text-left transition-colors duration-300 ease-proteus',
                            collapsed ? 'flex justify-center px-0 py-2.5' : 'px-2.5 py-2',
                            isActive ? 'bg-white/[0.06]' : 'hover:bg-white/[0.035]',
                          )}
                        >
                          {isActive ? (
                            <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent" />
                          ) : null}

                          {collapsed ? (
                            <span
                              className={cn(
                                'inline-flex h-8 w-8 items-center justify-center rounded-full border text-[10px] font-mono uppercase',
                                isActive
                                  ? 'border-accent/40 bg-accent/10 text-accent'
                                  : 'border-hairline text-fg-faint',
                              )}
                            >
                              {session.title.slice(0, 2)}
                            </span>
                          ) : (
                            <>
                              <span
                                className={cn(
                                  'block truncate min-w-0 flex-1 text-[13px] leading-snug',
                                  isActive ? 'text-fg' : 'text-fg-muted group-hover:text-fg',
                                )}
                              >
                                {session.title}
                              </span>
                              <span className="mt-0.5 flex items-center gap-2 shrink-0">
                                <span className="truncate text-[11px] text-fg-faint">
                                  {session.preview}
                                </span>
                              </span>
                              <span className="mt-1 block font-mono text-[10px] text-fg-faint/70 shrink-0">
                                {formatRelativeTime(session.updatedAt)}
                              </span>
                              {/* Action buttons on hover */}
                              <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200 ease-proteus">
                                <button
                                  type="button"
                                  onClick={(e) => handleRenameStart(session, e)}
                                  className="inline-flex h-6 w-6 items-center justify-center rounded border border-hairline text-fg-faint transition-colors hover:border-hairline-strong hover:text-fg hover:bg-white/[0.03]"
                                  aria-label="Rename session"
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); setDeletingId(session.id); }}
                                  className="inline-flex h-6 w-6 items-center justify-center rounded border border-hairline text-fg-faint transition-colors hover:border-red/40 hover:text-red hover:bg-red/[0.03]"
                                  aria-label="Delete session"
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              </div>
                            </>
                          )}
                        </button>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )))
        }
      </nav>

      {/* Pinned account switcher */}
      <div className={cn('border-t border-hairline p-3', collapsed && 'px-2')}>
        {!collapsed ? (
          <p className="mb-2 px-1 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
            Account
          </p>
        ) : null}
        <AccountSwitcher collapsed={collapsed} />
      </div>
    </aside>
  )
}

export default Sidebar