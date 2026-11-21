import { useMutation } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  Database,
  Fingerprint,
  Lock,
  Mail,
  Plug,
  Radio,
  Quote,
  Server,
  ShieldCheck,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Toggle } from '@/components/ui/Toggle'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

type TabId = 'connect' | 'voice' | 'safety'

const TABS: { id: TabId; index: string; label: string; rotate: number }[] = [
  { id: 'connect', index: '01', label: 'Connect Client', rotate: -2 },
  { id: 'voice', index: '02', label: 'Voice & Stylometry', rotate: -1.5 },
  { id: 'safety', index: '03', label: 'Audience & Safety Rules', rotate: -1 },
]

const PROVIDERS = [
  {
    id: 'gmail',
    name: 'Gmail',
    icon: Mail,
    method: 'OAuth 2.0',
    detail: 'Read-only scope on your Sent label. Tokens stay in your local vault.',
  },
  {
    id: 'outlook',
    name: 'Outlook 365',
    icon: Server,
    method: 'OAuth 2.0',
    detail: 'Microsoft Graph, delegated SentItems. Tenant-scoped token cache.',
  },
  {
    id: 'imap',
    name: 'IMAP / Mbox',
    icon: Database,
    method: 'Credentials · file',
    detail: 'Any IMAP host, or drop an exported .mbox and index it offline.',
  },
]

const METRICS = [
  { label: 'Avg sentence', value: '14.2', unit: 'words' },
  { label: 'Avg email', value: '118', unit: 'words' },
  { label: 'Exclamation rate', value: '6', unit: '%' },
  { label: 'Emoji rate', value: '0.4', unit: '%' },
  { label: 'Bullet lists', value: '38', unit: '%' },
  { label: 'Paragraphs', value: '2.4', unit: 'avg' },
]

const GREETINGS = [
  { pattern: 'Hi {first},', pct: 46 },
  { pattern: 'Hello {first},', pct: 22 },
  { pattern: 'Hey {first},', pct: 14 },
  { pattern: '{first} —', pct: 9 },
]

const STYLE_CHIPS = [
  'blunt-technical',
  'directness · high',
  'advanced-technical',
  'short & punchy',
  'no emoji',
  'bullets for asks',
]

const TIERS = [
  { name: 'Executive / Client', note: 'Formal-ready, concessions gated', pct: 92 },
  { name: 'Peer', note: 'Direct, contractions allowed', pct: 78 },
  { name: 'Direct report', note: 'Warm, context-rich', pct: 64 },
  { name: 'External', note: 'Guardrailed, no internal detail', pct: 55 },
]

const AUDIENCE_MODES = [
  { name: '1-on-1 private', icon: Mail, note: 'Default. Full stylistic range.' },
  { name: 'Group CC', icon: Users, note: 'Neutralises in-jokes, trims candour.' },
  { name: 'Broadcast BCC', icon: Radio, note: 'Adds salutation, strips personal detail.' },
]

function ProviderCard({
  provider,
}: {
  provider: (typeof PROVIDERS)[number]
}) {
  const Icon = provider.icon
  return (
    <div className="group flex flex-col rounded-[20px] border border-hairline bg-elevated/50 p-5 transition-all duration-300 ease-proteus hover:border-hairline-strong hover:bg-elevated">
      <div className="mb-3 flex items-center justify-between">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-hairline bg-white/[0.04]">
          <Icon className="h-5 w-5 text-accent" strokeWidth={1.5} />
        </span>
        <Badge tone="neutral">{provider.method}</Badge>
      </div>
      <h4 className="font-display text-lg text-fg">{provider.name}</h4>
      <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-fg-muted">{provider.detail}</p>
      <Button variant="secondary" size="sm" className="mt-4 w-full" leftIcon={<Plug className="h-3.5 w-3.5" />}>
        Connect
      </Button>
    </div>
  )
}

export function FolderTabs() {
  const [active, setActive] = useState<TabId>('connect')
  const [rules, setRules] = useState({
    firstRecipientGate: true,
    blockCommitments: true,
    bccGuard: true,
    styleLearning: false,
  })

  const seed = useMutation({
    mutationFn: api.demoSeed,
  })
  const build = useMutation({
    mutationFn: () => api.buildProfile(false),
  })

  return (
    <section id="product" className="relative mx-auto max-w-7xl px-6 py-24 lg:px-10 lg:py-32">
      <div className="mb-14 max-w-2xl">
        <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.24em] text-accent">
          Onboarding
        </p>
        <h2 className="font-display text-4xl font-light leading-tight tracking-tight text-fg text-balance sm:text-5xl">
          Three steps to a <span className="italic text-accent">voice-faithful</span> draft.
        </h2>
        <p className="mt-5 text-[1.0625rem] leading-relaxed text-fg-muted">
          Point Proteus at your Sent mail, let it profile your stylometry, then set the
          audience rules it must never break.
        </p>
      </div>

      {/* Folder-style tabs */}
      <div
        role="tablist"
        aria-label="Onboarding steps"
        className="relative z-10 ml-3 flex flex-wrap items-end gap-1.5"
      >
        {TABS.map((tab) => {
          const isActive = tab.id === active
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              onClick={() => setActive(tab.id)}
              style={{ transform: `rotate(${tab.rotate}deg)` }}
              className={cn(
                'group relative -mb-px rounded-t-[16px] border border-b-0 px-5 py-3 transition-all duration-300 ease-proteus',
                'font-mono text-[12px] uppercase tracking-[0.18em]',
                isActive
                  ? 'z-20 border-hairline bg-surface text-fg'
                  : 'z-10 translate-y-[3px] border-hairline bg-elevated/45 text-fg-faint hover:bg-elevated hover:text-fg-muted',
              )}
            >
              <span className={cn('mr-2', isActive ? 'text-accent' : 'text-fg-faint/70')}>
                {tab.index}.
              </span>
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Panel */}
      <div className="relative rounded-card rounded-tl-none border border-hairline bg-surface p-6 sm:p-9">
        {/* ── 01 Connect ─────────────────────────────────────────── */}
        {active === 'connect' ? (
          <div role="tabpanel" id="panel-connect" aria-labelledby="tab-connect" className="animate-fade-up">
            <div className="grid gap-4 sm:grid-cols-3">
              {PROVIDERS.map((p) => (
                <ProviderCard key={p.id} provider={p} />
              ))}
            </div>

            <div className="mt-7 flex flex-col gap-4 rounded-[20px] border border-hairline bg-elevated/40 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <Lock className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <p className="max-w-xl text-[13px] leading-relaxed text-fg-muted">
                  Extraction runs locally and writes to{' '}
                  <code className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[12px] text-fg">
                    local_user_data/
                  </code>
                  . Raw bodies are cleaned of reply history before profiling — passwords are
                  never persisted.
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => seed.mutate()}
                  disabled={seed.isPending}
                  leftIcon={<Database className="h-3.5 w-3.5" />}
                >
                  {seed.isPending ? 'Seeding…' : 'Load demo corpus'}
                </Button>
                <Button
                  size="sm"
                  onClick={() => build.mutate()}
                  disabled={build.isPending}
                  leftIcon={<Fingerprint className="h-3.5 w-3.5" />}
                >
                  {build.isPending ? 'Profiling…' : 'Build profile'}
                </Button>
              </div>
            </div>

            {seed.data ? (
              <p className="mt-3 inline-flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.14em] text-accent">
                <Check className="h-3.5 w-3.5" />
                {seed.data.clean_emails_retained} clean emails retained from {seed.data.extracted_emails}
              </p>
            ) : null}
            {seed.isError ? (
              <p className="mt-3 inline-flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.14em] text-[#fbbf24]">
                <AlertTriangle className="h-3.5 w-3.5" />
                Backend offline — start it on 127.0.0.1:8000 to run live extraction.
              </p>
            ) : null}
          </div>
        ) : null}

        {/* ── 02 Voice & Stylometry ──────────────────────────────── */}
        {active === 'voice' ? (
          <div role="tabpanel" id="panel-voice" aria-labelledby="tab-voice" className="animate-fade-up">
            <div className="grid gap-8 lg:grid-cols-12">
              <div className="lg:col-span-7">
                <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  Deterministic metrics · all 412 emails
                </p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {METRICS.map((m) => (
                    <div
                      key={m.label}
                      className="rounded-[18px] border border-hairline bg-elevated/40 p-4 transition-colors duration-300 ease-proteus hover:border-hairline-strong"
                    >
                      <p className="font-display text-3xl leading-none text-fg">{m.value}</p>
                      <p className="mt-2 font-mono text-[12px] uppercase tracking-[0.14em] text-fg-faint">
                        {m.unit}
                      </p>
                      <p className="mt-1 text-[12px] text-fg-muted">{m.label}</p>
                    </div>
                  ))}
                </div>

                <p className="mb-3 mt-8 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  LLM style card · Qwen3:8B
                </p>
                <div className="flex flex-wrap gap-2">
                  {STYLE_CHIPS.map((chip) => (
                    <Badge key={chip} tone="accent" size="md">
                      {chip}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="lg:col-span-5">
                <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  Top greetings
                </p>
                <div className="space-y-3">
                  {GREETINGS.map((g) => (
                    <div key={g.pattern}>
                      <div className="mb-1.5 flex items-baseline justify-between">
                        <span className="font-mono text-[12px] text-fg">{g.pattern}</span>
                        <span className="font-mono text-[12px] text-fg-faint">{g.pct}%</span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                        <div
                          className="h-full rounded-full bg-accent transition-all duration-300 ease-proteus"
                          style={{ width: `${g.pct}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-6 rounded-[18px] border border-accent/25 bg-accent/[0.06] p-5">
                  <Quote className="mb-3 h-4 w-4 text-accent" />
                  <p className="font-mono text-[12px] uppercase tracking-[0.16em] text-fg-faint">
                    Exact sign-off
                  </p>
                  <p className="mt-2 whitespace-pre-line font-display text-xl italic leading-snug text-fg">
                    {'Best,\nMaya'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* ── 03 Audience & Safety ───────────────────────────────── */}
        {active === 'safety' ? (
          <div role="tabpanel" id="panel-safety" aria-labelledby="tab-safety" className="animate-fade-up">
            <div className="grid gap-8 lg:grid-cols-12">
              <div className="lg:col-span-5">
                <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  Relationship tiers
                </p>
                <div className="space-y-3">
                  {TIERS.map((t) => (
                    <div
                      key={t.name}
                      className="flex items-center gap-4 rounded-[18px] border border-hairline bg-elevated/40 p-4"
                    >
                      <div className="relative h-9 w-9 shrink-0">
                        <svg viewBox="0 0 36 36" className="h-9 w-9 -rotate-90">
                          <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
                          <circle
                            cx="18"
                            cy="18"
                            r="15"
                            fill="none"
                            stroke="#D4F268"
                            strokeWidth="3"
                            strokeLinecap="round"
                            strokeDasharray={`${(t.pct / 100) * 94.2} 94.2`}
                          />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center font-mono text-[12px] text-fg-muted">
                          {t.pct}
                        </span>
                      </div>
                      <div>
                        <p className="text-[13px] font-medium text-fg">{t.name}</p>
                        <p className="text-[12px] text-fg-faint">{t.note}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="lg:col-span-4">
                <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  Audience modes
                </p>
                <div className="space-y-3">
                  {AUDIENCE_MODES.map((m) => {
                    const Icon = m.icon
                    return (
                      <div
                        key={m.name}
                        className="flex items-start gap-3 rounded-[18px] border border-hairline bg-elevated/40 p-4"
                      >
                        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-accent" strokeWidth={1.6} />
                        <div>
                          <p className="text-[13px] font-medium text-fg">{m.name}</p>
                          <p className="text-[12px] leading-relaxed text-fg-faint">{m.note}</p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="lg:col-span-3">
                <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.2em] text-fg-faint">
                  Hard safety rules
                </p>
                <div className="space-y-4 rounded-[18px] border border-hairline bg-elevated/40 p-5">
                  <Toggle
                    id="rule-gate"
                    checked={rules.firstRecipientGate}
                    onChange={(v) => setRules((r) => ({ ...r, firstRecipientGate: v }))}
                    label="First-recipient gate"
                    hint="Always review new contacts"
                  />
                  <Toggle
                    id="rule-commit"
                    checked={rules.blockCommitments}
                    onChange={(v) => setRules((r) => ({ ...r, blockCommitments: v }))}
                    label="Block commitments"
                    hint="No auto-send on price / legal"
                  />
                  <Toggle
                    id="rule-bcc"
                    checked={rules.bccGuard}
                    onChange={(v) => setRules((r) => ({ ...r, bccGuard: v }))}
                    label="BCC broadcast guard"
                    hint="Flag >2 blind recipients"
                  />
                  <Toggle
                    id="rule-learn"
                    checked={rules.styleLearning}
                    onChange={(v) => setRules((r) => ({ ...r, styleLearning: v }))}
                    label="Auto-learn from edits"
                    hint="Extract rules from approvals"
                  />
                  <div className="flex items-start gap-2 border-t border-hairline pt-4">
                    <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                    <p className="text-[12px] leading-relaxed text-fg-faint">
                      Rules are enforced server-side, not just in the UI.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default FolderTabs
