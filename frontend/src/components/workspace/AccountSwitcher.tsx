import { Check, ChevronsUpDown, Plus, Plug, X } from 'lucide-react'
import { useState } from 'react'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useAppStore } from '@/stores/useAppStore'
import { ConnectGmailModal } from '@/components/auth/ConnectGmailModal'
import type { Provider } from '@/types'
import { cn } from '@/lib/utils'

const PROVIDER_LABEL: Record<Provider, string> = { gmail: 'Gmail', outlook: 'Outlook', imap: 'IMAP', mbox: 'Mbox', demo: 'Demo' }
const PROVIDER_TONE: Record<Provider, 'accent' | 'neutral' | 'warning'> = { gmail: 'accent', outlook: 'neutral', imap: 'warning', mbox: 'neutral', demo: 'neutral' }
const PROVIDER_OPTIONS: Provider[] = ['gmail', 'outlook', 'imap']
interface AccountSwitcherProps { collapsed?: boolean }
export function AccountSwitcher({ collapsed = false }: AccountSwitcherProps) {
  const accounts = useAppStore((s) => s.accounts)
  const activeAccountId = useAppStore((s) => s.activeAccountId)
  const setActiveAccount = useAppStore((s) => s.setActiveAccount)
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', provider: 'gmail' as Provider })
  const [showConnectModal, setShowConnectModal] = useState(false)
  const popRef = useClickOutside<HTMLDivElement>(open, () => { setOpen(false); setAdding(false); setShowConnectModal(false) })
  const active = accounts.find((account) => account.id === activeAccountId) ?? accounts[0] ?? null
  const handleAddAccount = (event: React.FormEvent) => { event.preventDefault(); if (!form.email.trim()) return; setShowConnectModal(true); setAdding(false); setOpen(false) }
  const handleAccountSwitch = async (accountId: string) => { await setActiveAccount(accountId); setOpen(false) }
  const card = (
    <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((value) => !value)} className={cn('group flex w-full items-center gap-3 rounded-sm border border-hairline bg-cobalt p-2.5 text-left transition-colors hover:border-paper-label', collapsed && 'justify-center p-2')} disabled={!active}>
      {active ? <><Avatar initials={active.initials} size={collapsed ? 'sm' : 'md'} /><span className="relative"><span className={cn('absolute -right-0.5 -top-0.5 h-2 w-2 rounded-pill', active.mailboxConnected ? 'bg-foam' : 'bg-ember')} /></span>{!collapsed ? <><span className="min-w-0 flex-1"><span className="block truncate text-[12px] font-medium text-paper">{active.name}</span><span className="block truncate font-mono text-[9px] text-paper-label">{active.email}</span></span><span className="flex flex-col items-end gap-1"><Badge tone={PROVIDER_TONE[active.provider]}>{PROVIDER_LABEL[active.provider]}</Badge><ChevronsUpDown className="h-3.5 w-3.5 text-paper-label" /></span></> : null}</> : <span className="text-[12px] text-paper-label">No accounts</span>}
    </button>
  )
  return (
    <div className="relative" ref={popRef}>
      {open && !collapsed ? <div role="dialog" aria-label="Switch account" className="absolute bottom-[calc(100%+10px)] left-0 z-40 w-full min-w-[17rem] animate-fade-up overflow-hidden rounded-sm border border-hairline bg-cobalt-deep shadow-none">
        {!adding && !showConnectModal ? <div className="p-2"><p className="px-2.5 py-2 font-mono text-[9px] uppercase tracking-[0.18em] text-paper-label">Switch account</p>{accounts.length === 0 ? <div className="px-2 py-3 text-center text-[12px] text-paper-label">No accounts connected yet</div> : accounts.map((account) => { const isActive = account.id === activeAccountId; return <button key={account.id} type="button" onClick={() => void handleAccountSwitch(account.id)} className={cn('flex w-full items-center gap-3 rounded-sm px-2.5 py-2 text-left transition-colors', isActive ? 'bg-paper/10' : 'hover:bg-paper/[0.06]')}><Avatar initials={account.initials} size="sm" /><span className="min-w-0 flex-1"><span className="block truncate text-[12px] text-paper">{account.name}</span><span className="block truncate font-mono text-[9px] text-paper-label">{account.email}</span></span>{isActive ? <Check className="h-4 w-4 text-foam" /> : <span className="font-mono text-[8px] uppercase text-paper-label">{PROVIDER_LABEL[account.provider]}</span>}</button> })}<div className="my-1.5 border-t border-hairline" /><button type="button" onClick={() => setAdding(true)} className="flex w-full items-center gap-3 rounded-sm px-2.5 py-2.5 text-left text-[12px] text-foam hover:bg-foam/10"><span className="inline-flex h-8 w-8 items-center justify-center rounded-pill border border-dashed border-foam/50"><Plus className="h-4 w-4" /></span>Add account</button></div> : adding ? <form className="p-4" onSubmit={handleAddAccount}><div className="mb-3 flex items-center justify-between"><p className="font-mono text-[9px] uppercase tracking-[0.18em] text-paper-label">Add account</p><button type="button" aria-label="Cancel" onClick={() => setAdding(false)} className="text-paper-label hover:text-paper"><X className="h-4 w-4" /></button></div><label className="mb-1 block font-mono text-[9px] uppercase tracking-wider text-paper-label">Display name</label><input value={form.name} onChange={(e) => setForm((current) => ({ ...current, name: e.target.value }))} placeholder="Your Name" className="mb-3 w-full rounded-sm border border-hairline bg-cobalt px-3 py-2 text-[12px] text-paper placeholder:text-paper-label focus:border-foam/70 focus:outline-none" /><label className="mb-1 block font-mono text-[9px] uppercase tracking-wider text-paper-label">Email</label><input type="email" required value={form.email} onChange={(e) => setForm((current) => ({ ...current, email: e.target.value }))} placeholder="you@company.com" className="mb-3 w-full rounded-sm border border-hairline bg-cobalt px-3 py-2 text-[12px] text-paper placeholder:text-paper-label focus:border-foam/70 focus:outline-none" /><label className="mb-1 block font-mono text-[9px] uppercase tracking-wider text-paper-label">Provider</label><div className="mb-4 grid grid-cols-3 gap-1.5">{PROVIDER_OPTIONS.map((provider) => <button key={provider} type="button" onClick={() => setForm((current) => ({ ...current, provider }))} className={cn('rounded-sm border px-2 py-2 font-mono text-[9px] uppercase tracking-wider', form.provider === provider ? 'border-foam/60 bg-foam/10 text-foam' : 'border-hairline text-paper-muted hover:text-paper')}>{PROVIDER_LABEL[provider]}</button>)}</div><Button type="submit" size="sm" className="w-full" leftIcon={<Plug className="h-3.5 w-3.5" />}>Connect & switch</Button></form> : null}
      </div> : null}
      <ConnectGmailModal isOpen={showConnectModal} onClose={() => setShowConnectModal(false)} />
      {card}
    </div>
  )
}
export default AccountSwitcher
