import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-pill font-medium transition-all duration-300 ease-proteus disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foam focus-visible:ring-offset-2 focus-visible:ring-offset-cobalt',
  {
    variants: {
      variant: {
        primary: 'bg-paper text-ink hover:-translate-y-px hover:bg-white',
        secondary: 'bg-cobalt-deep text-paper border border-hairline hover:border-paper-label hover:bg-cobalt',
        ghost: 'text-paper-muted hover:bg-paper/10 hover:text-paper',
        outline: 'border border-hairline text-paper hover:border-paper-label hover:bg-paper/5',
        danger: 'bg-ember-ink text-white border border-ember hover:bg-[#992B0A]',
      },
      size: { sm: 'h-8 px-3.5 text-[12px]', md: 'h-10 px-5 text-sm', lg: 'h-12 px-7 text-[15px]', icon: 'h-9 w-9 p-0' },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export function Button({ className, variant, size, leftIcon, rightIcon, children, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props}>{leftIcon}{children}{rightIcon}</button>
}

export default Button