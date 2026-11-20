import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

interface WordmarkProps { to?: string; size?: 'sm' | 'md' | 'lg'; className?: string }
const sizes = { sm: 'text-xl', md: 'text-2xl', lg: 'text-5xl' } as const

export function Wordmark({ to = '/', size = 'md', className }: WordmarkProps) {
  const content = <span className={cn('font-display font-normal tracking-[-0.03em] text-paper', sizes[size], className)}>proteus</span>
  if (!to) return content
  return <Link to={to} className="inline-flex rounded-sm" aria-label="Proteus home">{content}</Link>
}
export default Wordmark
