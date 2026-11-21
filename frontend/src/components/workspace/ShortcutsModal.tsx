import { Modal } from '@/components/ui/Modal'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'

const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: '⌘/Ctrl + K', action: 'Open the command palette' },
  { keys: '⌘/Ctrl + N', action: 'Start a new session' },
  { keys: '⌘/Ctrl + Enter', action: 'Send / approve the active draft' },
  { keys: 'Enter', action: 'Send chat message' },
  { keys: 'Shift + Enter', action: 'New line in the composer' },
  { keys: '@', action: 'Mention a contact in the composer' },
  { keys: '/', action: 'Quick tone macros in the composer' },
  { keys: '↑ / ↓', action: 'Navigate sessions and menus' },
  { keys: 'Esc', action: 'Close popovers, sheets and modals' },
  { keys: '?', action: 'Open this cheat sheet' },
]

export function ShortcutsModal() {
  const open = useWorkspaceUI((state) => state.shortcutsOpen)
  const setOpen = useWorkspaceUI((state) => state.setShortcutsOpen)
  return (
    <Modal open={open} onClose={() => setOpen(false)} label="Keyboard shortcuts">
      <div className="p-6">
        <p className="font-mono text-[12px] uppercase tracking-[0.16em] text-ink-muted">Reference</p>
        <h2 className="mt-1.5 font-display text-2xl">Keyboard shortcuts</h2>
        <ul className="mt-5 space-y-2.5">
          {SHORTCUTS.map((shortcut) => (
            <li key={shortcut.keys} className="flex items-center justify-between gap-4">
              <span className="text-[13px] text-ink">{shortcut.action}</span>
              <kbd className="shrink-0 rounded-[2px] border border-ink-hairline bg-white/40 px-2 py-1 font-mono text-[12px] text-ink-muted">{shortcut.keys}</kbd>
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  )
}

export default ShortcutsModal