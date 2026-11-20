import { Lock, Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '@/lib/api'
import type { Account } from '@/types'

export function MailboxSetupGate({ account, onConnected }: { account: Account; onConnected: (account: Account) => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const connect = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try { const result = await api.connectAppPassword(password.replace(/\s+/g, ''), account.id); onConnected(result.account) } catch (err) { setError(err instanceof Error ? err.message : 'Mailbox verification failed.') } finally { setBusy(false) }
  }
  return <main className="flex flex-1 items-center justify-center bg-cobalt-deep p-6"><form onSubmit={connect} className="w-full max-w-lg rounded-sm border border-hairline bg-paper p-7 text-ink"><Lock className="mb-4 h-6 w-6 text-ember-ink" /><p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink/55">Mailbox gate</p><h2 className="mt-2 font-display text-3xl text-ink">Unlock {account.email}</h2><p className="mt-3 text-sm leading-relaxed text-ink/70">Mailbox setup is required before drafting or sending. IMAP: imap.gmail.com:993 · SMTP: smtp.gmail.com:465.</p><a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer" className="mt-4 inline-block text-sm text-ember-ink underline underline-offset-4">Open Google App Passwords ↗</a><label className="mt-6 block font-mono text-[9px] uppercase tracking-wider text-ink/55">16-character App Password</label><input required type="password" value={password} onChange={(e) => setPassword(e.target.value.replace(/\s+/g, ''))} onPaste={(e) => { e.preventDefault(); setPassword(e.clipboardData.getData('text').replace(/\s+/g, '')) }} maxLength={16} className="mt-2 w-full rounded-sm border border-ink/20 bg-white/35 px-3 py-2 text-ink focus:border-ink/50 focus:outline-none" placeholder="xxxx xxxx xxxx xxxx" />{error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}<button disabled={busy || password.length !== 16} className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}Verify and unlock</button></form></main>
}
