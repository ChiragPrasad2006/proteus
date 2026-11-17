import { Aperture } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

interface WordmarkProps {
  to?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
  showIcon?: boolean
}

const sizes = {
  sm: { icon: 'h-5 w-5', text: 'text-lg' },
  md: { icon: 'h-6 w-6', text: 'text-xl' },
  lg: { icon: 'h-8 w-8', text: 'text-3xl' },
} as const

/** Proteus wordmark + aperture glyph. */
export function Wordmark({ to = '/', size = 'md', className, showIcon = true }: WordmarkProps) {
  const s = sizes[size]
  const content = (
    <span className={cn('group inline-flex items-center gap-2.5', className)}>
      {showIcon ? (
        <span className="relative inline-flex items-center justify-center">
          <Aperture
            className={cn(s.icon, 'text-accent transition-transform duration-300 ease-proteus group-hover:rotate-45')}
            strokeWidth={1.4}
          />
          <span className="absolute inset-0 rounded-full bg-accent/20 blur-md" aria-hidden />
        </span>
      ) : null}
      <span
        className={cn(
          'font-display font-medium tracking-tight text-fg',
          s.text,
        )}
      >
        Proteus
      </span>
    </span>
  )

  if (!to) return content
  return (
    <Link to={to} className="inline-flex rounded-md" aria-label="Proteus home">
      {content}
    </Link>
  )
}

export default Wordmark
