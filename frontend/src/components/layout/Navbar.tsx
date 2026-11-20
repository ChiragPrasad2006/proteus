import { ArrowUpRight, Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Wordmark } from '@/components/ui/Wordmark'
import { cn } from '@/lib/utils'
import { startGoogleSignIn } from '@/lib/googleAuth'
import { EmailSignInModal } from '@/components/auth/EmailSignInModal'
import { ApiError } from '@/lib/api'

const NAV_LINKS = [
  { label: 'How it learns', href: '#how-it-learns' },
  { label: 'Privacy', href: '#privacy' },
  { label: 'Source', href: 'https://github.com/ChiragPrasad2006/proteus' },
]

export function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)
  const [emailSignInOpen, setEmailSignInOpen] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const openProteus = async () => {
    setAuthError(null)
    try {
      if (!(await startGoogleSignIn())) setEmailSignInOpen(true)
    } catch (error) {
      setAuthError(error instanceof ApiError && error.status === 0
        ? 'Cannot reach Proteus backend on 127.0.0.1:8000 — start Proteus.exe'
        : 'Google sign-in could not be started. Please try again.')
    }
  }
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16)
    onScroll(); window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return (
    <header className={cn('fixed inset-x-0 top-0 z-50 transition-all duration-300 ease-proteus', scrolled ? 'border-b border-hairline bg-cobalt/95 backdrop-blur-sm' : 'border-b border-transparent')}>
      <nav className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 px-5 py-4 md:px-10">
        <Wordmark to="/" size="md" />
        <div className="hidden items-center gap-7 md:flex">
          {NAV_LINKS.map((link) => <a key={link.label} href={link.href} className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper-label transition-colors hover:text-foam">{link.label}</a>)}
        </div>
        <button type="button" onClick={openProteus} className="hidden items-center gap-2 rounded-pill border border-hairline px-4 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors hover:border-paper-label hover:bg-paper/5 md:inline-flex">Open Proteus <ArrowUpRight className="h-3.5 w-3.5" /></button>
        <button type="button" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen((value) => !value)} className="inline-flex h-9 w-9 items-center justify-center rounded-pill border border-hairline text-paper md:hidden">{open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}</button>
      </nav>
      {open ? (
        <div className="fixed inset-0 z-40 flex flex-col bg-cobalt px-5 pb-8 pt-24 md:hidden">
          <nav className="flex flex-col" aria-label="Mobile navigation">
            {NAV_LINKS.map((link) => <a key={link.label} href={link.href} onClick={() => setOpen(false)} className="border-b border-hairline py-5 font-mono text-sm uppercase tracking-[0.16em] text-paper">{link.label}</a>)}
          </nav>
          <button type="button" onClick={() => { setOpen(false); void openProteus() }} className="mt-auto rounded-pill bg-paper px-5 py-4 text-center font-mono text-sm uppercase tracking-[0.14em] text-ink">Open Proteus</button>
        </div>
      ) : null}
      {authError ? <p role="alert" className="border-b border-ember/40 bg-ink/20 px-5 py-2 text-center text-[11px] text-paper-muted">{authError}</p> : null}
      <EmailSignInModal
        isOpen={emailSignInOpen}
        onClose={() => setEmailSignInOpen(false)}
        onSignedIn={() => { window.location.href = '/workspace' }}
        note="Google OAuth is not configured on this machine yet — sign in with your email to continue, then configure App Password or OAuth inside the workspace"
      />
    </header>
  )
}
export default Navbar
