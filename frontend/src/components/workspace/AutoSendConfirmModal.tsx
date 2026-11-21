import { Zap } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { setAutoSendConfirmed } from '@/lib/localAdapter'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'

/** One-time in-app confirmation before Auto-Send is armed (never window.confirm). */
export function AutoSendConfirmModal() {
  const open = useWorkspaceUI((state) => state.autoSendConfirmOpen)
  const setOpen = useWorkspaceUI((state) => state.setAutoSendConfirmOpen)
  const setAutoSend = useAppStore((state) => state.setAutoSend)
  const account = useActiveAccount()

  const enable = () => {
    if (account) setAutoSendConfirmed(account.id)
    setAutoSend(true)
    setOpen(false)
  }

  return (
    <Modal open={open} onClose={() => setOpen(false)} label="Enable Auto-Send">
      <div className="p-6">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-pill bg-ember/14 text-ember-ink">
          <Zap className="h-5 w-5" aria-hidden />
        </span>
        <h2 className="mt-4 font-display text-2xl">Turn on Auto-Send?</h2>
        <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
          Automatically send without asking for contacts you’ve already approved. First-time contacts and new external domains always require your approval.
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-ink-faint">
          You can turn this off any time from the workspace header. Every automatic send still passes the first-recipient gate.
        </p>
        <div className="mt-6 flex items-center justify-end gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
            Cancel
          </button>
          <button type="button" onClick={enable} className="rounded-pill bg-ink px-5 py-2 text-[13px] font-medium text-paper hover:bg-send-hover">
            Enable Auto-Send
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default AutoSendConfirmModal