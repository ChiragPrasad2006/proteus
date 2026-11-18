import { Check, ChevronsUpDown, Plus, Plug, X, Upload, Loader2, AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useClickOutside } from '@/hooks/useClickOutside'
import { useAppStore } from '@/stores/useAppStore'
import { api } from '@/lib/api'
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
  const [oauthStatus, setOauthStatus] = useState<'idle' | 'checking' | 'configured' | 'missing'>('idle')
  const [showOauthModal, setShowOauthModal] = useState(false)
  const [uploadingCredentials, setUploadingCredentials] = useState(false)
  const [credentialsJson, setCredentialsJson] = useState('')

  const popRef = useClickOutside<HTMLDivElement>(open, () => {
    setOpen(false)
    setAdding(false)
    setShowOauthModal(false)
  })

  const active = accounts.find((a) => a.id === activeAccountId) ?? accounts[0]!

  const checkOauthStatus = async () => {
    setOauthStatus('checking')
    try {
      const res = await api.googleAuthStatus()
      setOauthStatus(res.configured ? 'configured' : 'missing')
    } catch {
      setOauthStatus('missing')
    }
  }

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.email.trim()) return

    if (form.provider === 'gmail') {
      // Check OAuth status before adding
      await checkOauthStatus()
      if (oauthStatus === 'missing') {
        setShowOauthModal(true)
        return
      }
      // OAuth is configured, start the OAuth flow
      try {
        const res = await api.googleAuthStart()
        // Redirect to Google OAuth consent screen
        window.location.href = res.auth_url
        return
      } catch (err) {
        console.error('Failed to start OAuth:', err)
        alert('Failed to start Google Sign-In. Please try again.')
        return
      }
    }

    // For non-Gmail providers, just add the account locally
    addAccount({
      name: form.name.trim() || form.email.split('@')[0]!,
      email: form.email.trim(),
      provider: form.provider,
    })
    setForm({ name: '', email: '', provider: 'gmail' })
    setAdding(false)
    setOpen(false)
  }

  const handleUploadCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!credentialsJson.trim()) return
    setUploadingCredentials(true)
    try {
      await api.googleAuthUploadCredentials(credentialsJson)
      setShowOauthModal(false)
      setCredentialsJson('')
      // After upload, check status and start OAuth
      await checkOauthStatus()
      if (oauthStatus === 'configured') {
        const res = await api.googleAuthStart()
        window.location.href = res.auth_url
      }
    } catch (err) {
      console.error('Failed to upload credentials:', err)
      alert('Failed to upload credentials. Please check the JSON format.')
    } finally {
      setUploadingCredentials(false)
    }
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result as string
      setCredentialsJson(content)
    }
    reader.readAsText(file)
  }

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
          {!adding && !showOauthModal ? (
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
          ) : showOauthModal ? (
            <div className="p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
                  Google OAuth Setup
                </p>
                <button
                  type="button"
                  aria-label="Cancel"
                  onClick={() => setShowOauthModal(false)}
                  className="text-fg-faint hover:text-fg"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="rounded-xl border border-hairline bg-ink/60 p-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#fbbf24]" strokeWidth={1.5} />
                    <div>
                      <p className="text-[13px] font-medium text-fg">Google OAuth credentials not configured</p>
                      <p className="mt-1 text-[12px] text-fg-faint">
                        To connect Gmail, you need to provide a <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">client_secret.json</code> file
                        from Google Cloud Console.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="space-y-2 text-[12px] text-fg-faint">
                  <p><strong>Step 1:</strong> Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="text-accent underline">Google Cloud Console → APIs & Services → Credentials</a></p>
                  <p><strong>Step 2:</strong> Click <strong>Create Credentials</strong> → <strong>OAuth client ID</strong></p>
                  <p><strong>Step 3:</strong> Choose <strong>Desktop app</strong> as application type</p>
                  <p><strong>Step 4:</strong> Add authorized redirect URI: <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">http://localhost:8000/api/auth/google/callback</code></p>
                  <p><strong>Step 5:</strong> Download the JSON file and upload it below</p>
                </div>

                <form onSubmit={handleUploadCredentials}>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                    Upload client_secret.json
                  </label>
                  <div className="mb-3 relative">
                    <input
                      type="file"
                      accept=".json"
                      onChange={handleFileUpload}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    />
                    <div className={cn(
                      'flex items-center justify-center gap-2 rounded-xl border border-dashed p-6 transition-colors duration-300 ease-proteus',
                      credentialsJson ? 'border-accent/50 bg-accent/[0.05]' : 'border-hairline hover:border-accent/30'
                    )}>
                      {credentialsJson ? (
                        <>
                          <Upload className="h-5 w-5 text-accent" />
                          <span className="font-mono text-[12px] text-fg">File selected ✓</span>
                        </>
                      ) : (
                        <>
                          <Upload className="h-5 w-5 text-fg-faint" />
                          <span className="font-mono text-[12px] text-fg-muted">Drag & drop or click to select</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="flex-1"
                      onClick={() => setShowOauthModal(false)}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      size="sm"
                      className="flex-1"
                      leftIcon={uploadingCredentials ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
                      disabled={!credentialsJson.trim() || uploadingCredentials}
                    >
                      {uploadingCredentials ? 'Saving…' : 'Save & Continue to Google Sign-In'}
                    </Button>
                  </div>
                </form>
              </div>
            </div>
          ) : (
            <form
              className="p-4"
              onSubmit={handleAddAccount}
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
