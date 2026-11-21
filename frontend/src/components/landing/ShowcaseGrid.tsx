import {
  ArrowUpRight,
  CheckCheck,
  FileText,
  Fingerprint,
  Gauge,
  Layers,
  ShieldCheck,
  Sparkles,
  Users,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface ShowcaseCard {
  index: string
  title: string
  copy: string
  icon: typeof Layers
  art: ReactNode
  span?: boolean
}

function MiniDraft() {
  return (
    <div className="w-full space-y-1.5 rounded-xl border border-hairline bg-ink/60 p-3">
      {[92, 78, 84, 56].map((w, i) => (
        <div
          key={i}
          className={cn('h-1.5 rounded-full', i === 3 ? 'bg-accent/60' : 'bg-white/[0.09]')}
          style={{ width: `${w}%` }}
        />
      ))}
    </div>
  )
}

function MiniChips() {
  return (
    <div className="flex w-full flex-wrap gap-1.5">
      {['Hi {first},', 'Best,', 'no emoji', 'high directness'].map((c) => (
        <span
          key={c}
          className="rounded-full border border-accent/25 bg-accent/[0.08] px-2 py-1 font-mono text-[12px] text-accent"
        >
          {c}
        </span>
      ))}
    </div>
  )
}

function MiniContacts() {
  return (
    <div className="flex -space-x-2">
      {[
        ['DR', 'from-[#D4F268] to-[#7C9B2E]'],
        ['PN', 'from-[#8AB4F8] to-[#3B5BDB]'],
        ['+2', 'from-[#443f3b] to-[#292524]'],
      ].map(([label, hue]) => (
        <span
          key={label}
          className={cn(
            'inline-flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br font-mono text-[12px] font-semibold text-ink ring-2 ring-surface',
            hue,
          )}
        >
          {label}
        </span>
      ))}
    </div>
  )
}

function MiniMeter() {
  return (
    <div className="w-full space-y-2.5">
      {[
        ['Formality', 72],
        ['Directness', 88],
        ['Verbosity', 34],
      ].map(([label, pct]) => (
        <div key={label as string}>
          <div className="mb-1 flex justify-between font-mono text-[12px] uppercase tracking-wider text-fg-faint">
            <span>{label}</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.07]">
            <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function MiniGate() {
  return (
    <div className="w-full rounded-xl border border-[#92400e]/50 bg-[#f59e0b]/[0.07] p-3">
      <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-wider text-[#fbbf24]">
        <ShieldCheck className="h-3 w-3" /> Review required
      </div>
      <div className="h-1.5 w-4/5 rounded-full bg-white/[0.1]" />
      <div className="mt-1.5 h-1.5 w-3/5 rounded-full bg-white/[0.07]" />
    </div>
  )
}

function MiniRetrieval() {
  return (
    <div className="w-full space-y-1.5">
      {[1, 0.62, 0.41].map((o, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="h-1.5 flex-1 rounded-full bg-white/[0.09]" />
          <span className="font-mono text-[12px] text-accent" style={{ opacity: o }}>
            {o.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  )
}

const CARDS: ShowcaseCard[] = [
  {
    index: '01',
    title: 'Drafts that read like you wrote them',
    copy: 'Every draft is conditioned on your retrieved sent-email examples, not a generic assistant voice.',
    icon: Sparkles,
    art: <MiniDraft />,
  },
  {
    index: '02',
    title: 'Stylometry, measured not guessed',
    copy: 'Sentence length, exclamation and emoji rates, bullet usage — computed deterministically over your corpus.',
    icon: Gauge,
    art: <MiniMeter />,
  },
  {
    index: '03',
    title: 'Voice fingerprint, locally derived',
    copy: 'A global style card plus per-recipient rules, all produced by a local Qwen model. Zero egress.',
    icon: Fingerprint,
    art: <MiniChips />,
  },
  {
    index: '04',
    title: 'Contacts resolved from your history',
    copy: 'Proteus surfaces who it matched, their relationship tier and how confident it is before you send.',
    icon: Users,
    art: <MiniContacts />,
  },
  {
    index: '05',
    title: 'First-recipient gate, always on',
    copy: 'New contacts and commercial concessions pause for explicit approval — never a silent auto-send.',
    icon: ShieldCheck,
    art: <MiniGate />,
  },
  {
    index: '06',
    title: 'Few-shot retrieval with decay',
    copy: 'Semantically closest prior threads, re-ranked by recency so your voice tracks how it has changed.',
    icon: Layers,
    art: <MiniRetrieval />,
  },
]

const STATS = [
  { label: 'Emails profiled', value: '412' },
  { label: 'Recipients learned', value: '137' },
  { label: 'Voice match', value: '94%' },
  { label: 'Data egress', value: '0 B' },
]

export function ShowcaseGrid() {
  return (
    <section id="method" className="relative mx-auto max-w-7xl px-6 py-24 lg:px-10 lg:py-32">
      <div className="mb-14 flex flex-col justify-between gap-6 md:flex-row md:items-end">
        <div className="max-w-2xl">
          <p className="mb-4 font-mono text-[12px] uppercase tracking-[0.24em] text-accent">
            The method
          </p>
          <h2 className="font-display text-4xl font-light leading-tight tracking-tight text-fg text-balance sm:text-5xl">
            Built on retrieval, <span className="italic text-accent">not vibes</span>.
          </h2>
        </div>
        <p className="max-w-sm text-[15px] leading-relaxed text-fg-muted">
          Six mechanisms working together, each inspectable in the workspace — retrieved
          examples, confidence scores and guardrails are shown, not hidden.
        </p>
      </div>

      {/* 3:4 showcase grid */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {CARDS.map((card) => {
          const Icon = card.icon
          return (
            <article
              key={card.index}
              className={cn(
                'group relative flex aspect-[3/4] flex-col overflow-hidden rounded-card border border-hairline bg-surface p-6',
                'transition-all duration-300 ease-proteus hover:border-hairline-strong hover:bg-elevated/40',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[12px] tracking-[0.2em] text-fg-faint">
                  {card.index}
                </span>
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-hairline bg-white/[0.03] transition-colors duration-300 ease-proteus group-hover:border-accent/40">
                  <Icon className="h-4 w-4 text-accent" strokeWidth={1.5} />
                </span>
              </div>

              <div className="my-auto flex items-center justify-center py-6">{card.art}</div>

              <div className="mt-auto">
                <h3 className="font-display text-xl leading-snug text-fg">{card.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-fg-muted">{card.copy}</p>
              </div>

              <ArrowUpRight className="absolute right-5 top-5 h-4 w-4 translate-y-1 text-fg-faint opacity-0 transition-all duration-300 ease-proteus group-hover:translate-y-0 group-hover:opacity-100" />
            </article>
          )
        })}
      </div>

      {/* Stat band */}
      <div id="stylometry" className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-card border border-hairline bg-hairline md:grid-cols-4">
        {STATS.map((s) => (
          <div key={s.label} className="bg-surface px-6 py-7 text-center">
            <p className="font-display text-4xl leading-none text-accent">{s.value}</p>
            <p className="mt-2.5 font-mono text-[12px] uppercase tracking-[0.18em] text-fg-faint">
              {s.label}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-[12px] uppercase tracking-[0.14em] text-fg-faint">
        <span className="inline-flex items-center gap-2">
          <CheckCheck className="h-3.5 w-3.5 text-accent/70" /> Edits feed back as learned rules
        </span>
        <span className="inline-flex items-center gap-2">
          <FileText className="h-3.5 w-3.5 text-accent/70" /> Full audit trail per draft
        </span>
      </div>
    </section>
  )
}

export default ShowcaseGrid
