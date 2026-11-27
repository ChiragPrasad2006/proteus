import { Check, Copy, Loader2, Lock, Shield } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '@/lib/api'
import type { Account, ZohoRegion } from '@/types'

export type MailboxProviderTab = 'gmail' | 'outlook' | 'zoho'

const ZOHO_REGIONS: { value: ZohoRegion; label: string; domain: string }[] = [
  { value: 'in', label: 'India (.in)', domain: 'zoho.in' },
  { value: 'com', label: 'US (.com)', domain: 'zoho.com' },
  { value: 'eu', label: 'EU (.eu)', domain: 'zoho.eu' },
  { value: 'com.au', label: 'AU (.com.au)', domain: 'zoho.com.au' },
  { value: 'jp', label: 'JP (.jp)', domain: 'zoho.jp' },
]

export function ProviderPillBar({
  provider,
  onChange,
}: {
  provider: MailboxProviderTab
  onChange: (next: MailboxProviderTab) => void
}) {
  const items: { id: MailboxProviderTab; label: string }[] = [
    { id: 'gmail', label: 'Gmail' },
    { id: 'outlook', label: 'Outlook' },
    { id: 'zoho', label: 'Zoho Mail' },
  ]
  return (
    <div role="tablist" aria-label="Email provider" className="mt-4 flex gap-1.5 rounded-[2px] border border-ink/15 bg-white/30 p-1">
      {items.map((item) => {
        const active = provider === item.id
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            className={`flex-1 rounded-[2px] px-3 py-2 font-mono text-[12px] uppercase tracking-wider transition-colors ${
              active
                ? 'bg-ink font-semibold text-paper'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export function OutlookSetupPanel() {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [tenantId, setTenantId] = useState('common')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const redirectUri = 'http://127.0.0.1:8000/api/auth/outlook/callback'

  const copyUri = async () => {
    try {
      await navigator.clipboard.writeText(redirectUri)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setError('Could not copy the redirect URI. Select and copy it manually.')
    }
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!clientId.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.outlookAuthConfigure({
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
        tenant_id: tenantId.trim() || 'common',
      })
      const res = await api.outlookAuthStart()
      window.location.assign(res.auth_url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Microsoft sign-in.')
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-5">
      <ol className="space-y-2.5 text-[12px] leading-relaxed text-ink/75">
        <li>
          <span className="mr-2 font-mono text-[12px] text-ember-ink">01</span>
          Open{' '}
          <a
            href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-ember-ink underline underline-offset-2"
          >
            Microsoft Entra / Azure App Registrations ↗
          </a>
        </li>
        <li>
          <span className="mr-2 font-mono text-[12px] text-ember-ink">02</span>
          Create a registration supporting <em>Accounts in any organizational directory and personal Microsoft accounts</em>.
        </li>
        <li>
          <span className="mr-2 font-mono text-[12px] text-ember-ink">03</span>
          Add Redirect URI:
          <div className="mt-2 flex items-center gap-2 rounded-[2px] border border-ink/15 bg-white/40 p-2">
            <code className="min-w-0 flex-1 break-all font-mono text-[12px] text-ink/80">{redirectUri}</code>
            <button
              type="button"
              onClick={() => void copyUri()}
              className="inline-flex shrink-0 items-center gap-1 rounded-[2px] border border-ink/20 px-2 py-1 font-mono text-[12px] uppercase tracking-wider text-ink/70 transition-colors hover:border-ink/50 hover:text-ink"
              aria-label="Copy Outlook redirect URI"
            >
              {copied ? <Check className="h-3 w-3 text-foam-ink" /> : <Copy className="h-3 w-3" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </li>
        <li>
          <span className="mr-2 font-mono text-[12px] text-ember-ink">04</span>
          Enable <strong>Allow public client flows</strong> (or create a Client Secret), copy the <strong>Application (client) ID</strong>, paste it below, and click <strong>Save &amp; Sign In with Microsoft</strong>.
        </li>
      </ol>

      <div className="mt-4 space-y-3">
        <div>
          <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Application (client) ID</label>
          <input
            required
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
            className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 font-mono text-[12px] text-ink focus:border-ink/50 focus:outline-none"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Tenant ID (optional)</label>
            <input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="common"
              className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 font-mono text-[12px] text-ink focus:border-ink/50 focus:outline-none"
            />
          </div>
          <div>
            <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Client Secret (optional)</label>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder="Public PKCE if blank"
              className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 font-mono text-[12px] text-ink focus:border-ink/50 focus:outline-none"
            />
          </div>
        </div>
      </div>
      {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
      <button
        type="submit"
        disabled={busy || !clientId.trim()}
        className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper hover:bg-ink/90 disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
        {busy ? 'Redirecting to Microsoft…' : 'Save & Sign In with Microsoft'}
      </button>
    </form>
  )
}

export function ZohoSetupPanel({
  initialEmail = '',
  initialName = '',
  accountId,
  onConnected,
}: {
  initialEmail?: string
  initialName?: string
  accountId?: string
  onConnected: (account: Account) => void
}) {
  const [zohoMode, setZohoMode] = useState<'app-password' | 'oauth'>('app-password')
  const [region, setRegion] = useState<ZohoRegion>('in')
  const [email, setEmail] = useState(initialEmail)
  const [displayName, setDisplayName] = useState(initialName)
  const [appPassword, setAppPassword] = useState('')
  const [oauthClientId, setOauthClientId] = useState('')
  const [oauthClientSecret, setOauthClientSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const activeRegion = ZOHO_REGIONS.find((r) => r.value === region) ?? ZOHO_REGIONS[0]
  const securityUrl = `https://accounts.${activeRegion.domain}/home#security/security_pwd`
  const redirectUri = 'http://127.0.0.1:8000/api/auth/zoho/callback'

  const handleAppPasswordSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!email.trim() || !appPassword.trim()) return
    setBusy(true)
    setError('')
    try {
      const res = await api.connectZoho(
        {
          email: email.trim(),
          display_name: displayName.trim() || undefined,
          app_password: appPassword.trim(),
          region,
        },
        accountId,
      )
      onConnected(res.account)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Zoho Mail verification failed.')
    } finally {
      setBusy(false)
    }
  }

  const handleOAuthSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!oauthClientId.trim() || !oauthClientSecret.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.zohoAuthConfigure({
        client_id: oauthClientId.trim(),
        client_secret: oauthClientSecret.trim(),
        region,
      })
      const res = await api.zohoAuthStart()
      window.location.assign(res.auth_url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Zoho OAuth.')
      setBusy(false)
    }
  }

  const copyUri = async () => {
    try {
      await navigator.clipboard.writeText(redirectUri)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setError('Could not copy the redirect URI.')
    }
  }

  return (
    <div className="mt-4">
      <div className="flex gap-1 border-b border-ink/15">
        <button
          type="button"
          onClick={() => setZohoMode('app-password')}
          className={`flex-1 border-b-2 px-3 py-2.5 font-mono text-[12px] uppercase tracking-wider transition-colors ${
            zohoMode === 'app-password' ? 'border-ember-ink font-semibold text-ember-ink' : 'border-transparent text-ink-muted hover:text-ink'
          }`}
        >
          <Lock className="mr-1 inline h-3.5 w-3.5" />
          App Password
        </button>
        <button
          type="button"
          onClick={() => setZohoMode('oauth')}
          className={`flex-1 border-b-2 px-3 py-2.5 font-mono text-[12px] uppercase tracking-wider transition-colors ${
            zohoMode === 'oauth' ? 'border-ember-ink font-semibold text-ember-ink' : 'border-transparent text-ink-muted hover:text-ink'
          }`}
        >
          <Shield className="mr-1 inline h-3.5 w-3.5" />
          Zoho OAuth
        </button>
      </div>

      <div className="mt-4">
        <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Zoho Data Center</label>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {ZOHO_REGIONS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setRegion(item.value)}
              className={`rounded-[2px] border px-2.5 py-1.5 font-mono text-[12px] transition-colors ${
                region === item.value
                  ? 'border-ember-ink bg-ember-ink/10 font-semibold text-ember-ink'
                  : 'border-ink/20 text-ink-muted hover:border-ink/40 hover:text-ink'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {zohoMode === 'app-password' ? (
        <form onSubmit={handleAppPasswordSubmit} className="mt-4">
          <ol className="space-y-2 text-[12px] leading-relaxed text-ink/75">
            <li>
              <span className="mr-2 font-mono text-[12px] text-ember-ink">01</span>
              Select your Zoho Data Center above (currently <strong>{activeRegion.label}</strong>).
            </li>
            <li>
              <span className="mr-2 font-mono text-[12px] text-ember-ink">02</span>
              Open{' '}
              <a
                href={securityUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-ember-ink underline underline-offset-2"
              >
                Zoho Account Security → App Passwords ↗
              </a>
            </li>
            <li>
              <span className="mr-2 font-mono text-[12px] text-ember-ink">03</span>
              Generate a new App Password named <strong>Proteus</strong>, paste it below, and click <strong>Verify &amp; Unlock Workspace</strong>.
            </li>
          </ol>
          <div className="mt-3 font-mono text-[12px] text-ink/65">
            IMAP: imappro.{activeRegion.domain}:993 · SMTP: smtppro.{activeRegion.domain}:465
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Zoho Email</label>
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={`you@${activeRegion.domain}`}
                className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:border-ink/50 focus:outline-none"
              />
            </div>
            <div>
              <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Display Name (optional)</label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your Name"
                className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-sm text-ink focus:border-ink/50 focus:outline-none"
              />
            </div>
          </div>
          <label className="mt-3 block font-mono text-[12px] uppercase tracking-wider text-ink-muted">App-Specific Password</label>
          <input
            required
            type="password"
            value={appPassword}
            onChange={(e) => setAppPassword(e.target.value)}
            placeholder="Paste Zoho App Password"
            className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 text-ink focus:border-ink/50 focus:outline-none"
          />
          {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
          <button
            type="submit"
            disabled={busy || !email.trim() || !appPassword.trim()}
            className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper hover:bg-ink/90 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {busy ? 'Verifying…' : 'Verify & Unlock Workspace'}
          </button>
        </form>
      ) : (
        <form onSubmit={handleOAuthSubmit} className="mt-4 space-y-3">
          <div className="text-[12px] leading-relaxed text-ink/75">
            Create a Self Client / Server-based app in Zoho API Console with Redirect URI:
            <div className="mt-2 flex items-center gap-2 rounded-[2px] border border-ink/15 bg-white/40 p-2">
              <code className="min-w-0 flex-1 break-all font-mono text-[12px] text-ink/80">{redirectUri}</code>
              <button
                type="button"
                onClick={() => void copyUri()}
                className="inline-flex shrink-0 items-center gap-1 rounded-[2px] border border-ink/20 px-2 py-1 font-mono text-[12px] uppercase tracking-wider text-ink/70 hover:border-ink/50 hover:text-ink"
              >
                {copied ? <Check className="h-3 w-3 text-foam-ink" /> : <Copy className="h-3 w-3" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
          <div>
            <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Zoho Client ID</label>
            <input
              required
              value={oauthClientId}
              onChange={(e) => setOauthClientId(e.target.value)}
              className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 font-mono text-[12px] text-ink focus:border-ink/50 focus:outline-none"
            />
          </div>
          <div>
            <label className="block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Zoho Client Secret</label>
            <input
              required
              type="password"
              value={oauthClientSecret}
              onChange={(e) => setOauthClientSecret(e.target.value)}
              className="mt-1.5 w-full rounded-[2px] border border-ink/20 bg-white/35 px-3 py-2 font-mono text-[12px] text-ink focus:border-ink/50 focus:outline-none"
            />
          </div>
          {error ? <p className="mt-3 text-sm text-ember-ink">{error}</p> : null}
          <button
            type="submit"
            disabled={busy || !oauthClientId.trim() || !oauthClientSecret.trim()}
            className="mt-2 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-sm font-medium text-paper hover:bg-ink/90 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
            {busy ? 'Redirecting to Zoho…' : 'Save & Sign In with Zoho'}
          </button>
        </form>
      )}
    </div>
  )
}
