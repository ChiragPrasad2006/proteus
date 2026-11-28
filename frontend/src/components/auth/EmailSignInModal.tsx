import { Loader2, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '@/lib/api'
import type { OAuthProvider } from '@/lib/googleAuth'

const PROVIDER_LABEL: Record<OAuthProvider, string> = {
  gmail: 'Google (Gmail)',
  outlook: 'Outlook',
  zoho: 'Zoho Mail',
}

export function EmailSignInModal({ isOpen, onClose, onSignedIn, note, provider = 'gmail' }: {
  isOpen: boolean
  onClose: () => void
  onSignedIn?: () => void
  note?: string
  provider?: OAuthProvider
}) {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen) return null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.identityLogin({
        email: email.trim(),
        display_name: displayName.trim() || email.trim().split('@')[0] || 'Proteus user',
        provider,
      })
      onSignedIn?.()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in with email.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Sign in with Email" className="fixed inset-0 z-50 flex items-center justify-center bg-cobalt/85 p-4">
      <form onSubmit={submit} className="w-full max-w-md rounded-[2px] border border-ink/15 bg-paper p-7 text-ink">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-ink-muted">
              Identity sign-in · {PROVIDER_LABEL[provider]}
            </p>
            <h2 className="mt-2 font-display text-3xl">Sign in with Email</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-muted hover:text-ink"><X className="h-5 w-5" /></button>
        </div>
        {note ? <p className="mb-5 border-l-2 border-ember-ink pl-3 text-[12px] leading-relaxed text-ink/70">{note}</p> : null}
        <label className="mb-1 block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Email address</label>
        <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mb-4 w-full rounded-[2px] border border-ink/20 bg-white/40 px-3 py-2.5 text-ink focus:border-ink/50 focus:outline-none" />
        <label className="mb-1 block font-mono text-[12px] uppercase tracking-wider text-ink-muted">Display name</label>
        <input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="mb-5 w-full rounded-[2px] border border-ink/20 bg-white/40 px-3 py-2.5 text-ink focus:border-ink/50 focus:outline-none" />
        {error ? <p className="mb-4 text-sm text-ember-ink">{error}</p> : null}
        <button type="submit" disabled={busy} className="inline-flex w-full items-center justify-center gap-2 rounded-pill bg-ink px-5 py-3 text-sm font-medium text-paper disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {busy ? 'Signing in…' : 'Continue to Workspace →'}
        </button>
      </form>
    </div>
  )
}
