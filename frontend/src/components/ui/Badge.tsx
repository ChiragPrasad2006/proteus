import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-pill border font-mono text-[12px] uppercase tracking-[0.14em] transition-colors duration-300 ease-proteus',
  {
    variants: {
      tone: {
        neutral: 'border-hairline bg-paper/[0.04] text-paper-muted',
        accent: 'border-foam/40 bg-foam/10 text-foam',
        success: 'border-foam/50 bg-foam/10 text-foam',
        warning: 'border-ember/60 bg-ember/10 text-paper',
        danger: 'border-ember/60 bg-ember/10 text-paper',
        outline: 'border-hairline text-paper',
      },
      size: { sm: 'px-2 py-0.5', md: 'px-2.5 py-1' },
    },
    defaultVariants: { tone: 'neutral', size: 'sm' },
  },
)

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}
export function Badge({ className, tone, size, ...props }: BadgeProps) { return <span className={cn(badgeVariants({ tone, size }), className)} {...props} /> }
export default Badge
