import { ArrowLeft, FileText, Keyboard, MessageSquarePlus, Search, UserRound, Zap } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { isAutoSendConfirmed } from '@/lib/localAdapter'
import { deriveSessionTitle } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'

interface PaletteItem {
  id: string
  label: string
  hint?: string
  icon: ReactNode
  run: () => void
}

/** Cmd/Ctrl+K command palette: sessions + workspace commands. */
export function CommandPalette() {
  const open = useWorkspaceUI((state) => state.paletteOpen)
  const setOpen = useWorkspaceUI((state) => state.setPaletteOpen)
  const setProfileOpen = useWorkspaceUI((state) => state.setProfileOpen)
  const setShortcutsOpen = useWorkspaceUI((state) => state.setShortcutsOpen)
  const setAutoSendConfirmOpen = useWorkspaceUI((state) => state.setAutoSendConfirmOpen)
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const selectSession = useAppStore((state) => state.selectSession)
  const createSession = useAppStore((state) => state.createSession)
  const accounts = useAppStore((state) => state.accounts)
  const activeAccountId = useAppStore((state) => state.activeAccountId)
  const setActiveAccount = useAppStore((state) => state.setActiveAccount)
  const autoSend = useAppStore((state) => state.autoSend)
  const setAutoSend = useAppStore((state) => state.setAutoSend)
  const account = useActiveAccount()

  const [query, setQuery] = useState('')
  const [view, setView] = useState<'main' | 'accounts'>('main')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setView('main')
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  const close = () => setOpen(false)

  const items = useMemo<PaletteItem[]>(() => {
    if (view === 'accounts') {
      return accounts.map((item) => ({
        id: `account-${item.id}`,
        label: item.name || item.email,
        hint: item.id === activeAccountId ? 'current' : item.email,
        icon: <UserRound className="h-4 w-4" aria-hidden />,
        run: () => { close(); void setActiveAccount(item.id) },
      }))
    }
    const commands: PaletteItem[] = [
      { id: 'new-session', label: 'New session', hint: '⌘N', icon: <MessageSquarePlus className="h-4 w-4" aria-hidden />, run: () => { close(); void createSession() } },
      { id: 'switch-account', label: 'Switch account', icon: <UserRound className="h-4 w-4" aria-hidden />, run: () => { setView('accounts'); setQuery(''); setActiveIndex(0) } },
      { id: 'style-profile', label: 'Open Style Profile', icon: <FileText className="h-4 w-4" aria-hidden />, run: () => { close(); setProfileOpen(true) } },
      {
        id: 'toggle-autosend',
        label: autoSend ? 'Turn Auto-Send off' : 'Turn Auto-Send on',
        icon: <Zap className="h-4 w-4" aria-hidden />,
        run: () => {
          close()
          if (autoSend) { setAutoSend(false); return }
          if (account && isAutoSendConfirmed(account.id)) setAutoSend(true)
          else setAutoSendConfirmOpen(true)
        },
      },
      { id: 'shortcuts', label: 'Keyboard shortcuts', hint: '?', icon: <Keyboard className="h-4 w-4" aria-hidden />, run: () => { close(); setShortcutsOpen(true) } },
    ]
    const lowered = query.trim().toLowerCase()
    const sessionItems: PaletteItem[] = sessions
      .filter((session) => {
        if (!lowered) return true
        const title = session.title?.trim() || deriveSessionTitle(session.preview || '')
        return title.toLowerCase().includes(lowered)
      })
      .slice(0, 8)
      .map((session) => ({
        id: `session-${session.id}`,
        label: session.title?.trim() || deriveSessionTitle(session.preview || '') || 'New session',
        hint: session.id === activeSessionId ? 'current' : 'session',
        icon: <Search className="h-4 w-4" aria-hidden />,
        run: () => { close(); void selectSession(session.id) },
      }))
    const filteredCommands = lowered ? commands.filter((command) => command.label.toLowerCase().includes(lowered)) : commands
    return [...filteredCommands, ...sessionItems]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, query, sessions, accounts, activeAccountId, activeSessionId, autoSend, account])

  useEffect(() => { setActiveIndex(0) }, [query, view])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close() }
      else if (event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex((index) => Math.min(items.length - 1, index + 1)) }
      else if (event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex((index) => Math.max(0, index - 1)) }
      else if (event.key === 'Enter') { event.preventDefault(); items[activeIndex]?.run() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, items, activeIndex])

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center bg-ink/70 px-4 pt-[12svh]" onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" className="w-full max-w-lg overflow-hidden rounded-card border border-hairline bg-cobalt-deep">
        <div className="flex items-center gap-2.5 border-b border-hairline px-4">
          {view === 'accounts' ? (
            <button type="button" onClick={() => { setView('main'); setQuery('') }} aria-label="Back to commands" className="text-paper-muted hover:text-paper">
              <ArrowLeft className="h-4 w-4" />
            </button>
          ) : (
            <Search className="h-4 w-4 shrink-0 text-paper-muted" aria-hidden />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={view === 'accounts' ? 'Choose an account…' : 'Search sessions or type a command…'}
            aria-label="Command palette search"
            className="w-full bg-transparent py-3.5 text-[14px] text-paper placeholder:text-paper-muted focus:outline-none"
          />
          <kbd className="shrink-0 rounded-[2px] border border-hairline px-1.5 py-0.5 font-mono text-[12px] text-paper-muted">esc</kbd>
        </div>
        <ul ref={listRef} role="listbox" aria-label="Commands" className="max-h-[46svh] overflow-y-auto p-1.5">
          {items.length === 0 ? (
            <li className="px-3 py-6 text-center text-[13px] text-paper-muted">No matches</li>
          ) : items.map((item, index) => (
            <li key={item.id} role="option" aria-selected={index === activeIndex}>
              <button
                type="button"
                data-index={index}
                onClick={item.run}
                onMouseEnter={() => setActiveIndex(index)}
                className={cn('flex w-full items-center gap-3 rounded-card px-3 py-2.5 text-left', index === activeIndex ? 'bg-paper/10' : 'hover:bg-paper/5')}
              >
                <span className="shrink-0 text-paper-muted">{item.icon}</span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-paper">{item.label}</span>
                {item.hint ? <span className="shrink-0 font-mono text-[12px] text-paper-muted">{item.hint}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default CommandPalette