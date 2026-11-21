import { Aperture, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * The hero's right-hand generative frame: a rounded-top-arch plate with a
 * layered radial "aperture" mark, a mono catalog label and a sticky-note badge.
 */
export function GenerativeFrame({ className }: { className?: string }) {
  return (
    <div className={cn('relative', className)}>
      <div className="arch paper-grid relative aspect-[4/5] w-full overflow-hidden border border-hairline bg-surface">
        {/* Layered aperture bloom */}
        <div className="absolute inset-0 opacity-90">
          <div className="absolute left-1/2 top-[38%] h-[62%] w-[62%] -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_50%_50%,rgba(212,242,104,0.42),rgba(212,242,104,0.06)_55%,transparent_72%)] blur-[2px]" />
          <div className="absolute left-1/2 top-[46%] h-[42%] w-[42%] -translate-x-1/2 rounded-full border border-accent/25" />
          <div className="absolute left-1/2 top-[46%] h-[58%] w-[58%] -translate-x-1/2 rounded-full border border-white/5" />
          <div className="absolute left-1/2 top-[52%] h-px w-[74%] -translate-x-1/2 bg-gradient-to-r from-transparent via-accent/40 to-transparent" />
        </div>

        {/* Aperture mark */}
        <div className="absolute left-1/2 top-[46%] -translate-x-1/2 -translate-y-1/2">
          <div className="relative flex h-28 w-28 items-center justify-center">
            <span className="absolute inset-0 animate-pulse-ring rounded-full border border-accent/40" />
            <Aperture className="h-14 w-14 text-accent" strokeWidth={1.1} />
          </div>
        </div>

        {/* Ghosted wordmark beneath the aperture */}
        <div className="absolute inset-x-0 bottom-0 px-7 pb-7">
          <p className="font-display text-[2.6rem] leading-none tracking-tight text-fg/90">
            your <span className="italic text-accent">voice</span>,
          </p>
          <p className="font-display text-[2.6rem] leading-none tracking-tight text-fg/40">
            reconstructed.
          </p>
        </div>

        {/* Catalog label */}
        <div className="absolute left-6 top-6 flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.24em] text-fg-faint">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Catalog · 04 / Stylometric Aperture
        </div>

        <div className="absolute right-6 top-6 font-mono text-[12px] uppercase tracking-[0.24em] text-fg-faint">
          v2.5 · 3B
        </div>
      </div>

      {/* Sticky-note badge */}
      <div className="absolute -bottom-6 -left-6 w-[15.5rem] rotate-[-4deg] rounded-[18px] border border-accent/25 bg-accent p-4 text-ink transition-transform duration-300 ease-proteus hover:rotate-[-2deg]">
        <div className="mb-2 flex items-center gap-1.5 font-mono text-[12px] uppercase tracking-[0.2em] text-ink/70">
          <Sparkles className="h-3 w-3" /> Sticky note
        </div>
        <p className="font-display text-[15px] leading-snug text-ink">
          It writes like you because it read{' '}
          <span className="italic">412 of your sent emails</span> first.
        </p>
      </div>
    </div>
  )
}

export default GenerativeFrame
