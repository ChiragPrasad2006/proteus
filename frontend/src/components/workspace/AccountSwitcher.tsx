import { Check, ChevronsUpDown, Plus, Plug, X } from 'lucide-react'
import { useState } from 'react'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useAppStore } from '@/stores/useAppStore'
import type { Provider } from '@/types'
import { cn } from '@/lib/utils'

const PROVIDER_LABEL: Record<Provider, string> = {
  gmail: 'Gmail',
  outlook: 'Outlook',
  imap: 'IMAP',
  mbox: 'Mbox',
  demo: 'Demo',
}

const PROVIDER_TONE: Record<Provider, 'accent' | 'neutral' | 'warning'> = {
  gmail: 'accent',
  outlook: 'neutral',
  imap: 'warning',
  mbox: 'neutral',
  demo: 'neutral',
}

const PROVIDER_OPTIONS: Provider[] = ['gmail', 'outlook', 'imap']

interface AccountSwitcherProps {
  collapsed?: boolean
}

/** Pinned account card at the foot of the sidebar, with a switch/add popover. */
export function AccountSwitcher({ collapsed = false }: AccountSwitcherProps) {
  const accounts = useAppStore((s) => s.accounts)
  const activeAccountId = useAppStore((s) => s.activeAccountId)
  const setActiveAccount = useAppStore((s) => s.setActiveAccount)
  const addAccount = useAppStore((s) => s.addAccount)

  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', provider: 'gmail' as Provider })

  const popRef = useClickOutside<HTMLDivElement>(open, () => {
    setOpen(false)
    setAdding(false)
  })

  const active = accounts.find((a) => a.id === activeAccountId) ?? accounts[0]!

  const card = (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={() => setOpen((v) => !v)}
      className={cn(
        'group flex w-full items-center gap-3 rounded-[18px] border border-hairline bg-elevated/60 p-2.5 text-left',
        'transition-all duration-300 ease-proteus hover:border-hairline-strong hover:bg-elevated',
        collapsed && 'justify-center p-2',
      )}
    >
      <Avatar initials={active.initials} hue={active.hue} size={collapsed ? 'sm' : 'md'} />
      {!collapsed ? (
        <>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-fg">{active.name}</span>
            <span className="block truncate font-mono text-[11px] text-fg-faint">
              {active.email}
            </span>
          </span>
          <span className="flex flex-col items-end gap-1">
            <Badge tone={PROVIDER_TONE[active.provider]}>{PROVIDER_LABEL[active.provider]}</Badge>
            <ChevronsUpDown className="h-3.5 w-3.5 text-fg-faint transition-colors group-hover:text-fg-muted" />
          </span>
        </>
      ) : null}
    </button>
  )

  return (
    <div className="relative" ref={popRef}>
      {open && !collapsed ? (
        <div
          role="dialog"
          aria-label="Switch account"
          className={cn(
            'glass-strong absolute bottom-[calc(100%+10px)] left-0 z-40 w-full min-w-[17rem]',
            'animate-fade-up overflow-hidden rounded-[20px] border border-hairline shadow-[0_30px_70px_-30px_rgba(0,0,0,0.95)]',
          )}
        >
          {!adding ? (
            <div className="p-2">
              <p className="px-2.5 py-2 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
                Switch account
              </p>
              {accounts.map((acct) => {
                const isActive = acct.id === activeAccountId
                return (
                  <button
                    key={acct.id}
                    type="button"
                    onClick={() => {
                      setActiveAccount(acct.id)
                      setOpen(false)
                    }}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-[14px] px-2.5 py-2 text-left transition-colors duration-300 ease-proteus',
                      isActive ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]',
                    )}
                  >
                    <Avatar initials={acct.initials} hue={acct.hue} size="sm" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-fg">{acct.name}</span>
                      <span className="block truncate font-mono text-[10px] text-fg-faint">
                        {acct.email}
                      </span>
                    </span>
                    {isActive ? (
                      <Check className="h-4 w-4 shrink-0 text-accent" />
                    ) : (
                      <span className="font-mono text-[9px] uppercase tracking-wider text-fg-faint">
                        {PROVIDER_LABEL[acct.provider]}
                      </span>
                    )}
                  </button>
                )
              })}

              <div className="my-1.5 border-t border-hairline" />
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="flex w-full items-center gap-3 rounded-[14px] px-2.5 py-2.5 text-left text-[13px] text-accent transition-colors duration-300 ease-proteus hover:bg-accent/[0.08]"
              >
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-dashed border-accent/40">
                  <Plus className="h-4 w-4" />
                </span>
                Add another account
              </button>
            </div>
          ) : (
            <form
              className="p-4"
              onSubmit={(e) => {
                e.preventDefault()
                if (!form.email.trim()) return
                addAccount({
                  name: form.name.trim() || form.email.split('@')[0]!,
                  email: form.email.trim(),
                  provider: form.provider,
                })
                setForm({ name: '', email: '', provider: 'gmail' })
                setAdding(false)
                setOpen(false)
              }}
            >
              <div className="mb-3 flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
                  Add account
                </p>
                <button
                  type="button"
                  aria-label="Cancel"
                  onClick={() => setAdding(false)}
                  className="text-fg-faint hover:text-fg"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                Display name
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Maya Okonkwo"
                className="mb-3 w-full rounded-xl border border-hairline bg-ink/60 px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent/50 focus:outline-none"
              />

              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                Email
              </label>
              <input
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="you@company.com"
                className="mb-3 w-full rounded-xl border border-hairline bg-ink/60 px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent/50 focus:outline-none"
              />

              <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                Provider
              </label>
              <div className="mb-4 grid grid-cols-3 gap-1.5">
                {PROVIDER_OPTIONS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, provider: p }))}
                    className={cn(
                      'rounded-xl border px-2 py-2 font-mono text-[10px] uppercase tracking-wider transition-colors duration-300 ease-proteus',
                      form.provider === p
                        ? 'border-accent/50 bg-accent/[0.1] text-accent'
                        : 'border-hairline text-fg-muted hover:text-fg',
                    )}
                  >
                    {PROVIDER_LABEL[p]}
                  </button>
                ))}
              </div>

              <Button
                type="submit"
                size="sm"
                className="w-full"
                leftIcon={<Plug className="h-3.5 w-3.5" />}
              >
                Connect & switch
              </Button>
            </form>
          )}
        </div>
      ) : null}

      {card}
    </div>
  )
}

export default AccountSwitcher
