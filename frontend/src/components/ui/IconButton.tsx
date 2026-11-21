import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name — also shown as the tooltip text. */
  label: string
  /** Optional mono shortcut badge rendered inside the tooltip. */
  shortcut?: string
  children: ReactNode
  /** Tooltip placement relative to the button. */
  tipSide?: 'top' | 'bottom'
  surface?: 'cobalt' | 'paper'
}

/**
 * Icon-only button with an accessible name and a hover/focus tooltip that
 * carries a mono shortcut badge (a11y requirement for icon-only controls).
 */
export function IconButton({ label, shortcut, children, tipSide = 'top', surface = 'cobalt', className, ...props }: IconButtonProps) {
  return (
    <span className="group/tip relative inline-flex">
      <button
        type="button"
        aria-label={label}
        className={cn(
          'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-pill transition-colors',
          surface === 'cobalt' ? 'text-paper-muted hover:bg-paper/10 hover:text-paper' : 'text-ink-muted hover:bg-ink/5 hover:text-ink',
          className,
        )}
        {...props}
      >
        {children}
      </button>
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute left-1/2 z-[80] -translate-x-1/2 whitespace-nowrap rounded-card border px-2 py-1 font-mono text-[12px] opacity-0 transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100',
          tipSide === 'top' ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]',
          surface === 'cobalt' ? 'border-hairline bg-ink text-paper' : 'border-ink-hairline bg-paper text-ink',
        )}
      >
        {label}
        {shortcut ? <kbd className="ml-1.5 rounded-[2px] border border-current/30 px-1 text-[12px]">{shortcut}</kbd> : null}
      </span>
    </span>
  )
}

export default IconButton