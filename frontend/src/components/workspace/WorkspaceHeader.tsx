import { Cpu, FileText, Info, Search, Zap } from 'lucide-react'
import { useState } from 'react'
import { IconButton } from '@/components/ui/IconButton'
import { Toggle } from '@/components/ui/Toggle'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useHealth } from '@/hooks/useHealth'
import { useDraftState, useSelectedDraft } from '@/hooks/useDraftState'
import { isAutoSendConfirmed } from '@/lib/localAdapter'
import { friendlyName } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'

export interface WorkspaceHeaderProps {
  /** Show the draft-sheet trigger (viewports < 1100px). */
  showDraftButton: boolean
  /** Optional override when viewing an Inbox thread instead of a Compose session. */
  titleOverride?: string
  participantsOverride?: string[]
}

export function WorkspaceHeader({ showDraftButton, titleOverride, participantsOverride }: WorkspaceHeaderProps) {
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const renameSession = useAppStore((state) => state.renameSession)
  const autoSend = useAppStore((state) => state.autoSend)
  const setAutoSend = useAppStore((state) => state.setAutoSend)
  const contacts = useAppStore((state) => state.contacts)
  const account = useActiveAccount()
  const draft = useSelectedDraft()
  const drafts = useDraftState((state) => state.drafts)
  const setPaletteOpen = useWorkspaceUI((state) => state.setPaletteOpen)
  const setDraftSheetOpen = useWorkspaceUI((state) => state.setDraftSheetOpen)
  const setAutoSendConfirmOpen = useWorkspaceUI((state) => state.setAutoSendConfirmOpen)

  const session = sessions.find((item) => item.id === activeSessionId) ?? null
  const isInboxMode = Boolean(titleOverride !== undefined)
  const sessionTitle = titleOverride ?? (session?.title?.trim() || 'New session')
  const [editing, setEditing] = useState(false)
  const [draftTitle, setDraftTitle] = useState(sessionTitle)
  const [modelHelpOpen, setModelHelpOpen] = useState(false)
  const [autoSendInfoOpen, setAutoSendInfoOpen] = useState(false)
  const modelHelpRef = useClickOutside<HTMLDivElement>(modelHelpOpen, () => setModelHelpOpen(false))
  const autoSendInfoRef = useClickOutside<HTMLDivElement>(autoSendInfoOpen, () => setAutoSendInfoOpen(false))

  // Reset the inline editor when the session/title changes (render-phase adjustment).
  const titleKey = `${session?.id ?? ''}:${sessionTitle}`
  const [prevTitleKey, setPrevTitleKey] = useState(titleKey)
  if (prevTitleKey !== titleKey) {
    setPrevTitleKey(titleKey)
    setDraftTitle(sessionTitle)
    setEditing(false)
  }

  const health = useHealth()
  const backendOffline = health.isError
  const modelReady = !backendOffline && (health.data?.generation?.available === true || health.data?.qwen?.available === true)
  const modelLabel = backendOffline ? 'Backend offline' : modelReady ? 'Local model · Ready' : 'Ollama offline'

  // Resolved recipient chips for the active session or inbox thread.
  const sessionDraft = draft ?? Object.values(drafts).filter((item) => item.sessionId === activeSessionId).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]
  const recipientEmails = participantsOverride && participantsOverride.length > 0
    ? participantsOverride
    : sessionDraft ? [...sessionDraft.to, ...sessionDraft.cc, ...sessionDraft.bcc] : []
  const recipientNames = recipientEmails.map((email) => contacts.find((contact) => contact.email === email)?.name || friendlyName(email))

  const commitTitle = () => {
    const next = draftTitle.trim()
    if (session && next && next !== session.title) void renameSession(session.id, next).catch(() => setDraftTitle(sessionTitle))
    else setDraftTitle(sessionTitle)
    setEditing(false)
  }

  const handleAutoSendToggle = (next: boolean) => {
    if (!next) { setAutoSend(false); return }
    if (account && isAutoSendConfirmed(account.id)) setAutoSend(true)
    else setAutoSendConfirmOpen(true)
  }

  return (
    <header className="sticky top-0 z-20 border-b border-hairline bg-cobalt-deep">
      <div className="flex h-[60px] items-center gap-3 px-4 lg:px-5">
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              onBlur={commitTitle}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commitTitle()
                if (event.key === 'Escape') { setDraftTitle(sessionTitle); setEditing(false) }
              }}
              aria-label="Session title"
              className="w-full max-w-lg rounded-card border border-foam/50 bg-cobalt px-2.5 py-1 font-display text-lg text-paper focus:outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={() => !isInboxMode && session && setEditing(true)}
              disabled={isInboxMode || !session}
              title={sessionTitle}
              className="block min-w-0 max-w-full text-left disabled:cursor-default"
            >
              <h1 className="truncate font-display text-lg font-normal leading-tight text-paper">{sessionTitle}</h1>
            </button>
          )}
          {recipientNames.length > 0 ? (
            <div className="mt-0.5 flex items-center gap-1.5 overflow-hidden">
              {recipientNames.slice(0, 3).map((name, index) => (
                <span key={`${name}-${index}`} className="inline-flex shrink-0 items-center gap-1 rounded-pill border border-hairline px-2 py-0.5 text-[12px] text-paper-muted" title={recipientEmails[index]}>
                  <span className="h-1 w-1 rounded-pill bg-foam" aria-hidden />
                  {name}
                </span>
              ))}
              {recipientNames.length > 3 ? <span className="shrink-0 font-mono text-[12px] text-paper-muted">+{recipientNames.length - 3}</span> : null}
            </div>
          ) : (
            <p className="mt-0.5 truncate font-mono text-[12px] text-paper-muted">{account?.email ?? 'Mailbox setup required'}</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <IconButton label="Command palette" shortcut="⌘K" onClick={() => setPaletteOpen(true)} className="hidden sm:inline-flex">
            <Search className="h-4 w-4" />
          </IconButton>

          {showDraftButton ? (
            <button
              type="button"
              onClick={() => setDraftSheetOpen(true)}
              className="inline-flex items-center gap-2 rounded-pill border border-hairline px-3 py-1.5 text-[12px] text-paper transition-colors hover:border-paper-label"
            >
              <FileText className="h-3.5 w-3.5" aria-hidden />
              Draft
              {sessionDraft ? <span className={cn('h-1.5 w-1.5 rounded-pill', sessionDraft.status === 'sent' ? 'bg-foam' : sessionDraft.status === 'pending_review' ? 'bg-ember' : 'bg-paper-muted')} aria-hidden /> : null}
            </button>
          ) : null}

          {/* Local model pill */}
          <div className="relative" ref={modelHelpRef}>
            <button
              type="button"
              onClick={() => !modelReady && setModelHelpOpen((value) => !value)}
              aria-expanded={modelHelpOpen}
              title={modelReady ? (health.data?.gpu?.available ? `GPU · ${health.data.gpu.name ?? 'ready'}` : 'Running on CPU') : 'Click for restart help'}
              className={cn('inline-flex items-center gap-2 rounded-pill border border-hairline px-3 py-1.5', !modelReady && 'hover:border-paper-label')}
            >
              <span className={cn('h-2 w-2 rounded-pill', modelReady ? 'bg-foam' : 'bg-ember')} aria-hidden />
              <Cpu className="h-3.5 w-3.5 text-paper-muted" aria-hidden />
              <span className="hidden font-mono text-[12px] text-paper md:inline">{modelLabel}</span>
            </button>
            {modelHelpOpen && !modelReady ? (
              <div role="dialog" aria-label="Local model help" className="absolute right-0 top-[calc(100%+8px)] z-40 w-72 rounded-card border border-hairline bg-cobalt-deep p-4">
                <p className="text-[13px] font-medium text-paper">{backendOffline ? 'The local backend is not running' : 'Ollama is not reachable'}</p>
                <ol className="mt-2.5 space-y-1.5 text-[12px] leading-relaxed text-paper-muted">
                  {backendOffline ? (
                    <>
                      <li>1. Launch <span className="font-mono text-paper">Proteus.exe</span> from the project folder.</li>
                      <li>2. Wait for the health check, then reload this page.</li>
                    </>
                  ) : (
                    <>
                      <li>1. Open a terminal and run <span className="font-mono text-paper">ollama serve</span>.</li>
                      <li>2. If the model is missing: <span className="font-mono text-paper">ollama pull qwen3:8b</span>.</li>
                      <li>3. Restart Proteus and reload this page.</li>
                    </>
                  )}
                </ol>
              </div>
            ) : null}
          </div>

          {/* Auto-Send safety control */}
          <div className="relative hidden items-center gap-1.5 rounded-pill border border-hairline px-3 py-1.5 md:flex" ref={autoSendInfoRef}>
            <Zap className={cn('h-3.5 w-3.5', autoSend ? 'text-ember' : 'text-paper-muted')} aria-hidden />
            <Toggle id="auto-send" checked={autoSend} onChange={handleAutoSendToggle} label="Auto-Send" />
            <button type="button" aria-label="What does Auto-Send do?" onClick={() => setAutoSendInfoOpen((value) => !value)} className="text-paper-muted hover:text-paper">
              <Info className="h-3.5 w-3.5" />
            </button>
            {autoSendInfoOpen ? (
              <div role="dialog" aria-label="Auto-Send explained" className="absolute right-0 top-[calc(100%+8px)] z-40 w-72 rounded-card border border-hairline bg-cobalt-deep p-4 text-[12px] leading-relaxed text-paper-muted">
                Automatically send without asking for contacts you’ve already approved. First-time contacts and new external domains always require your approval.
              </div>
            ) : null}
          </div>
        </div>
      </div>
      {autoSend ? (
        <div className="flex items-center gap-2.5 border-t border-hairline px-4 py-2 lg:px-5">
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-pill bg-ember px-3 py-0.5 font-mono text-[12px] font-medium uppercase tracking-[0.08em] text-ink">
            <Zap className="h-3 w-3" aria-hidden /> Auto-Send on
          </span>
          <p className="truncate text-[12px] text-paper-muted">Approved contacts send automatically. First-time contacts still wait for your OK.</p>
        </div>
      ) : null}
    </header>
  )
}

export default WorkspaceHeader