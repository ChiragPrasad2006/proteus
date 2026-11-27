import { Check, Copy, Lock, Loader2, Shield, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api } from '@/lib/api'
import { OutlookSetupPanel, ProviderPillBar, ZohoSetupPanel, type MailboxProviderTab } from '@/components/auth/ProviderSetupPanels'
import { startGoogleSignIn } from '@/lib/googleAuth'
import type { Account } from '@/types'

export function MailboxSetupGate({ account, onConnected, onAccountCreated }: {
  account: Account | null
  onConnected: (account: Account) => void
  onAccountCreated: (account: Account) => void
}) {
  const [provider, setProvider] = useState<MailboxProviderTab>('gmail')
  const [tab, setTab] = useState<'app-password' | 'oauth'>('app-password')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [credentialsJson, setCredentialsJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copiedRedirectUri, setCopiedRedirectUri] = useState(false)
  const redirectUri = 'http://127.0.0.1:8000/api/auth/google/callback'

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

  const copyRedirectUri = async () => {
    try {
      await navigator.clipboard.writeText(redirectUri)
      setCopiedRedirectUri(true)
      window.setTimeout(() => setCopiedRedirectUri(false), 1800)
    } catch {
      setError('Could not copy the redirect URI. Select and copy it manually.')
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center overflow-y-auto bg-cobalt-deep p-6">
      <section className="w-full max-w-xl rounded-[2px] border border-ink/15 bg-paper p-7 text-ink">
        <Lock className="mb-4 h-6 w-6 text-ember-ink" />
        <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-ink-muted">Mandatory mailbox unlock</p>
        <h2 className="mt-2 font-display text-3xl">{account ? `Unlock ${account.email}` : 'Connect an account first'}</h2>
        {account ? (
          <>
            <p className="mt-3 text-sm leading-relaxed text-ink/70">Your mailbox connection is required before drafting or sending.</p>
            <ProviderPillBar provider={provider} onChange={setProvider} />
            {provider === 'outlook' ? (
              <OutlookSetupPanel />
            ) : provider === 'zoho' ? (
              <ZohoSetupPanel initialEmail={account.email} initialName={account.name} accountId={account.id} onConnected={onConnected} />
            ) : (
              <>
                <div className="mt-5 flex gap-1 border-b border-ink/15">
              <button type="button" onClick={() => setTab('app-password')} className={`flex-1 border-b-2 px-3 py-3 font-mono text-[12px] uppercase tracking-wider transition-colors ${tab === 'app-password' ? 'border-ember-ink text-ember-ink font-semibold' : 'border-transparent text-ink-muted hover:text-ink'}`}>Gmail App Password</button>
              <button type="button" onClick={() => setTab('oauth')} className={`flex-1 border-b-2 px-3 py-3 font-mono text-[12px] uppercase tracking-wider transition-colors ${tab === 'oauth' ? 'border-ember-ink text-ember-ink font-semibold' : 'border-transparent text-ink-muted hover:text-ink'}`}><Shield className="mr-1 inline h-3.5 w-3.5" />Google OAuth</button>
            </div>
            {tab === 'app-password' ? (
              <form onSubmit={connect}>
                <ol className="mt-5 space-y-2.5 text-[12px] leading-relaxed text-ink/75">
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">01</span>Ensure <strong>2-Step Verification</strong> is enabled on your Google Account (<a href="https://myaccount.google.com/security" target="_blank" rel="noopener noreferrer" className="text-ember-ink underline underline-offset-2">https://myaccount.google.com/security ↗</a>).</li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">02</span>Click <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer" className="font-medium text-ember-ink underline underline-offset-2">Open Google App Passwords ↗</a> (opens in new tab).</li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">03</span>Enter <strong>Proteus</strong> as the app name and click <strong>Create</strong>.</li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">04</span>Copy the generated <strong>16-character password</strong> and paste it below (spaces are stripped automatically), then click <strong>Verify &amp; Unlock Workspace</strong>.</li>
                </ol>
                <div className="mt-5 font-mono text-[12px] text-ink/65">IMAP: imap.gmail.com:993 · SMTP: smtp.gmail.com:465</div>
                <label className="mt-3 block font-mono text-[12px] uppercase tracking-wider text-ink-muted">16-character App Password</label>
                <input required type="password" value={password} onChange={(event) => setPassword(event.target.value.replace(/\s+/g, ''))} onPaste={(event) => { event.preventDefault(); setPassword(event.clipboardData.getData('text').replace(/\s+/g, '')) }} maxLength={16} className="mt-2 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-ink focus:border-ink/50 focus:outline-none" placeholder="xxxx xxxx xxxx xxxx" />
                {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
                <button disabled={busy || password.length !== 16} className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-50 hover:bg-ink/90">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? 'Verifying…' : 'Verify & Unlock Workspace'}</button>
              </form>
            ) : (
              <form onSubmit={uploadCredentials} className="mt-5">
                <ol className="space-y-2.5 text-[12px] leading-relaxed text-ink/75">
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">01</span>Open <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="text-ember-ink underline underline-offset-2">Google Cloud Console → Credentials ↗</a> and create or select a project.</li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">02</span>Go to <strong>APIs &amp; Services → Library</strong>, search <strong>Gmail API</strong>, and click <strong>Enable</strong>.</li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">03</span>Go to <strong>OAuth consent screen → External</strong>, fill in app name (<strong>Proteus</strong>), and add your Gmail address under <strong>Test users</strong>.</li>
                  <li>
                    <span className="mr-2 font-mono text-[12px] text-ember-ink">04</span>
                    Under <strong>Credentials → + Create Credentials → OAuth client ID</strong>, choose <strong>Desktop app</strong> (or <strong>Web application</strong> with Authorized Redirect URI:
                    <div className="mt-2 flex items-center gap-2 rounded-[2px] border border-ink/15 bg-white/40 p-2">
                      <code className="min-w-0 flex-1 break-all font-mono text-[12px] text-ink/80">{redirectUri}</code>
                      <button
                        type="button"
                        onClick={() => void copyRedirectUri()}
                        className="inline-flex shrink-0 items-center gap-1 rounded-[2px] border border-ink/20 px-2 py-1 font-mono text-[12px] uppercase tracking-wider text-ink/70 transition-colors hover:border-ink/50 hover:text-ink focus-visible:outline-none"
                        aria-label="Copy redirect URI"
                      >
                        {copiedRedirectUri ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
                        {copiedRedirectUri ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </li>
                  <li><span className="mr-2 font-mono text-[12px] text-ember-ink">05</span>Download the JSON file, upload it below (<code className="font-mono text-[12px] text-ink/75">POST /api/auth/google/upload-credentials</code>), and click <strong>Save &amp; Sign In with Google</strong>.</li>
                </ol>
                <label className="relative mt-5 flex cursor-pointer items-center justify-center gap-2 rounded-[2px] border border-dashed border-ink/25 p-6 font-mono text-[12px] text-ink/65 hover:border-ink/40">
                  <Upload className="h-5 w-5" />{credentialsJson ? 'File selected ✓' : 'Choose or drop client_secret.json'}
                  <input type="file" accept=".json" className="absolute inset-0 cursor-pointer opacity-0" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => setCredentialsJson(String(reader.result ?? '')); reader.readAsText(file) }} />
                </label>
                {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
                <button type="submit" disabled={busy || !credentialsJson} className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper disabled:opacity-50 hover:bg-ink/90">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? 'Saving…' : 'Save & Sign In with Google'}</button>
              </form>
            )}
              </>
            )}
          </>
        ) : (
          <div className="mt-5 space-y-5">
            <button
              type="button"
              onClick={async () => {
                setBusy(true)
                setError('')
                try {
                  if (!(await startGoogleSignIn())) {
                    setError('Google OAuth is not configured on this machine yet. Sign in with email below.')
                  }
                } catch (err) {
                  setError(
                    err instanceof ApiError && err.status === 0
                      ? 'Cannot reach Proteus backend on 127.0.0.1:8000 — start Proteus.exe'
                      : (err instanceof Error ? err.message : 'Could not start Google sign-in.')
                  )
                } finally {
                  setBusy(false)
                }
              }}
              disabled={busy}
              className="inline-flex w-full items-center justify-center gap-2 rounded-pill bg-ink px-5 py-3 text-sm font-medium text-paper hover:bg-ink/90 disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}Sign in with Google
            </button>
            <div className="border-t border-ink/15 pt-5">
              <p className="font-mono text-[12px] uppercase tracking-wider text-ink-muted">Email & Name quick sign-in</p>
              <form onSubmit={signInWithEmail} className="mt-3 grid gap-3 sm:grid-cols-2">
                <input required type="email" placeholder="Email address" value={email} onChange={(event) => setEmail(event.target.value)} className="rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:outline-none" />
                <input required placeholder="Display name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:outline-none" />
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
