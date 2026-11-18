import { Check, Loader2, Plug, X, AlertTriangle, Mail, Lock, Shield, Upload } from 'lucide-react'
import { useState, useCallback } from 'react'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import type { } from '@/types'

interface ConnectGmailModalProps {
  isOpen: boolean
  onClose: () => void
}

export function ConnectGmailModal({ isOpen, onClose }: ConnectGmailModalProps) {
  const [activeTab, setActiveTab] = useState<'oauth' | 'app-password'>('oauth')
  const [oauthStatus, setOauthStatus] = useState<'idle' | 'checking' | 'configured' | 'missing'>('idle')
  const [uploadingCredentials, setUploadingCredentials] = useState(false)
  const [credentialsJson, setCredentialsJson] = useState('')
  const [startingOAuth, setStartingOAuth] = useState(false)
  const [appPasswordForm, setAppPasswordForm] = useState({
    email: '',
    appPassword: '',
    displayName: '',
  })
  const [connectingAppPassword, setConnectingAppPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const checkOauthStatus = useCallback(async () => {
    setOauthStatus('checking')
    try {
      const res = await api.googleAuthStatus()
      setOauthStatus(res.configured ? 'configured' : 'missing')
    } catch {
      setOauthStatus('missing')
    }
  }, [])

  const handleUploadCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!credentialsJson.trim()) return
    setUploadingCredentials(true)
    setError(null)
    try {
      await api.googleAuthUploadCredentials(credentialsJson)
      await checkOauthStatus()
      if (oauthStatus === 'configured') {
        const res = await api.googleAuthStart()
        window.location.href = res.auth_url
      }
    } catch (err) {
      console.error('Failed to upload credentials:', err)
      setError('Failed to upload credentials. Please check the JSON format.')
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

  const handleStartOAuth = async () => {
    setStartingOAuth(true)
    setError(null)
    try {
      const res = await api.googleAuthStart()
      window.location.href = res.auth_url
    } catch (err) {
      console.error('Failed to start OAuth:', err)
      setError('Failed to start Google Sign-In. Please try again.')
    } finally {
      setStartingOAuth(false)
    }
  }

  const handleConnectAppPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!appPasswordForm.email.trim() || !appPasswordForm.appPassword.trim()) return
    setConnectingAppPassword(true)
    setError(null)
    try {
      const normalizedPassword = appPasswordForm.appPassword.replace(/\s+/g, '')
      const account = await api.identityLogin({
        email: appPasswordForm.email.trim(),
        display_name: appPasswordForm.displayName.trim() || appPasswordForm.email.trim().split('@')[0] || 'Gmail user',
      })
      await api.connectAppPassword(normalizedPassword, account.id)
      onClose()
    } catch (err) {
      console.error('Failed to connect via App Password:', err)
      setError(err instanceof Error ? err.message : 'Failed to connect. Check email and App Password.')
    } finally {
      setConnectingAppPassword(false)
    }
  }

  if (!isOpen) return null

  return (
    <div
      role="dialog"
      aria-label="Connect Gmail Account"
      className={cn(
        'glass-strong fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in',
        'bg-black/60 backdrop-blur-sm',
      )}
    >
      <div className="relative w-full max-w-lg">
        <div className="glass-strong rounded-[24px] border border-hairline overflow-hidden shadow-[0_30px_70px_-30px_rgba(0,0,0,0.95)]">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-hairline">
            <div className="flex items-center gap-3">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-accent/10">
                <Mail className="h-5 w-5 text-accent" />
              </span>
              <div>
                <p className="font-medium text-fg">Connect Gmail Account</p>
                <p className="text-[12px] text-fg-faint">Choose how you'd like to connect</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-fg-faint hover:text-fg transition-colors"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-hairline">
            <button
              type="button"
              onClick={() => setActiveTab('oauth')}
              className={cn(
                'flex-1 py-3 px-4 font-mono text-[11px] uppercase tracking-wider transition-colors border-b-2',
                activeTab === 'oauth'
                  ? 'border-accent text-accent'
                  : 'border-transparent text-fg-faint hover:text-fg',
              )}
            >
              <Shield className="inline h-3.5 w-3.5 mr-1.5" />
              Google OAuth2
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('app-password')}
              className={cn(
                'flex-1 py-3 px-4 font-mono text-[11px] uppercase tracking-wider transition-colors border-b-2',
                activeTab === 'app-password'
                  ? 'border-accent text-accent'
                  : 'border-transparent text-fg-faint hover:text-fg',
              )}
            >
              <Lock className="inline h-3.5 w-3.5 mr-1.5" />
              App Password
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-4">
            {activeTab === 'oauth' ? (
              <div className="space-y-4">
                {oauthStatus === 'configured' ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 p-3 rounded-xl border border-accent/30 bg-accent/[0.05]">
                      <Check className="h-5 w-5 text-accent shrink-0" />
                      <div>
                        <p className="font-medium text-fg">Google OAuth is configured</p>
                        <p className="text-[12px] text-fg-faint">Ready to sign in with your Google account</p>
                      </div>
                    </div>
                    <Button
                      className="w-full"
                      leftIcon={startingOAuth ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}
                      disabled={startingOAuth}
                      onClick={handleStartOAuth}
                    >
                      {startingOAuth ? 'Redirecting…' : 'Continue with Google'}
                    </Button>
                  </div>
                ) : (
                  <>
                    <div className="rounded-xl border border-hairline bg-ink/60 p-4">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#fbbf24]" strokeWidth={1.5} />
                        <div>
                          <p className="text-[13px] font-medium text-fg">Google OAuth credentials not configured</p>
                          <p className="mt-1 text-[12px] text-fg-faint">
                            To connect Gmail via OAuth, you need to provide a{' '}
                            <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">
                              client_secret.json
                            </code>{' '}
                            from Google Cloud Console.
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="space-y-2 text-[12px] text-fg-faint">
                      <p>
                        <strong>Step 1:</strong>{' '}
                        <a
                          href="https://console.cloud.google.com/apis/credentials"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent underline"
                        >
                          Google Cloud Console → APIs & Services → Credentials
                        </a>
                      </p>
                      <p><strong>Step 2:</strong> Click <strong>Create Credentials</strong> → <strong>OAuth client ID</strong></p>
                      <p><strong>Step 3:</strong> Choose <strong>Desktop app</strong> as application type</p>
                      <p>
                        <strong>Step 4:</strong> Add authorized redirect URI:{' '}
                        <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">
                          http://localhost:8000/api/auth/google/callback
                        </code>
                      </p>
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
                        <div
                          className={cn(
                            'flex items-center justify-center gap-2 rounded-xl border border-dashed p-6 transition-colors duration-300 ease-proteus',
                            credentialsJson ? 'border-accent/50 bg-accent/[0.05]' : 'border-hairline hover:border-accent/30',
                          )}
                        >
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

                      {error && (
                        <div className="mb-3 p-3 rounded-xl border border-red/30 bg-red/[0.05] text-red text-[12px]">
                          {error}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          className="flex-1"
                          onClick={onClose}
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
                  </>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-xl border border-hairline bg-ink/60 p-4">
                  <div className="flex items-start gap-3">
                    <Lock className="mt-0.5 h-5 w-5 shrink-0 text-accent" strokeWidth={1.5} />
                    <div>
                      <p className="text-[13px] font-medium text-fg">Instant Gmail via App Password</p>
                      <p className="mt-1 text-[12px] text-fg-faint">
                        Use a 16-character Google App Password with IMAP/SMTP. No Google Cloud setup required.
                        <a
                          href="https://support.google.com/accounts/answer/185833"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent underline ml-1"
                        >
                          How to create one →
                        </a>
                      </p>
                    </div>
                  </div>
                </div>

                <div className="space-y-3 text-[12px] text-fg-faint">
                  <p><strong>IMAP:</strong> <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">imap.gmail.com:993</code> (SSL)</p>
                  <p><strong>SMTP:</strong> <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">smtp.gmail.com:465</code> (SSL)</p>
                  <p><strong>Folder:</strong> <code className="font-mono text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded">Sent</code></p>
                </div>

                <form onSubmit={handleConnectAppPassword}>
                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                    Display name (optional)
                  </label>
                  <input
                    value={appPasswordForm.displayName}
                    onChange={(e) => setAppPasswordForm((f) => ({ ...f, displayName: e.target.value }))}
                    placeholder="Your Name"
                    className="mb-3 w-full rounded-xl border border-hairline bg-ink/60 px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent/50 focus:outline-none"
                  />

                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                    Gmail address
                  </label>
                  <input
                    type="email"
                    required
                    value={appPasswordForm.email}
                    onChange={(e) => setAppPasswordForm((f) => ({ ...f, email: e.target.value }))}
                    placeholder="you@gmail.com"
                    className="mb-3 w-full rounded-xl border border-hairline bg-ink/60 px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent/50 focus:outline-none"
                  />

                  <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                    16-character App Password
                  </label>
                  <input
                    type="password"
                    required
                    value={appPasswordForm.appPassword}
                    onChange={(e) => setAppPasswordForm((f) => ({ ...f, appPassword: e.target.value.replace(/\s+/g, '') }))}
                    onPaste={(e) => {
                      e.preventDefault()
                      const normalized = e.clipboardData.getData('text').replace(/\s+/g, '')
                      setAppPasswordForm((f) => ({ ...f, appPassword: normalized }))
                    }}
                    placeholder="xxxx xxxx xxxx xxxx"
                    className="mb-3 w-full rounded-xl border border-hairline bg-ink/60 px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent/50 focus:outline-none font-mono"
                    maxLength={16}
                  />

                  {error && (
                    <div className="mb-3 p-3 rounded-xl border border-red/30 bg-red/[0.05] text-red text-[12px]">
                      {error}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="flex-1"
                      onClick={onClose}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      size="sm"
                      className="flex-1"
                      leftIcon={connectingAppPassword ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />}
                      disabled={connectingAppPassword}
                    >
                      {connectingAppPassword ? 'Connecting…' : 'Connect & Sync Sent Mail'}
                    </Button>
                  </div>
                </form>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ConnectGmailModal