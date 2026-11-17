import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border font-mono text-[10px] uppercase tracking-[0.16em] transition-colors duration-300 ease-proteus',
  {
    variants: {
      tone: {
        neutral: 'border-hairline bg-white/[0.04] text-fg-muted',
        accent: 'border-accent/30 bg-accent/10 text-accent',
        success: 'border-[#3f6212]/50 bg-[#D4F268]/10 text-[#c4e85a]',
        warning: 'border-[#92400e]/60 bg-[#f59e0b]/10 text-[#fbbf24]',
        danger: 'border-[#7f1d1d]/60 bg-[#ef4444]/10 text-[#fca5a5]',
        outline: 'border-hairline-strong bg-transparent text-fg',
      },
      size: {
        sm: 'px-2 py-0.5',
        md: 'px-2.5 py-1',
      },
    },
    defaultVariants: { tone: 'neutral', size: 'sm' },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone, size }), className)} {...props} />
}

export { badgeVariants }
export default Badge
