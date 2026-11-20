import { Lock, Loader2, Shield, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '@/lib/api'
import { startGoogleSignIn } from '@/lib/googleAuth'
import type { Account } from '@/types'

export function MailboxSetupGate({ account, onConnected, onAccountCreated }: {
  account: Account | null
  onConnected: (account: Account) => void
  onAccountCreated: (account: Account) => void
}) {
  const [tab, setTab] = useState<'app-password' | 'oauth'>('app-password')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [credentialsJson, setCredentialsJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const connect = async (event: FormEvent) => {
    event.preventDefault()
    if (!account) return
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

  const signInWithEmail = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const created = await api.identityLogin({
        email: email.trim(),
        display_name: displayName.trim() || email.trim().split('@')[0] || 'Proteus user',
      })
      onAccountCreated(created)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the account.')
    } finally {
      setBusy(false)
    }
  }

  const startOAuth = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.googleAuthStart()
      window.location.assign(result.auth_url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Google sign-in.')
      setBusy(false)
    }
  }

  const uploadCredentials = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.googleAuthUploadCredentials(credentialsJson)
      await startOAuth()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save Google credentials.')
      setBusy(false)
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center overflow-y-auto bg-cobalt-deep p-6">
      <section className="w-full max-w-xl rounded-sm border border-ink/15 bg-paper p-7 text-ink shadow-2xl">
        <Lock className="mb-4 h-6 w-6 text-ember-ink" />
        <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink/55">Mandatory mailbox unlock</p>
        <h2 className="mt-2 font-display text-3xl">{account ? `Unlock ${account.email}` : 'Connect an account first'}</h2>
        {account ? (
          <>
            <p className="mt-3 text-sm leading-relaxed text-ink/70">Your mailbox connection is required before drafting or sending. IMAP: imap.gmail.com:993 · SMTP: smtp.gmail.com:465.</p>
            <div className="mt-5 flex gap-1 border-b border-ink/15">
              <button type="button" onClick={() => setTab('app-password')} className={`flex-1 border-b-2 px-3 py-3 font-mono text-[10px] uppercase tracking-wider ${tab === 'app-password' ? 'border-ember-ink text-ember-ink' : 'border-transparent text-ink/55'}`}>Gmail App Password</button>
              <button type="button" onClick={() => setTab('oauth')} className={`flex-1 border-b-2 px-3 py-3 font-mono text-[10px] uppercase tracking-wider ${tab === 'oauth' ? 'border-ember-ink text-ember-ink' : 'border-transparent text-ink/55'}`}><Shield className="mr-1 inline h-3.5 w-3.5" />Google OAuth</button>
            </div>
            {tab === 'app-password' ? (
              <form onSubmit={connect}>
                <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer" className="mt-5 inline-block text-sm text-ember-ink underline underline-offset-4">Open Google App Passwords ↗</a>
                <div className="mt-4 grid gap-2 font-mono text-[10px] text-ink/65"><span>IMAP: imap.gmail.com:993</span><span>SMTP: smtp.gmail.com:465</span></div>
                <label className="mt-5 block font-mono text-[9px] uppercase tracking-wider text-ink/55">16-character App Password</label>
                <input required type="password" value={password} onChange={(event) => setPassword(event.target.value.replace(/\s+/g, ''))} onPaste={(event) => { event.preventDefault(); setPassword(event.clipboardData.getData('text').replace(/\s+/g, '')) }} maxLength={16} className="mt-2 w-full rounded-sm border border-ink/20 bg-white/35 px-3 py-2 text-ink focus:border-ink/50 focus:outline-none" placeholder="xxxx xxxx xxxx xxxx" />
                {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
                <button disabled={busy || password.length !== 16} className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? 'Verifying…' : 'Verify & Unlock Workspace'}</button>
              </form>
            ) : (
              <form onSubmit={uploadCredentials} className="mt-5">
                <p className="text-sm leading-relaxed text-ink/70">Upload your Google Cloud OAuth client_secret.json to enable identity sign-in and mailbox access.</p>
                <label className="relative mt-5 flex cursor-pointer items-center justify-center gap-2 rounded-sm border border-dashed border-ink/25 p-6 font-mono text-[11px] text-ink/65">
                  <Upload className="h-5 w-5" />{credentialsJson ? 'File selected ✓' : 'Choose or drop client_secret.json'}
                  <input type="file" accept=".json" className="absolute inset-0 cursor-pointer opacity-0" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => setCredentialsJson(String(reader.result ?? '')); reader.readAsText(file) }} />
                </label>
                {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
                <button type="submit" disabled={busy || !credentialsJson} className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? 'Saving…' : 'Save & Sign In with Google'}</button>
              </form>
            )}
          </>
        ) : (
          <div className="mt-5 space-y-5">
            <button type="button" onClick={async () => { setBusy(true); setError(''); try { if (!(await startGoogleSignIn())) setError('Google OAuth is not configured. Use email sign-in below.') } catch (err) { setError(err instanceof Error ? err.message : 'Could not start Google sign-in.') } finally { setBusy(false) } }} disabled={busy} className="inline-flex w-full items-center justify-center gap-2 rounded-pill bg-ink px-5 py-3 text-sm font-medium text-paper">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}Sign in with Google</button>
            <div className="border-t border-ink/15 pt-5">
              <p className="font-mono text-[10px] uppercase tracking-wider text-ink/55">Email & Name quick sign-in</p>
              <form onSubmit={signInWithEmail} className="mt-3 grid gap-3 sm:grid-cols-2">
                <input required type="email" placeholder="Email address" value={email} onChange={(event) => setEmail(event.target.value)} className="rounded-sm border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:outline-none" />
                <input required placeholder="Display name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="rounded-sm border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:outline-none" />
                <button type="submit" disabled={busy} className="rounded-pill border border-ink/25 px-4 py-2 text-sm font-medium text-ink hover:border-ink/50 sm:col-span-2">Continue to Mailbox Unlock →</button>
              </form>
              {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
            </div>
          </div>
        )}
      </section>
    </main>
  )
}
