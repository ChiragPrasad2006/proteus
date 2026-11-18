import { useEffect, useState } from 'react'
import { FolderTabs } from '@/components/landing/FolderTabs'
import { Hero } from '@/components/landing/Hero'
import { ShowcaseGrid } from '@/components/landing/ShowcaseGrid'
import { StickyNoteCTA } from '@/components/landing/StickyNoteCTA'
import { Navbar } from '@/components/layout/Navbar'
import { SerratedDivider } from '@/components/effects/SerratedDivider'
import { Wordmark } from '@/components/ui/Wordmark'

/** Marketing page: fixed navbar → 5:7 hero → serrated tear → product → method → CTA. */
export function LandingPage() {
  const [oauthError, setOauthError] = useState<string | null>(null)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('auth') === 'error') {
      setOauthError(params.get('reason') || 'Google sign-in could not be completed.')
      window.history.replaceState({}, '', '/')
    }
  }, [])
  return (
    <div className="min-h-screen bg-ink text-fg">
      <Navbar />
      {oauthError ? <div role="status" className="mx-auto mt-4 max-w-7xl rounded border border-red/40 bg-red/10 px-4 py-3 text-sm text-red">{oauthError}</div> : null}

      <main>
        <Hero />

        <SerratedDivider position="top" color="#0C0A09" />

        <FolderTabs />
        <ShowcaseGrid />
        <StickyNoteCTA />
      </main>

      <footer className="border-t border-hairline">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-6 py-10 sm:flex-row lg:px-10">
          <Wordmark to="/" size="sm" />
          <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-fg-faint">
            Local-first · Zero egress · v2.5 · 3B
          </p>
        </div>
      </footer>
    </div>
  )
}

export default LandingPage
