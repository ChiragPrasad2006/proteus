import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-all duration-300 ease-proteus disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-ink',
  {
    variants: {
      variant: {
        primary:
          'bg-accent text-ink hover:bg-accent-dim active:scale-[0.98] shadow-[0_10px_30px_-14px_rgba(212,242,104,0.7)]',
        secondary:
          'bg-elevated text-fg border border-hairline hover:border-hairline-strong hover:bg-white/[0.06] active:scale-[0.98]',
        ghost: 'text-fg-muted hover:bg-white/[0.06] hover:text-fg active:scale-[0.98]',
        outline:
          'border border-hairline-strong bg-transparent text-fg hover:border-accent/50 hover:text-accent active:scale-[0.98]',
        danger:
          'bg-[#3b1414] text-[#fca5a5] border border-[#7f1d1d]/60 hover:bg-[#4a1a1a] active:scale-[0.98]',
      },
      size: {
        sm: 'h-8 px-3.5 text-[13px]',
        md: 'h-10 px-5 text-sm',
        lg: 'h-12 px-7 text-[15px]',
        icon: 'h-9 w-9 p-0',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export function Button({
  className,
  variant,
  size,
  leftIcon,
  rightIcon,
  children,
  ...props
}: ButtonProps) {
  return (
    <button className={cn(buttonVariants({ variant, size }), className)} {...props}>
      {leftIcon}
      {children}
      {rightIcon}
    </button>
  )
}

export { buttonVariants }
export default Button
