import { useState, useEffect } from 'react'
import { ArrowRight, Copy, Check } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmailSignInModal } from '@/components/auth/EmailSignInModal'
import { Button } from '@/components/ui/Button'
import { startGoogleSignIn } from '@/lib/googleAuth'
import { cn } from '@/lib/utils'

const INSTALL_CMD = '.\\Proteus.exe'

/** Headline lines for the staggered reveal animation. */
const HEADLINE_LINES = [
  { text: 'The agent that', italic: false },
  { text: 'becomes you.', italic: true },
]

function HeadlineWord({ text, italic, delay }: { text: string; italic: boolean; delay: number }) {
  const [visible, setVisible] = useState(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return true
    }
    return false
  })

  useEffect(() => {
    if (visible) return
    const id = setTimeout(() => setVisible(true), delay)
    return () => clearTimeout(id)
  }, [delay, visible])

  return (
    <span
      className={cn(
        'block leading-[0.95] tracking-[-0.03em] transition-all duration-700',
        italic ? 'italic' : '',
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6',
      )}
      style={{
        transitionTimingFunction: 'cubic-bezier(0.16,1,0.3,1)',
        transitionDelay: visible ? '0ms' : `${delay}ms`,
      }}
    >
      {text}
    </span>
  )
}

function CopyInstallButton() {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard
      .writeText(INSTALL_CMD)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1800)
      })
      .catch(() => {
        /* ignore */
      })
  }

  return (
    <div className="mt-8 inline-flex items-center gap-3 rounded-pill border border-hairline bg-cobalt-deep px-4 py-2.5">
      <code className="font-mono text-[13px] text-paper-muted">{INSTALL_CMD}</code>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? 'Copied' : 'Copy install command'}
        className="inline-flex h-6 w-6 items-center justify-center rounded-pill border border-hairline text-paper-label transition-colors hover:border-foam/60 hover:text-foam focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foam"
      >
        {copied ? <Check className="h-3 w-3 text-foam" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  )
}

/**
 * Full-viewport cobalt hero section.
 * Places the Proteus engraving behind the content matching the exact geometry
 * from proteus.html without two-column grid isolation or white boxes.
 */
export function Hero() {
  const [setupOpen, setSetupOpen] = useState(false)

  const beginGoogleLogin = async () => {
    try {
      if (!(await startGoogleSignIn())) setSetupOpen(true)
    } catch {
      setSetupOpen(true)
    }
  }

  return (
    <section className="relative flex min-h-svh overflow-hidden">
      {/* Proteus engraving artwork placed behind hero content with exact geometry from proteus.html */}
      <div
        className={cn(
          'pointer-events-none absolute z-[1]',
          'bottom-0 right-[-6%] aspect-square h-[min(112vh,1250px)]',
          'max-md:right-[-28%] max-md:h-[75vh] max-md:opacity-40',
        )}
        style={{
          position: 'absolute',
          right: '-6%',
          bottom: 0,
          height: 'min(112vh, 1250px)',
          aspectRatio: '1',
          zIndex: 1,
          pointerEvents: 'none',
        }}
        aria-hidden="true"
      >
        <img
          src="/art/proteus-alpha.png"
          alt=""
          className="h-full w-full object-contain object-right-bottom mix-blend-multiply motion-safe:animate-breathe motion-reduce:animate-none"
          fetchPriority="high"
        />
      </div>

      {/* Hero content wrapper (z-index: 2, kept in exact format and alignment) */}
      <div className="relative z-[2] mx-auto flex w-full max-w-[1440px] items-center px-5 pt-28 pb-16 md:px-10 lg:pt-32 lg:pb-24">
        <div className="max-w-2xl">
          {/* Mono eyebrow */}
          <p className="mb-8 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label motion-safe:animate-fade-in">
            Local-first · Runs on your machine
          </p>

          {/* Staggered headline */}
          <h1 className="font-display text-[clamp(3rem,8vw,7rem)] font-light text-paper">
            {HEADLINE_LINES.map((line, i) => (
              <HeadlineWord key={i} text={line.text} italic={line.italic} delay={120 + i * 180} />
            ))}
          </h1>

          {/* Subline */}
          <p
            className="mt-7 max-w-sm text-[1.0625rem] leading-relaxed text-paper-muted opacity-0 translate-y-4"
            style={{
              animation: 'fade-up 0.7s cubic-bezier(0.16,1,0.3,1) 580ms both',
            }}
          >
            Local-first email, written in your voice.{' '}
            <span className="text-paper">Nothing leaves your machine.</span>
          </p>

          {/* CTAs */}
          <div
            className="mt-10 flex flex-wrap items-center gap-4 opacity-0"
            style={{ animation: 'fade-up 0.7s cubic-bezier(0.16,1,0.3,1) 760ms both' }}
          >
            <Button
              size="lg"
              onClick={beginGoogleLogin}
              className="rounded-pill bg-paper px-7 font-medium text-ink hover:-translate-y-px hover:bg-white"
            >
                      Continue with Google
            </Button>
            <Link
              to="https://github.com/ChiragPrasad2006/proteus"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-12 items-center gap-2 rounded-pill border border-hairline px-6 font-mono text-[12px] uppercase tracking-[0.12em] text-paper-muted transition-colors hover:border-paper-label hover:text-paper focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foam"
            >
              Read the source <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {/* Install line */}
          <div
            className="opacity-0"
            style={{ animation: 'fade-up 0.7s cubic-bezier(0.16,1,0.3,1) 920ms both' }}
          >
            <CopyInstallButton />
          </div>
        </div>
      </div>

      <EmailSignInModal isOpen={setupOpen} onClose={() => setSetupOpen(false)} onSignedIn={() => { window.location.href = '/workspace' }} />
    </section>
  )
}

export default Hero
