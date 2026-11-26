import { Download, LoaderCircle, Pencil, RotateCcw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { IconButton } from '@/components/ui/IconButton'
import { api } from '@/lib/api'
import { forgetRule, getPilotMetrics, listRecipientRules, resetProfile, updateRule, type RecipientRule } from '@/lib/localAdapter'
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

interface RuleRow {
  rule_id: string
  text: string
  scope: 'global' | 'recipient'
  recipient_email?: string
}

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
  const [resetting, setResetting] = useState(false)
  const [recipientRules, setRecipientRules] = useState<RecipientRule[]>([])
  const [rulesLoading, setRulesLoading] = useState(false)
  // Render-phase adjustment: reload per-recipient rules whenever the drawer opens.
  const [rulesAccount, setRulesAccount] = useState<string | null>(null)
  const rulesKey = open && accountId ? accountId : null
  if (rulesKey !== rulesAccount) {
    setRulesAccount(rulesKey)
    setRecipientRules([])
    setRulesLoading(true)
  }
  const [editingRule, setEditingRule] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, setOpen])

  // Per-recipient rules are server state: fetch them once per drawer open.
  useEffect(() => {
    if (!rulesAccount) return
    let cancelled = false
    listRecipientRules(rulesAccount)
      .then((rules) => { if (!cancelled) setRecipientRules(rules) })
      .catch(() => { if (!cancelled) setRecipientRules([]) })
      .finally(() => { if (!cancelled) setRulesLoading(false) })
    return () => { cancelled = true }
  }, [rulesAccount])

  if (!open) return null

  const close = () => setOpen(false)

  const refreshProfile = async () => {
    if (!accountId) return
    try {
      setStyleProfile(await api.profile(accountId))
    } catch {
      setStyleProfile(null)
    }
  }

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

  const exportPilotMetrics = async () => {
    if (!accountId) return
    try {
      const metrics = await getPilotMetrics(accountId)
      const blob = new Blob([JSON.stringify(metrics, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'proteus-local-usage-metrics.json'
      anchor.click()
      URL.revokeObjectURL(url)
      toast('Local usage metrics exported as JSON.')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not export local usage metrics.', 'warning', 6000)
    }
  }

  const saveEdit = async (row: RuleRow) => {
    const text = editText.trim()
    if (!accountId || !text) return
    try {
      await updateRule(accountId, row.rule_id, text, row.scope)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not edit the rule.', 'warning', 6000)
      return
    }
    setEditingRule(null)
    await Promise.all([refreshProfile(), reloadRecipientRules()])
    toast('Rule updated.')
  }

  const forget = async (row: RuleRow) => {
    if (!accountId) return
    try {
      await forgetRule(accountId, row.rule_id, row.scope)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not forget the rule.', 'warning', 6000)
      return
    }
    await Promise.all([refreshProfile(), reloadRecipientRules()])
    toast('Rule forgotten.')
  }

  const reloadRecipientRules = async () => {
    if (!accountId) return
    try {
      setRecipientRules(await listRecipientRules(accountId))
    } catch {
      setRecipientRules([])
    }
  }

  const confirmReset = async () => {
    if (!accountId || resetting) return
    setResetting(true)
    try {
      setStyleProfile(await resetProfile(accountId))
      await reloadRecipientRules()
      toast('Style profile reset.', 'success')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not reset the profile.', 'warning', 6000)
    } finally {
      setResetting(false)
      setResetOpen(false)
    }
  }

  const globalRules: RuleRow[] = (profile?.global_learned_rules ?? []).map((text, index) => ({
    rule_id: `global:${index}`,
    text,
    scope: 'global',
  }))
  const recipientRuleRows: RuleRow[] = recipientRules.map((rule) => ({
    rule_id: rule.rule_id,
    text: rule.text,
    scope: 'recipient',
    recipient_email: rule.recipient_email,
  }))

  const renderRule = (row: RuleRow) => {
    const isEditing = editingRule === row.rule_id
    return (
      <li key={row.rule_id} className="rounded-card border border-ink-hairline bg-white/30 p-3">
        {isEditing ? (
          <div className="flex items-center gap-2">
            <input
              value={editText}
              onChange={(event) => setEditText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void saveEdit(row)
                if (event.key === 'Escape') setEditingRule(null)
              }}
              aria-label="Edit rule"
              className="min-w-0 flex-1 rounded-card border border-ink-hairline bg-paper px-2.5 py-1.5 text-[13px] focus:border-ink/60 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void saveEdit(row)}
              className="shrink-0 rounded-pill bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-send-hover"
            >
              Save
            </button>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-3">
            <p className="min-w-0 text-[13px] leading-relaxed">
              “{row.text}”
              {row.recipient_email ? <span className="ml-1.5 font-mono text-[12px] text-ink-faint">{row.recipient_email}</span> : null}
            </p>
            <div className="flex shrink-0 items-center gap-1">
              <IconButton label="Edit rule" surface="paper" className="h-7 w-7" onClick={() => { setEditingRule(row.rule_id); setEditText(row.text) }}>
                <Pencil className="h-3 w-3" />
              </IconButton>
              <button
                type="button"
                onClick={() => void forget(row)}
                className="rounded-pill border border-ink-hairline px-2.5 py-1 text-[12px] text-ink-muted hover:border-ink/50 hover:text-ink"
              >
                Forget
              </button>
            </div>
          </div>
        )}
      </li>
    )
  }

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
                {profile.corpus_statistics.total_sent_emails} sent emails · {profile.corpus_statistics.clean_emails_retained} retained · {globalRules.length} global rules
              </p>
            </section>

            {/* Learned rules */}
            <section>
              <h3 className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted">Global rules</h3>
              {globalRules.length === 0 ? (
                <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">No global rules yet. Proteus learns atomic rules from the edits you make before sending.</p>
              ) : (
                <ul className="mt-2.5 space-y-2">{globalRules.map(renderRule)}</ul>
              )}
            </section>

            <section>
              <h3 className="font-mono text-[12px] uppercase tracking-[0.14em] text-ink-muted">Per-recipient rules</h3>
              {rulesLoading ? (
                <p className="mt-2 text-[13px] text-ink-muted">Loading…</p>
              ) : recipientRuleRows.length === 0 ? (
                <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">No recipient-specific rules yet. They appear after Proteus learns an edit pattern for a particular person.</p>
              ) : (
                <ul className="mt-2.5 space-y-2">{recipientRuleRows.map(renderRule)}</ul>
              )}
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
            <section className="space-y-2.5 border-t border-ink-hairline pt-5">
              <div className="flex flex-wrap items-center gap-2.5">
                <button type="button" onClick={exportProfile} className="inline-flex items-center gap-2 rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">
                  <Download className="h-4 w-4" aria-hidden /> Export profile
                </button>
                <button type="button" onClick={() => setResetOpen(true)} className="inline-flex items-center gap-2 rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink-muted hover:border-ember-ink/60 hover:text-ember-ink">
                  <RotateCcw className="h-4 w-4" aria-hidden /> Reset profile
                </button>
              </div>
              <button
                type="button"
                onClick={() => void exportPilotMetrics()}
                className="inline-flex items-center gap-2 rounded-pill border border-ink-hairline px-3.5 py-1.5 text-[12px] text-ink-muted hover:border-ink/50 hover:text-ink"
              >
                <Download className="h-3.5 w-3.5" aria-hidden /> Export local usage metrics (JSON)
              </button>
            </section>
          </div>
        )}
      </aside>

      <Modal open={resetOpen} onClose={() => setResetOpen(false)} label="Reset style profile">
        <div className="p-6">
          <h2 className="font-display text-2xl">Reset profile?</h2>
          <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
            This forgets every learned rule and restores the stylometry derived from your sent mail. Your mailbox connection, contacts and Sent corpus stay untouched.
          </p>
          <div className="mt-6 flex items-center justify-end gap-2.5">
            <button type="button" onClick={() => setResetOpen(false)} className="rounded-pill border border-ink-hairline px-4 py-2 text-[13px] font-medium text-ink hover:border-ink/50 hover:bg-ink/5">Cancel</button>
            <button type="button" onClick={() => void confirmReset()} disabled={resetting} className="inline-flex items-center gap-2 rounded-pill bg-ink px-5 py-2 text-[13px] font-medium text-paper hover:bg-send-hover disabled:opacity-50">
              {resetting ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {resetting ? 'Resetting…' : 'Reset profile'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default StyleProfile