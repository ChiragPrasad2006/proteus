import { ArrowRight, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'

/** Pin-board section: a rotated sticky note inviting the user into /workspace. */
export function StickyNoteCTA() {
  return (
    <section id="safety" className="relative mx-auto max-w-7xl px-6 pb-28 lg:px-10 lg:pb-36">
      <div className="relative">
        {/* Pin-board backing */}
        <div className="paper-grid flex min-h-[22rem] items-center justify-center rounded-card border border-hairline bg-elevated/30 px-6 py-16">
          {/* Push-pin */}
          <span
            aria-hidden
            className="absolute left-1/2 top-6 h-4 w-4 -translate-x-1/2 rounded-full bg-accent shadow-[0_6px_14px_-2px_rgba(212,242,104,0.7)]"
          />

          <div className="relative w-full max-w-xl rotate-[-1.5deg] rounded-[22px] bg-accent p-8 text-ink shadow-[0_40px_80px_-40px_rgba(0,0,0,0.95)] transition-transform duration-300 ease-proteus hover:rotate-[-0.5deg] sm:p-10">
            <div className="mb-4 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-ink/60">
              <Sparkles className="h-3.5 w-3.5" /> Ready when you are
            </div>

            <h2 className="font-display text-3xl font-light leading-[1.1] tracking-tight text-ink text-balance sm:text-4xl">
              Your Sent folder is already the training set.
              <span className="block italic">Let’s put it to work.</span>
            </h2>

            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-ink/70">
              Open the workspace, brief Proteus on who you’re writing to, and approve the
              first-recipient review before anything sends.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link to="/workspace">
                <Button
                  size="lg"
                  className="w-full bg-ink text-fg shadow-none hover:bg-[#241f1c] sm:w-auto"
                  rightIcon={<ArrowRight className="h-4 w-4" />}
                >
                  Launch the workspace
                </Button>
              </Link>
              <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink/60">
                No card · runs offline
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default StickyNoteCTA
