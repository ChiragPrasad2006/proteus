import { ArrowUpRight, Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Wordmark } from '@/components/ui/Wordmark'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { label: 'Product', href: '#product' },
  { label: 'Stylometry', href: '#stylometry' },
  { label: 'Safety', href: '#safety' },
  { label: 'Method', href: '#method' },
]

/** Fixed glassmorphism navbar with pill links and the workspace CTA. */
export function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={cn(
        'glass fixed inset-x-0 top-0 z-50 transition-all duration-300 ease-proteus',
        scrolled ? 'border-b border-hairline py-2.5' : 'border-b border-transparent py-4',
      )}
    >
      <nav className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 lg:px-10">
        <Wordmark to="/" size="md" />

        {/* Pill nav links */}
        <div className="hidden items-center gap-1 rounded-full border border-hairline bg-white/[0.03] p-1 md:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="rounded-full px-4 py-1.5 text-[13px] font-medium text-fg-muted transition-colors duration-300 ease-proteus hover:bg-white/[0.06] hover:text-fg"
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="hidden items-center gap-3 md:flex">
          <Link to="/workspace">
            <Button variant="ghost" size="sm">
              Sign in
            </Button>
          </Link>
          <Link to="/workspace">
            <Button size="sm" rightIcon={<ArrowUpRight className="h-4 w-4" />}>
              Open workspace
            </Button>
          </Link>
        </div>

        <button
          type="button"
          aria-label={open ? 'Close menu' : 'Open menu'}
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-hairline text-fg-muted md:hidden"
        >
          {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
        </button>
      </nav>

      {open ? (
        <div className="mx-auto mt-3 max-w-7xl px-6 md:hidden">
          <div className="flex flex-col gap-1 rounded-2xl border border-hairline bg-surface/95 p-3 backdrop-blur">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-2 text-sm text-fg-muted hover:bg-white/[0.06] hover:text-fg"
              >
                {link.label}
              </a>
            ))}
            <Link to="/workspace" onClick={() => setOpen(false)} className="mt-1">
              <Button className="w-full" size="md">
                Open workspace
              </Button>
            </Link>
          </div>
        </div>
      ) : null}
    </header>
  )
}

export default Navbar
