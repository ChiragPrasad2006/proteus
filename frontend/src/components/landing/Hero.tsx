import { ArrowRight, Lock, Mail, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { GenerativeFrame } from '@/components/effects/GenerativeFrame'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

function GoogleGlyph({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.06 12.25c0-.85-.08-1.67-.22-2.45H12v4.63h6.2a5.3 5.3 0 0 1-2.3 3.48v2.89h3.72c2.18-2 3.44-4.96 3.44-8.55Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.11 0 5.72-1.03 7.62-2.79l-3.72-2.89c-1.03.69-2.35 1.1-3.9 1.1-3 0-5.54-2.03-6.45-4.75H1.7v2.98A11.99 11.99 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.55 14.67a7.2 7.2 0 0 1 0-4.6V7.09H1.7a12 12 0 0 0 0 10.56l3.85-2.98Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.69 0 3.2.58 4.4 1.72l3.3-3.3C17.71 1.2 15.1 0 12 0A11.99 11.99 0 0 0 1.7 7.09l3.85 2.98C6.46 7.35 9 4.75 12 4.75Z"
      />
    </svg>
  )
}

/** Asymmetrical 5:7 hero — copy and sign-in on the left, art on the right. */
export function Hero() {
  return (
    <section className="relative overflow-hidden pt-36 pb-24 lg:pt-44 lg:pb-32">
      {/* Ambient bloom */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 right-[-10%] h-[46rem] w-[46rem] rounded-full bg-[radial-gradient(circle,rgba(212,242,104,0.12),transparent_62%)] blur-2xl"
      />

      <div className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-16 px-6 lg:grid-cols-12 lg:gap-10 lg:px-10">
        {/* Left — 5 columns */}
        <div className="lg:col-span-5">
          <div
            className={cn(
              'mb-7 inline-flex items-center gap-2 rounded-full border border-hairline bg-white/[0.03] px-3.5 py-1.5',
              'font-mono text-[10px] uppercase tracking-[0.2em] text-fg-muted',
            )}
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-accent" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
            </span>
            Local-first · Runs on your machine
          </div>

          <h1 className="font-display text-[2.75rem] font-light leading-[1.02] tracking-[-0.02em] text-fg text-balance sm:text-6xl lg:text-[4.2rem]">
            The email writer that already sounds like{' '}
            <span className="italic text-accent">you</span>.
          </h1>

          <p className="mt-7 max-w-lg text-[1.0625rem] leading-relaxed text-fg-muted text-pretty">
            Proteus reads your Sent folder, learns your stylometry — greetings, cadence,
            sign-offs, the way you concede a point — then drafts new mail in that exact
            voice. Nothing leaves your machine.
          </p>

          <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center">
            <button
              type="button"
              className={cn(
                'inline-flex h-12 items-center justify-center gap-3 rounded-full bg-fg px-6',
                'text-[15px] font-medium text-ink transition-all duration-300 ease-proteus',
                'hover:bg-white active:scale-[0.98]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-ink',
              )}
            >
              <GoogleGlyph className="h-5 w-5" />
              Continue with Google
            </button>
            <Link to="/workspace">
              <Button
                variant="outline"
                size="lg"
                rightIcon={<ArrowRight className="h-4 w-4" />}
                className="w-full sm:w-auto"
              >
                Skip to workspace
              </Button>
            </Link>
          </div>

          <ul className="mt-9 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-faint">
            <li className="inline-flex items-center gap-2">
              <Lock className="h-3.5 w-3.5 text-accent/70" /> Zero-egress
            </li>
            <li className="inline-flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-accent/70" /> First-recipient gate
            </li>
            <li className="inline-flex items-center gap-2">
              <Mail className="h-3.5 w-3.5 text-accent/70" /> Gmail · Outlook · IMAP
            </li>
          </ul>
        </div>

        {/* Right — 7 columns */}
        <div className="lg:col-span-7">
          <GenerativeFrame className="mx-auto max-w-[34rem] lg:ml-auto lg:mr-0 lg:max-w-[38rem]" />
        </div>
      </div>
    </section>
  )
}

export default Hero
