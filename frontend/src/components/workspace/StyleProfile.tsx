import { Download, LoaderCircle, Pencil, RotateCcw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { IconButton } from '@/components/ui/IconButton'
import { api } from '@/lib/api'
import { clearRuleOverrides, getForgottenRules, getRuleOverrides, forgetRule, setRuleOverride } from '@/lib/localAdapter'
import { cn } from '@/lib/utils'
import { useActiveAccount, useAppStore } from '@/stores/useAppStore'
import { toast } from '@/stores/useToastStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'
import type { AudienceMode } from '@/types'

const AUDIENCE_TABS: { mode: AudienceMode; label: string; copy: string }[] = [
  { mode: '1on1_private', label: '1:1 Private', copy: 'One recipient, no copies. Proteus uses your personal voice for this relationship — your usual greeting, your exact sign-off, and the directness you normally use with them.' },
  { mode: 'group_cc', label: 'Group CC', copy: 'A shared audience. Proteus writes for the whole group: inclusive greetings, neutral asides, and nothing that assumes a private context between you and one reader.' },
  { mode: 'broadcast_bcc', label: 'Broadcast BCC', copy: 'Hidden recipients. Proteus keeps the tone impersonal and uniform — no single person is addressed, and the letter reads the same for everyone who receives it.' },
]

/** Paper slide-over sheet with the real stylometry fingerprint and learned rules. */
export function StyleProfile() {
  const open = useWorkspaceUI((state) => state.profileOpen)
  const setOpen = useWorkspaceUI((state) => state.setProfileOpen)
  const profile = useAppStore((state) => state.styleProfile)
  const setStyleProfile = useAppStore((state) => state.setStyleProfile)
  const accountId = useAppStore((state) => state.activeAccountId)
  const account = useActiveAccount()

  const [tab, setTab] = useState<AudienceMode>('1on1_private')
  const [building, setBuilding] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [forgotten, setForgotten] = useState<string[]>([])
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [editingRule, setEditingRule] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  // Load local rule overrides when the drawer opens (render-phase adjustment).
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const loadKey = open && accountId ? accountId : null
  if (loadKey !== loadedFor) {
    setLoadedFor(loadKey)
    if (loadKey !== null) {
      setForgotten(getForgottenRules(loadKey))
      setOverrides(getRuleOverrides(loadKey))
    }
  }

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, setOpen])

  if (!open) return null

  const close = () => setOpen(false)

  const buildProfile = async () => {
    if (!accountId || building) return
    setBuilding(true)
    try {
      const result = await api.buildProfile(false, accountId)
      setStyleProfile(result)
      toast('Style profile calibrated from your sent mail.', 'success')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not build the profile yet.', 'warning', 6000)
    } finally {
      setBuilding(false)
    }
  }

  const exportProfile = () => {
    if (!profile) return
    const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `proteus-style-profile-${account?.email ?? 'account'}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    toast('Profile exported as JSON.')
  }

  const confirmReset = () => {
    // TODO(backend): POST /api/profile/reset — server-side reset is not exposed yet.
    // Until then, reset clears local rule overrides/forgets and re-reads the server profile.
    if (accountId) {
      clearRuleOverrides(accountId)
      setForgotten([])
      setOverrides({})
      void api.profile(accountId).then(setStyleProfile).catch(() => setStyleProfile(null))
    }
    setResetOpen(false)
    toast('Local rule overrides cleared. Server-side reset arrives with the profile-reset endpoint.')
  }

  const rules = profile?.global_learned_rules ?? []
  const visibleRules = rules.filter((rule) => !forgotten.includes(rule))
  const stylometry = profile?.deterministic_stylometry
  const styleCard = profile?.global_style_card
  const topGreeting = stylometry?.top_greetings?.[0]

  return (
    <div className="fixed inset-0 z-[65] flex justify-end bg-ink/50" onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}>
      <aside role="dialog" aria-modal="true" aria-label="Style Profile" className="on-paper flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-ink-hairline bg-paper text-ink">
        <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-ink-hairline bg-paper px-5 py-4">
          <img src="/art/proteus-face.webp" alt="" aria-hidden className="engraving-multiply h-10 w-10 rounded-pill object-cover" />
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-xl leading-tight">Style Profile</h2>
            <p className="truncate font-mono text-[12px] text-ink-muted">{account?.email ?? 'No account'}</p>
          </div>
          <IconButton label="Close Style Profile" surface="paper" onClick={close}>
            <X className="h-4 w-4" />
          </IconButton>
        </div>

        {!profile ? (
          <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
            <img src="/art/proteus-waves.webp" alt="" aria-hidden className="engraving-multiply mb-4 h-20 w-32 object-contain opacity-60" />
            <p className="font-display text-xl">No style profile yet</p>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">Connect a mailbox, then calibrate Proteus’s voice from your sent emails.</p>
            <button
              type="button"
              onClick={() => void buildProfile()}
              disabled={building || !account?.mailboxConnected}
              className="mt-5 inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2.5 text-[13px] font-medium text-paper hover:bg-send-hover disabled:opacity-50"
            >
              {building ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {building ? 'Calibrating…' : 'Calibrate voice'}
            </button>
            {!account?.mailboxConnected ? <p className="mt-3 text-[12px] text-ink-faint">Unlock the mailbox first.</p> : null}
          </div>
        ) : (
          <div className="flex-1 space-y-6 px-5 py-5">
            {/* Stylometry fingerprint */}
            <section>
              <h3 className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted">Stylometry fingerprint</h3>
              <dl className="mt-3 grid grid-cols-2 gap-2.5">
                <div className="rounded-card border border-ink-hairline bg-white/30 p-3">
                  <dt className="font-mono text-[12px] text-ink-muted">Top greeting</dt>
                  <dd className="mt-1 text-[13px] font-medium">{topGreeting ? `${topGreeting.pattern} · ${Math.round(topGreeting.pct)}%` : '—'}</dd>
                </div>
                <div className="rounded-card border border-ink-hairline bg-white/30 p-3">
                  <dt className="font-mono text-[12px] text-ink-muted">Exact sign-off</dt>
                  <dd className="mt-1 truncate text-[13px] font-medium" title={stylometry?.exact_signoff}>{stylometry?.exact_signoff || '—'}</dd>
                </div>
                <div className="rounded-card border border-ink-hairline bg-white/30 p-3">
                  <dt className="font-mono text-[12px] text-ink-muted">Avg sentence</dt>
                  <dd className="mt-1 text-[13px] font-medium">{stylometry ? `${stylometry.avg_sentence_length_words.toFixed(1)} words` : '—'}</dd>
                </div>
                <div className="rounded-card border border-ink-hairline bg-white/30 p-3">
                  <dt className="font-mono text-[12px] text-ink-muted">Avg email</dt>
                  <dd className="mt-1 text-[13px] font-medium">{stylometry ? `${Math.round(stylometry.avg_email_length_words)} words` : '—'}</dd>
                </div>
              </dl>
              {styleCard ? (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {[styleCard.formality, styleCard.tone, styleCard.directness ? `${styleCard.directness} directness` : '', styleCard.vocabulary_level].filter(Boolean).map((descriptor) => (
                    <span key={descriptor} className="rounded-pill border border-ink-hairline px-3 py-1 text-[12px] text-ink-muted">{descriptor}</span>
                  ))}
                </div>
              ) : null}
              <p className="mt-3 font-mono text-[12px] text-ink-muted">
                {profile.corpus_statistics.total_sent_emails} sent emails · {profile.corpus_statistics.clean_emails_retained} retained · {rules.length} learned rules
              </p>
            </section>

            {/* Learned rules */}
            <section>
              <h3 className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted">Learned rules</h3>
              {visibleRules.length === 0 ? (
                <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">No active rules yet. Proteus learns atomic rules from the edits you make before sending.</p>
              ) : (
                <ul className="mt-2.5 space-y-2">
                  {visibleRules.map((rule) => {
                    const displayed = overrides[rule] ?? rule
                    const isEditing = editingRule === rule
                    return (
                      <li key={rule} className="rounded-card border border-ink-hairline bg-white/30 p-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <input
                              value={editText}
                              onChange={(event) => setEditText(event.target.value)}
                              onKeyDown={(event) => {
                                if (event.key === 'Enter' && accountId) {
                                  // TODO(backend): PATCH /api/profile/rules/{rule_id} — edits are local overrides until then.
                                  setRuleOverride(accountId, rule, editText.trim() || rule)
                                  setOverrides(getRuleOverrides(accountId))
                                  setEditingRule(null)
                                }
                                if (event.key === 'Escape') setEditingRule(null)
                              }}
                              aria-label="Edit rule"
                              className="min-w-0 flex-1 rounded-card border border-ink-hairline bg-paper px-2.5 py-1.5 text-[13px] focus:border-ink/60 focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => {
                                if (!accountId) return
                                setRuleOverride(accountId, rule, editText.trim() || rule)
                                setOverrides(getRuleOverrides(accountId))
                                setEditingRule(null)
                              }}
                              className="shrink-0 rounded-pill bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-send-hover"
                            >
                              Save
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-start justify-between gap-3">
                            <p className="text-[13px] leading-relaxed">“{displayed}”{overrides[rule] ? <span className="ml-1.5 font-mono text-[12px] text-ink-faint">(edited locally)</span> : null}</p>
                            <div className="flex shrink-0 items-center gap-1">
                              <IconButton label="Edit rule" surface="paper" className="h-7 w-7" onClick={() => { setEditingRule(rule); setEditText(displayed) }}>
                                <Pencil className="h-3 w-3" />
                              </IconButton>
                              {/* TODO(backend): DELETE /api/profile/rules/{rule_id} — forget hides locally until then. */}
                              <button
                                type="button"
                                onClick={() => {
                                  if (!accountId) return
                                  forgetRule(accountId, rule)
                                  setForgotten(getForgottenRules(accountId))
                                  toast('Rule hidden on this device.')
                                }}
                                className="rounded-pill border border-ink-hairline px-2.5 py-1 text-[12px] text-ink-muted hover:border-ink/50 hover:text-ink"
                              >
                                Forget
                              </button>
                            </div>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
              {/* TODO(backend): GET /api/profile/recipient-rules — per-recipient rules are not exposed by the API yet. */}
              <p className="mt-2.5 text-[12px] leading-relaxed text-ink-faint">Per-recipient rules will appear here once the local API exposes them.</p>
            </section>

            {/* Audience tabs */}
            <section>
              <h3 className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted">Audience adaptation</h3>
              <div className="mt-2.5 flex gap-1 rounded-card border border-ink-hairline p-1" role="tablist" aria-label="Audience modes">
                {AUDIENCE_TABS.map((item) => (
                  <button
                    key={item.mode}
                    type="button"
                    role="tab"
                    aria-selected={tab === item.mode}
                    onClick={() => setTab(item.mode)}
                    className={cn('flex-1 rounded-[2px] px-2 py-1.5 text-[12px] font-medium transition-colors', tab === item.mode ? 'bg-ink text-paper' : 'text-ink-muted hover:bg-ink/5')}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <p className="mt-2.5 text-[13px] leading-relaxed text-ink-muted">{AUDIENCE_TABS.find((item) => item.mode === tab)?.copy}</p>
            </section>

            {/* Export / reset */}
            <section className="flex items-center gap-2.5 border-t border-ink-hairline pt-5">
              <button type="button" onClick={exportProfile} className="inline-flex items-center gap-2 rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
                <Download className="h-4 w-4" aria-hidden /> Export profile
              </button>
              <button type="button" onClick={() => setResetOpen(true)} className="inline-flex items-center gap-2 rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink-muted hover:border-ember-ink/60 hover:text-ember-ink">
                <RotateCcw className="h-4 w-4" aria-hidden /> Reset profile
              </button>
            </section>
          </div>
        )}
      </aside>

      <Modal open={resetOpen} onClose={() => setResetOpen(false)} label="Reset style profile">
        <div className="p-6">
          <h2 className="font-display text-2xl">Reset profile?</h2>
          <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
            This clears your local rule edits and hidden rules, then re-reads the profile from the server. A full server-side reset is not available yet.
          </p>
          <div className="mt-6 flex items-center justify-end gap-2.5">
            <button type="button" onClick={() => setResetOpen(false)} className="rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">Cancel</button>
            <button type="button" onClick={confirmReset} className="rounded-pill bg-ink px-5 py-2 text-[13px] font-medium text-paper hover:bg-send-hover">Reset local overrides</button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default StyleProfile