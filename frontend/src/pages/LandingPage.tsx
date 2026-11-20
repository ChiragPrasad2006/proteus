import { useEffect, useState } from 'react'
import { Check, ShieldCheck } from 'lucide-react'
import { Hero } from '@/components/landing/Hero'
import { Navbar } from '@/components/layout/Navbar'
import { Button } from '@/components/ui/Button'

const TIERS = [
  {
    numeral: 'I',
    title: 'Ingest',
    art: 'waves',
    artAlt: 'Waves rising from the sea in the Proteus engraving — representing ingestion of your email corpus',
    copy: 'Gmail, Outlook, IMAP, .mbox, and .eml. Strict per-account isolation with deterministic stylometry: greeting, sign-off, sentence length, tone, and vocabulary fingerprint.',
  },
  {
    numeral: 'II',
    title: 'Remember',
    art: 'tree',
    artAlt: 'Proteus holding a tree — representing deep memory and time-decayed recall',
    copy: 'Time-decayed RAG on LanceDB with a 90-day half-life. Every example stays audience-aware, from private one-to-one mail to group CC and broadcast BCC.',
  },
  {
    numeral: 'III',
    title: 'Think',
    art: 'lion',
    artAlt: "Lion's head held by Proteus — representing Fast Drafting mode",
    copy: 'One local Qwen3:8B model, two working modes: the lion drafts quickly (think=false, sub-second); the serpent reasons deeply (think=true). Your corpus and contacts remain on disk.',
  },
  {
    numeral: 'IV',
    title: 'Act',
    art: 'flame',
    artAlt: 'Flame held by Proteus — representing the action of drafting and sending email',
    copy: 'Say "Email Manu, CC Jatin." Proteus resolves, drafts, and applies the first-recipient safety gate. Approved edits become permanent style rules.',
  },
]

const DEMO_EMAILS = [
  { greeting: 'Hi Manu,', signoff: 'Best,', words: 14.2, tone: 'Direct' },
  { greeting: 'Hello Jatin,', signoff: 'Thanks,', words: 13.8, tone: 'Warm' },
  { greeting: 'Hi Chiranth,', signoff: 'Best,', words: 14.7, tone: 'Concise' },
]

function useReveal() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll('.reveal-section'))
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        }),
      { threshold: 0.14 },
    )
    nodes.forEach((node) => observer.observe(node))
    return () => observer.disconnect()
  }, [])
}

export function LandingPage() {
  const [oauthError, setOauthError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [streamed, setStreamed] = useState(0)
  useReveal()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('auth') === 'error') {
      setOauthError(params.get('reason') || 'Google sign-in could not be completed.')
      window.history.replaceState({}, '', '/')
    }
  }, [])

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setStreamed(DEMO_EMAILS.length)
      return
    }
    const timer = window.setInterval(
      () => setStreamed((value) => Math.min(DEMO_EMAILS.length, value + 1)),
      720,
    )
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="min-h-screen bg-cobalt text-paper">
      <Navbar />

      {oauthError ? (
        <div
          role="status"
          className="mx-auto mt-20 max-w-7xl border border-ember/60 bg-ember/10 px-4 py-3 text-sm text-paper"
        >
          {oauthError}
        </div>
      ) : null}

      <main>
        {/* ── 1. HERO ── */}
        <Hero />

        {/* ── 2. MARQUEE STRIP ── */}
        <div className="overflow-hidden border-y border-hairline py-4 font-mono text-[11px] uppercase tracking-[0.22em] text-paper-label">
          <div className="flex w-max animate-marquee motion-reduce:animate-none">
            <span className="px-8">
              Local-first&nbsp;/&nbsp;No telemetry&nbsp;/&nbsp;Multi-account&nbsp;/&nbsp;Your
              voice&nbsp;/&nbsp;MIT licensed&nbsp;/&nbsp;
            </span>
            <span className="px-8" aria-hidden="true">
              Local-first&nbsp;/&nbsp;No telemetry&nbsp;/&nbsp;Multi-account&nbsp;/&nbsp;Your
              voice&nbsp;/&nbsp;MIT licensed&nbsp;/&nbsp;
            </span>
          </div>
        </div>

        {/* ── 3. FOUR TIERS ── */}
        <section id="how-it-learns" className="mx-auto max-w-[1440px] px-5 py-24 md:px-10 md:py-36">
          <div className="reveal-section mb-20 flex flex-col justify-between gap-8 md:flex-row md:items-end">
            <div>
              <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label">
                Four tiers of becoming
              </p>
              <h2 className="max-w-[10ch] font-display text-6xl font-light leading-[0.9] tracking-[-0.04em] md:text-8xl">
                From your mail to your voice.
              </h2>
            </div>
            <p className="max-w-md text-paper-muted">
              One continuous local system. No cloud brain, no style marketplace, no telemetry.
            </p>
          </div>

          <div className="border-t border-hairline">
            {TIERS.map((tier, index) => (
              <article
                key={tier.numeral}
                className="reveal-section group grid min-h-[34rem] items-center gap-10 border-b border-hairline py-14 lg:grid-cols-2 lg:gap-20 lg:py-20"
              >
                {/* Art */}
                <div className={index % 2 ? 'lg:order-2' : ''}>
                  <div
                    className={`relative aspect-square max-h-[34rem] overflow-hidden ${index % 2 === 0 ? 'bg-cobalt-deep' : 'bg-cobalt'}`}
                  >
                    <img
                      src={`/art/proteus-${tier.art}.webp`}
                      alt={tier.artAlt}
                      loading="lazy"
                      className="engraving-multiply h-full w-full object-contain transition-transform duration-700 ease-proteus group-hover:scale-[1.03]"
                    />
                    <span className="absolute bottom-3 left-3 font-mono text-[10px] uppercase tracking-[0.18em] text-paper-label">
                      {tier.numeral}&nbsp;/&nbsp;{tier.title}
                    </span>
                  </div>
                </div>

                {/* Copy */}
                <div className={index % 2 ? 'lg:order-1' : ''}>
                  <span className="font-display text-8xl font-light leading-none text-paper/25">
                    {tier.numeral}
                  </span>
                  <h3 className="mt-2 font-display text-6xl font-light tracking-[-0.04em] transition-all duration-500 md:text-8xl">
                    {tier.title}
                    <span className="ml-3 inline-block h-0.5 w-0 bg-paper transition-all duration-500 ease-proteus group-hover:w-10" />
                  </h3>
                  <p className="mt-6 max-w-xl text-lg leading-relaxed text-paper-muted">
                    {tier.copy}
                  </p>
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* ── 4. LIVE STYLE-PROFILE DEMO ── */}
        <section className="bg-cobalt-deep py-24 md:py-32">
          <div className="reveal-section mx-auto grid max-w-[1440px] gap-14 px-5 md:px-10 lg:grid-cols-[0.8fr_1.2fr]">
            <div>
              <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label">
                Live style profile
              </p>
              <h2 className="font-display text-5xl font-light leading-[0.95] tracking-[-0.04em] md:text-7xl">
                A fingerprint, not a costume.
              </h2>
              <p className="mt-6 max-w-md leading-relaxed text-paper-muted">
                Proteus measures deterministic features before asking a model to imitate them.
              </p>
            </div>

            <div className="bg-paper p-7 text-ink shadow-none md:p-10" style={{ borderRadius: '2px' }}>
              <div className="flex items-center justify-between border-b border-ink/15 pb-5">
                <span className="font-mono text-[11px] uppercase tracking-[0.16em]">
                  Stylometry fingerprint
                </span>
                <span
                  className="relative flex h-2 w-2"
                  aria-label="Live"
                >
                  <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-pill bg-foam" />
                  <span className="relative inline-flex h-2 w-2 rounded-pill bg-foam" />
                </span>
              </div>

              <div className="grid gap-7 py-7 sm:grid-cols-2">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">
                    Top greeting
                  </p>
                  <p className="mt-2 font-display text-3xl">Hi {'{first}'},</p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">
                    Exact sign-off
                  </p>
                  <p className="mt-2 font-display text-3xl">Best,</p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">
                    Avg sentence
                  </p>
                  <p className="mt-2 font-display text-3xl">14.2 words</p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">
                    Tone
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {['Direct', 'Warm', 'Concise'].map((tone) => (
                      <span
                        key={tone}
                        className="rounded-pill border border-ink/20 px-3 py-1 font-mono text-[10px] uppercase tracking-wider"
                      >
                        {tone}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="border-t border-ink/15 pt-5">
                {DEMO_EMAILS.slice(0, streamed).map((email) => (
                  <p
                    key={email.greeting}
                    className="flex justify-between border-b border-ink/10 py-2 font-mono text-[11px] text-ink/70"
                  >
                    <span>
                      {email.greeting} … {email.signoff}
                    </span>
                    <span>
                      {email.words}w · {email.tone}
                    </span>
                  </p>
                ))}
                {streamed === 0 ? (
                  <p className="py-2 font-mono text-[11px] text-ink/50">
                    Listening to local corpus…
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        </section>

        {/* ── 5. SAFETY GATE ── */}
        <section id="safety" className="mx-auto max-w-[1440px] px-5 py-24 md:px-10 md:py-36">
          <div className="reveal-section grid gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-center">
            <div>
              <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label">
                The safety gate
              </p>
              <h2 className="max-w-[10ch] font-display text-6xl font-light leading-[0.92] tracking-[-0.04em] md:text-8xl">
                Never sends to a stranger without asking.
              </h2>
              <p className="mt-6 max-w-md text-paper-muted">
                Every first recipient pauses the send. Proteus can draft, learn, and prepare — but
                you own the final threshold.
              </p>
            </div>

            {/* Paper email mockup */}
            <div className="relative bg-paper p-7 text-ink md:p-10" style={{ borderRadius: '2px' }}>
              {!sent ? (
                <span
                  className="-rotate-6 absolute right-7 top-7 border-2 border-ember-ink px-3 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-ember-ink"
                  aria-label="Pending review"
                >
                  Pending review
                </span>
              ) : null}

              <div className="border-b border-ink/15 pb-5">
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">To</p>
                <p className="mt-1">manu@example.com</p>
                <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.16em] text-ink/60">
                  Subject
                </p>
                <p className="mt-1 font-display text-2xl">Following up on the launch plan</p>
              </div>

              <div className="space-y-3 py-7 font-display text-lg leading-relaxed">
                <p>Hi Manu,</p>
                <p>
                  I've pulled the latest milestones into the plan we discussed. The revised timing
                  should keep the handoff comfortable for the team.
                </p>
                <p>Best,</p>
              </div>

              <div className="flex flex-wrap gap-3 border-t border-ink/15 pt-6">
                <Button
                  onClick={() => setSent(true)}
                  leftIcon={
                    sent ? (
                      <Check className="h-4 w-4 text-foam" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )
                  }
                  className={sent ? 'bg-foam/20 text-ink border border-foam/50' : ''}
                >
                  {sent ? 'Sent' : 'Approve & send'}
                </Button>
                <Button
                  variant="outline"
                  className="border-ink/20 text-ink hover:border-ink/50 hover:bg-ink/5"
                >
                  Edit first
                </Button>
              </div>
            </div>
          </div>
        </section>

        {/* ── 6. PRIVACY BAND ── */}
        <section id="privacy" className="relative overflow-hidden bg-ink py-24 text-paper md:py-36">
          <img
            src="/art/proteus-alpha.png"
            alt=""
            aria-hidden="true"
            loading="lazy"
            className="engraving-invert pointer-events-none absolute -right-28 top-0 h-full max-h-[54rem] opacity-[0.08]"
          />
          <div className="reveal-section relative mx-auto max-w-[1440px] px-5 md:px-10">
            <p className="mb-5 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label">
              Privacy is the architecture
            </p>
            <h2 className="max-w-[12ch] font-display text-7xl font-light leading-[0.88] tracking-[-0.045em] md:text-[9rem]">
              100% local.{' '}
              <span className="italic">Zero</span>{' '}
              telemetry.
            </h2>
            <div className="mt-14 flex flex-wrap gap-x-8 gap-y-4 font-mono text-[11px] uppercase tracking-[0.18em] text-paper-label">
              {['SQLite', 'LanceDB', 'Ollama', 'Qwen3:8B', 'MIT'].map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>
        </section>
      </main>

      {/* ── 7. FOOTER ── */}
      <footer className="overflow-hidden border-t border-hairline bg-cobalt-deep">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-10 px-5 py-16 md:flex-row md:items-end md:justify-between md:px-10">
          <div>
            <p className="font-display text-[clamp(6rem,20vw,17rem)] leading-[0.65] tracking-[-0.07em] text-paper">
              proteus
            </p>
          </div>
          <div className="text-right">
            <div className="flex justify-end gap-5 font-mono text-[11px] uppercase tracking-[0.15em]">
              <a
                href="https://github.com/ChiragPrasad2006/proteus"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-foam focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foam"
              >
                GitHub
              </a>
              <a
                href="https://github.com/ChiragPrasad2006/proteus/blob/main/LICENSE"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-foam focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foam"
              >
                License
              </a>
            </div>
            <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.15em] text-paper-label">
              Built locally. Becomes you.
            </p>
          </div>
        </div>
      </footer>

    </div>
  )
}

export default LandingPage
