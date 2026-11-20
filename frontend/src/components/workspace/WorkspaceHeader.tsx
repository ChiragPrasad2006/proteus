import { Cpu, PanelLeftOpen, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Toggle } from '@/components/ui/Toggle'
import { useRuntimeStatus } from '@/hooks/useHealth'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'

const STATE_STYLE = {
  online: { dot: 'bg-foam', text: 'text-foam', ring: 'shadow-[0_0_0_3px_rgba(201,240,227,0.14)]' },
  loading: { dot: 'bg-paper-muted', text: 'text-paper-muted', ring: '' },
  offline: { dot: 'bg-ember', text: 'text-ember', ring: '' },
} as const

export function WorkspaceHeader() {
  const sessions = useAppStore((s) => s.sessions)
  const activeSessionId = useAppStore((s) => s.activeSessionId)
  const renameSession = useAppStore((s) => s.renameSession)
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed)
  const autoSend = useAppStore((s) => s.autoSend)
  const setAutoSend = useAppStore((s) => s.setAutoSend)
  const account = useActiveAccount()
  const session = sessions?.find((s) => s.id === activeSessionId) ?? sessions?.[0] ?? null
  const sessionTitle = session?.title ?? 'New session'
  const [editing, setEditing] = useState(false)
  const [draftTitle, setDraftTitle] = useState(sessionTitle)
  useEffect(() => setDraftTitle(sessionTitle), [session?.id, sessionTitle])
  const runtime = useRuntimeStatus('Qwen3:8B')
  const style = STATE_STYLE[runtime.state]
  const commitTitle = () => {
    const next = draftTitle.trim()
    if (session && next && next !== session.title) renameSession(session.id, next)
    else setDraftTitle(sessionTitle)
    setEditing(false)
  }
  return (
    <header className="sticky top-0 z-20 border-b border-hairline bg-cobalt-deep">
      <div className="flex h-[68px] items-center gap-3 px-4 lg:px-5">
        {sidebarCollapsed ? <button type="button" onClick={toggleSidebar} aria-label="Expand sidebar" className="hidden h-9 w-9 items-center justify-center rounded-pill border border-hairline text-paper-muted hover:text-paper lg:inline-flex"><PanelLeftOpen className="h-4 w-4" /></button> : null}
        <div className="min-w-0 flex-1">
          {editing ? <input autoFocus value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} onBlur={commitTitle} onKeyDown={(e) => { if (e.key === 'Enter') commitTitle(); if (e.key === 'Escape') { setDraftTitle(sessionTitle); setEditing(false) } }} className="w-full max-w-lg rounded-sm border border-foam/50 bg-cobalt px-2.5 py-1 font-display text-lg text-paper focus:outline-none" /> : <button type="button" onClick={() => session && setEditing(true)} disabled={!session} className="group flex min-w-0 items-center gap-2 text-left disabled:cursor-default"><h1 className="truncate font-display text-lg font-normal leading-tight text-paper">{sessionTitle}</h1>{session ? <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-paper-label opacity-0 transition-opacity group-hover:opacity-100">rename</span> : null}</button>}
          <p className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-[0.1em] text-paper-label">{account?.email ?? 'Mailbox setup required'}</p>
        </div>
        <div className="hidden items-center gap-2 rounded-pill border border-hairline px-3 py-1.5 sm:flex" title={runtime.detail}>
          <span className="relative flex h-2 w-2">{runtime.state === 'online' ? <span className={cn('absolute inline-flex h-full w-full animate-pulse-ring rounded-full', style.dot)} /> : null}<span className={cn('relative inline-flex h-2 w-2 rounded-full', style.dot, style.ring)} /></span>
          <Cpu className={cn('h-3.5 w-3.5', style.text)} />
          <span className="font-mono text-[10px] text-paper-label">{runtime.label}</span>
          <span className={cn('font-mono text-[9px] uppercase tracking-wider', style.text)}>{runtime.state}</span>
        </div>
        <div className="hidden items-center gap-2 rounded-pill border border-hairline px-3 py-1.5 md:flex"><Zap className={cn('h-3.5 w-3.5', autoSend ? 'text-ember' : 'text-paper-label')} /><Toggle id="auto-send" checked={autoSend} onChange={setAutoSend} label="Auto-Send" /></div>
      </div>
      {autoSend ? <div className="flex items-center gap-2 border-t border-hairline bg-ember/10 px-4 py-2 lg:px-5"><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ember">Auto-send armed</span><p className="truncate text-[11px] text-paper-muted">Eligible drafts may dispatch without review. First-recipient and commitment gates still apply.</p></div> : null}
    </header>
  )
}
export default WorkspaceHeader
