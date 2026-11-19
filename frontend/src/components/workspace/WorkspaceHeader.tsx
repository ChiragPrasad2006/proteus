import { Cpu, MoreHorizontal, PanelLeftOpen, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Toggle } from '@/components/ui/Toggle'
import { useRuntimeStatus } from '@/hooks/useHealth'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'

const STATE_STYLE = {
  online: { dot: 'bg-accent', text: 'text-accent', ring: 'shadow-[0_0_10px_2px_rgba(212,242,104,0.55)]' },
  loading: { dot: 'bg-[#fbbf24]', text: 'text-[#fbbf24]', ring: '' },
  offline: { dot: 'bg-fg-faint', text: 'text-fg-faint', ring: '' },
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
    <header className="sticky top-0 z-20 border-b border-hairline bg-ink/85 backdrop-blur-xl">
      <div className="flex h-[68px] items-center gap-3 px-4 lg:px-6">
        {sidebarCollapsed ? (
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label="Expand sidebar"
            className="hidden h-9 w-9 items-center justify-center rounded-full border border-hairline text-fg-muted transition-colors duration-300 ease-proteus hover:border-hairline-strong hover:text-fg lg:inline-flex"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        ) : null}

        {/* Session title */}
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitTitle()
                if (e.key === 'Escape') {
                  setDraftTitle(sessionTitle)
                  setEditing(false)
                }
              }}
              className="w-full max-w-lg rounded-lg border border-accent/40 bg-ink/60 px-2.5 py-1 font-display text-lg text-fg focus:outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={() => session && setEditing(true)}
              disabled={!session}
              className="group flex min-w-0 items-center gap-2 text-left disabled:cursor-default"
            >
              <h1 className="truncate font-display text-lg font-normal leading-tight text-fg">
                {sessionTitle}
              </h1>
              {session ? <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-fg-faint opacity-0 transition-opacity group-hover:opacity-100">rename</span> : null}
            </button>
          )}
          <p className="mt-0.5 truncate font-mono text-[11px] text-fg-faint">
            {account?.email ?? 'Mailbox setup required'} · workspace
          </p>
        </div>

        {/* Runtime status */}
        <div
          className="hidden items-center gap-2 rounded-full border border-hairline bg-white/[0.03] px-3 py-1.5 sm:flex"
          title={runtime.detail}
        >
          <span className="relative flex h-2 w-2">
            {runtime.state === 'online' ? (
              <span className={cn('absolute inline-flex h-full w-full animate-pulse-ring rounded-full', style.dot)} />
            ) : null}
            <span className={cn('relative inline-flex h-2 w-2 rounded-full', style.dot, style.ring)} />
          </span>
          <Cpu className={cn('h-3.5 w-3.5', style.text)} />
          <span className="font-mono text-[11px] text-fg-muted">{runtime.label}</span>
          <span className={cn('font-mono text-[10px] uppercase tracking-wider', style.text)}>
            {runtime.state === 'online' ? 'ready' : runtime.state}
          </span>
        </div>

        {/* Auto-send */}
        <div className="hidden items-center gap-2 rounded-full border border-hairline bg-white/[0.03] px-3 py-1.5 md:flex">
          <Zap className={cn('h-3.5 w-3.5', autoSend ? 'text-accent' : 'text-fg-faint')} />
          <Toggle
            id="auto-send"
            checked={autoSend}
            onChange={setAutoSend}
            label="Auto-Send"
          />
        </div>

        <button
          type="button"
          aria-label="More options"
          className="inline-flex h-9 w-9 items-center justify-center rounded-full text-fg-faint transition-colors duration-300 ease-proteus hover:bg-white/[0.06] hover:text-fg"
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </div>

      {/* Guardrail notice when auto-send is armed */}
      {autoSend ? (
        <div className="flex items-center gap-2 border-t border-hairline bg-[#f59e0b]/[0.07] px-4 py-2 lg:px-6">
          <Badge tone="warning">Auto-send armed</Badge>
          <p className="truncate text-[12px] text-[#fbbf24]">
            Eligible drafts will dispatch without review. First-recipient and commitment
            gates still apply.
          </p>
        </div>
      ) : null}
    </header>
  )
}

export default WorkspaceHeader
