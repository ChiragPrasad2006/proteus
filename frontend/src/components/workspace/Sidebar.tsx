import { Check, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Pencil, Search, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AccountSwitcher } from '@/components/workspace/AccountSwitcher'
import { Button } from '@/components/ui/Button'
import { Wordmark } from '@/components/ui/Wordmark'
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
  const styleProfile = useAppStore((s) => s.styleProfile)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions
    const query = searchQuery.toLowerCase()
    return sessions.filter((session) => session.title.toLowerCase().includes(query) || (session.preview ?? '').toLowerCase().includes(query))
  }, [sessions, searchQuery])
  const grouped = useMemo(() => {
    const map = new Map<string, Session[]>()
    for (const session of filteredSessions) { const key = sessionBucket(session.updatedAt); const list = map.get(key) ?? []; list.push(session); map.set(key, list) }
    return BUCKET_ORDER.filter((bucket) => map.has(bucket)).map((bucket) => ({ bucket, items: map.get(bucket)! }))
  }, [filteredSessions])
  useEffect(() => { if (renamingId && renameInputRef.current) { renameInputRef.current.focus(); renameInputRef.current.select() } }, [renamingId])
  const handleRenameCancel = useCallback(() => { setRenamingId(null); setRenameDraft('') }, [])
  const handleDeleteCancel = useCallback(() => setDeletingId(null), [])
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchInputRef.current?.focus() }
      if (event.key === 'Escape') {
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
  }, [searchQuery, renamingId, deletingId, handleRenameCancel, handleDeleteCancel])
  const handleRenameStart = useCallback((session: Session, event: React.MouseEvent) => { event.stopPropagation(); setRenamingId(session.id); setRenameDraft(session.title) }, [])
  const handleRenameCommit = useCallback(async (sessionId: string) => { const title = renameDraft.trim(); if (title && title.length <= 100) { try { await renameSession(sessionId, title) } catch {} } setRenamingId(null); setRenameDraft('') }, [renameDraft, renameSession])
  const handleRenameKeyDown = useCallback((event: React.KeyboardEvent, sessionId: string) => { if (event.key === 'Enter') void handleRenameCommit(sessionId); if (event.key === 'Escape') handleRenameCancel() }, [handleRenameCommit, handleRenameCancel])
  const handleDeleteConfirm = useCallback(async (sessionId: string) => { try { await deleteSession(sessionId) } catch {} setDeletingId(null) }, [deleteSession])
  return (
    <aside className={cn('relative z-30 flex shrink-0 flex-col border-r border-hairline bg-cobalt-deep transition-[width] duration-300 ease-proteus', collapsed ? 'w-[76px]' : 'w-[260px]')}>
      <div className={cn('flex h-[68px] items-center border-b border-hairline', collapsed ? 'justify-center px-2' : 'justify-between px-4')}><Wordmark to="/" size="sm" /><button type="button" onClick={toggleSidebar} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} className={cn('inline-flex h-8 w-8 items-center justify-center rounded-pill text-paper-label hover:bg-paper/10 hover:text-paper', collapsed && 'hidden')}><PanelLeftClose className="h-4 w-4" /></button></div>
      {collapsed ? <div className="flex justify-center py-3"><button type="button" onClick={toggleSidebar} aria-label="Expand sidebar" className="inline-flex h-9 w-9 items-center justify-center rounded-pill border border-hairline text-paper-muted hover:text-paper"><PanelLeftOpen className="h-4 w-4" /></button></div> : null}
      <div className={cn('pt-4', collapsed ? 'px-2' : 'px-3')}>{collapsed ? <button type="button" onClick={createSession} aria-label="New session" className="mx-auto flex h-10 w-10 items-center justify-center rounded-pill bg-paper text-ink hover:-translate-y-px"><MessageSquarePlus className="h-4 w-4" /></button> : <Button onClick={createSession} className="w-full" leftIcon={<MessageSquarePlus className="h-4 w-4" />}>+ New session</Button>}</div>
      {!collapsed ? <div className="mt-3 px-3"><div className="relative flex items-center"><Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-paper-label" /><input ref={searchInputRef} type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.stopPropagation()} placeholder="Search sessions" className="w-full rounded-pill border border-hairline bg-cobalt py-2 pl-9 pr-11 text-[12px] text-paper placeholder:text-paper-label focus:border-foam/70 focus:outline-none" />{searchQuery ? <button type="button" onClick={() => { setSearchQuery(''); searchInputRef.current?.focus() }} className="absolute right-3 top-1/2 -translate-y-1/2 text-paper-label hover:text-paper" aria-label="Clear search"><X className="h-3 w-3" /></button> : <kbd className="absolute right-3 top-1/2 -translate-y-1/2 font-mono text-[8px] text-paper-label">⌘K</kbd>}</div></div> : null}
      <nav className="scrollbar-none mt-4 flex-1 overflow-y-auto px-2 pb-4" aria-label="Session history">{!filteredSessions.length && searchQuery ? <div className="px-2.5 py-6 text-center text-[12px] text-paper-label">No matching sessions</div> : grouped.map(({ bucket, items }) => <div key={bucket} className="mb-4">{!collapsed ? <p className="px-2.5 pb-2 font-mono text-[9px] uppercase tracking-[0.18em] text-paper-label">{bucket}</p> : <div className="mx-auto mb-2 h-px w-6 bg-hairline" />}<ul className="space-y-0.5">{items.map((session) => { const isActive = session.id === activeSessionId; const isRenaming = renamingId === session.id; const isDeleting = deletingId === session.id; return <li key={session.id}>{isRenaming ? <div className="px-2.5 py-1.5"><input ref={renameInputRef} type="text" value={renameDraft} onChange={(e) => setRenameDraft(e.target.value)} onBlur={() => void handleRenameCommit(session.id)} onKeyDown={(e) => handleRenameKeyDown(e, session.id)} className="w-full rounded-sm border border-foam/60 bg-cobalt px-2 py-1 text-[12px] text-paper focus:outline-none" autoFocus /></div> : isDeleting ? <div className="flex items-center gap-2 px-2.5 py-1.5"><span className="flex-1 text-[12px] text-paper-muted">Delete?</span><button type="button" onClick={(e) => { e.stopPropagation(); void handleDeleteConfirm(session.id) }} className="inline-flex h-6 w-6 items-center justify-center rounded-pill border border-ember/60 text-ember" aria-label="Confirm delete"><Check className="h-3 w-3" /></button><button type="button" onClick={(e) => { e.stopPropagation(); handleDeleteCancel() }} className="inline-flex h-6 w-6 items-center justify-center rounded-pill border border-hairline text-paper-label" aria-label="Cancel delete"><X className="h-3 w-3" /></button></div> : <button type="button" onClick={() => void selectSession(session.id)} title={collapsed ? session.title : undefined} className={cn('group relative w-full rounded-sm text-left transition-colors', collapsed ? 'flex justify-center px-0 py-2.5' : 'px-2.5 py-2', isActive ? 'bg-paper/10' : 'hover:bg-paper/[0.06]')}>{isActive ? <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 bg-foam" /> : null}{collapsed ? <span className={cn('inline-flex h-8 w-8 items-center justify-center rounded-pill border font-mono text-[9px] uppercase', isActive ? 'border-foam/50 bg-foam/10 text-foam' : 'border-hairline text-paper-label')}>{session.title.slice(0, 2)}</span> : <><span className={cn('block truncate text-[12px] leading-snug', isActive ? 'text-paper' : 'text-paper-muted group-hover:text-paper')}>{session.title}</span><span className="mt-0.5 block truncate font-mono text-[9px] text-paper-label/75">{session.preview}</span><span className="mt-1 block font-mono text-[8px] uppercase tracking-wider text-paper-label/60">{formatRelativeTime(session.updatedAt)}</span><div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"><button type="button" onClick={(e) => handleRenameStart(session, e)} className="inline-flex h-6 w-6 items-center justify-center rounded-pill border border-hairline text-paper-label hover:text-paper" aria-label="Rename session"><Pencil className="h-3 w-3" /></button><button type="button" onClick={(e) => { e.stopPropagation(); setDeletingId(session.id) }} className="inline-flex h-6 w-6 items-center justify-center rounded-pill border border-hairline text-paper-label hover:border-ember hover:text-ember" aria-label="Delete session"><Trash2 className="h-3 w-3" /></button></div></>}</button>}</li> })}</ul></div>)}</nav>
      <div className={cn('border-t border-hairline p-3', collapsed && 'px-2')}>{!collapsed ? <p className="mb-2 px-1 font-mono text-[9px] uppercase tracking-[0.18em] text-paper-label">Account</p> : null}<AccountSwitcher collapsed={collapsed} /><button type="button" onClick={() => setProfileOpen((value) => !value)} className={cn('mt-2 w-full rounded-sm border border-hairline px-3 py-2 text-left text-[12px] text-paper-muted hover:bg-paper/[0.06] hover:text-paper', collapsed && 'px-0 text-center')}>{collapsed ? 'SP' : 'Style Profile'}</button>{profileOpen && !collapsed ? <div className="mt-2 max-h-48 overflow-y-auto rounded-sm border border-hairline bg-cobalt p-3 text-[11px] leading-relaxed text-paper-muted">{styleProfile ? <pre className="whitespace-pre-wrap font-mono text-[9px]">{JSON.stringify(styleProfile, null, 2)}</pre> : <p>No local style profile yet. Connect a mailbox and build the profile to see it here.</p>}</div> : null}</div>
    </aside>
  )
}
export default Sidebar
