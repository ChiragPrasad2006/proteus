import { cn } from '@/lib/utils'

interface AvatarProps {
  initials: string
  /** Tailwind gradient stops, e.g. "from-[#D4F268] to-[#7C9B2E]". */
  hue?: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  className?: string
  ring?: boolean
}

const sizeMap = {
  xs: 'h-6 w-6 text-[10px]',
  sm: 'h-8 w-8 text-[11px]',
  md: 'h-10 w-10 text-xs',
  lg: 'h-12 w-12 text-sm',
} as const

export function Avatar({ initials, hue = 'from-[#D4F268] to-[#7C9B2E]', size = 'md', className, ring }: AvatarProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-mono font-semibold uppercase tracking-wider text-ink',
        hue,
        sizeMap[size],
        ring && 'ring-2 ring-ink',
        className,
      )}
      aria-hidden="true"
    >
      {initials}
    </span>
  )
}

export default Avatar
