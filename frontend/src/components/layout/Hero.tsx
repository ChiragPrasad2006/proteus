import { ArrowRight, Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ConnectGmailModal } from '@/components/auth/ConnectGmailModal'
import { Button } from '@/components/ui/Button'
import { startGoogleSignIn } from '@/lib/googleAuth'

export function Hero() {
  const [setupOpen, setSetupOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const artRef = useRef<HTMLDivElement>(null)
  const beginGoogleLogin = async () => {
    try { if (!await startGoogleSignIn()) setSetupOpen(true) } catch { setSetupOpen(true) }
  }
  useEffect(() => {
    const onScroll = () => {
      const node = artRef.current
      if (!node || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      node.style.setProperty('--hero-parallax', `${Math.min(70, window.scrollY * 0.08)}px`)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  const copyInstall = async () => {
    await navigator.clipboard.writeText('.\Proteus.exe')
    setCopied(true); window.setTimeout(() => setCopied(false), 1600)
  }
  return (
    <section className="relative min-h-screen overflow-hidden pt-28 md:pt-32">
      <div className="mx-auto grid min-h-[calc(100svh-7rem)] max-w-[1440px] grid-cols-1 items-center gap-8 px-5 md:px-10 lg:grid-cols-[0.82fr_1.18fr]">
        <div className="relative z-10 pb-10 lg:pb-24">
          <p className="mb-7 font-mono text-[11px] uppercase tracking-[0.2em] text-paper-label">Local-first · Your voice, learned</p>
          <h1 className="max-w-[10ch] font-display text-[clamp(4rem,10vw,9.5rem)] font-light leading-[0.86] tracking-[-0.05em] text-paper">
            <span className="block animate-fade-up">The agent</span>
            <span className="block animate-fade-up [animation-delay:100ms]">that <em className="font-normal">becomes</em></span>
            <span className="block animate-fade-up [animation-delay:200ms]">you.</span>
          </h1>
          <p className="mt-8 max-w-xl text-lg leading-relaxed text-paper-muted sm:text-xl">Local-first email, written in your voice. Nothing leaves your machine.</p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row">
            <Button size="lg" onClick={beginGoogleLogin} rightIcon={<ArrowRight className="h-4 w-4" />}>Get started</Button>
            <a href="https://github.com/ChiragPrasad2006/proteus" target="_blank" rel="noreferrer"><Button size="lg" variant="outline" className="w-full">Read the source</Button></a>
          </div>
          <button type="button" onClick={copyInstall} className="mt-8 inline-flex items-center gap-3 rounded-pill border border-hairline px-4 py-2 font-mono text-[12px] text-paper-label transition-colors hover:border-paper-label">
            <span>.\Proteus.exe</span>{copied ? <Check className="h-3.5 w-3.5 text-foam" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
        <div ref={artRef} className="relative -mx-8 mt-4 h-[62svh] min-h-[34rem] overflow-hidden lg:-mx-24 lg:h-[calc(100svh-4rem)] lg:min-h-[42rem]">
          <picture className="absolute inset-0">
            <source media="(max-width: 640px)" srcSet="/art/proteus-full-800.webp" />
            <source srcSet="/art/proteus-full@2x.webp" />
            <img src="/art/proteus-full.webp" alt="Proteus, the shape-shifting sea god, rising from engraved waves with a flame, lion, serpent, and tree" className="engraving-multiply absolute inset-0 h-full w-full object-contain object-center opacity-0 [animation:fade-in_1.2s_0.3s_forwards]" fetchPriority="high" />
          </picture>
          <div className="absolute inset-0 animate-breathe" aria-hidden="true" />
        </div>
      </div>
      <ConnectGmailModal isOpen={setupOpen} onClose={() => setSetupOpen(false)} />
    </section>
  )
}
export default Hero
