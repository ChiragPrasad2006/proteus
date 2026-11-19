import { Lock, Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '@/lib/api'
import type { Account } from '@/types'

export function MailboxSetupGate({ account, onConnected }: { account: Account; onConnected: (account: Account) => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const connect = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api.connectAppPassword(password.replace(/\s+/g, ''), account.id)
      onConnected(result.account)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Mailbox verification failed.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="flex flex-1 items-center justify-center p-6"><form onSubmit={connect} className="w-full max-w-lg rounded-2xl border border-hairline bg-surface p-6"><Lock className="mb-3 h-6 w-6 text-accent"/><h2 className="font-display text-2xl text-fg">Unlock {account.email}</h2><p className="mt-2 text-sm text-fg-muted">Mailbox setup is required before drafting or sending. IMAP: imap.gmail.com:993 · SMTP: smtp.gmail.com:465.</p><a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer" className="mt-4 inline-block text-sm text-accent underline">Open Google App Passwords ↗</a><label className="mt-5 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">16-character App Password</label><input required type="password" value={password} onChange={(e) => setPassword(e.target.value.replace(/\s+/g, ''))} onPaste={(e) => { e.preventDefault(); setPassword(e.clipboardData.getData('text').replace(/\s+/g, '')) }} maxLength={16} className="mt-2 w-full rounded-xl border border-hairline bg-ink px-3 py-2 text-fg" placeholder="xxxx xxxx xxxx xxxx"/>{error ? <p className="mt-3 text-sm text-red">{error}</p> : null}<button disabled={busy || password.length !== 16} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-ink disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin"/> : null}Verify and unlock</button></form></main>
}
