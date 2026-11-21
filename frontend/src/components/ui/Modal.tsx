import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface ModalProps {
  open: boolean
  onClose: () => void
  label: string
  children: ReactNode
  /** Paper letter surface (default) vs cobalt panel. */
  surface?: 'paper' | 'cobalt'
  className?: string
}

/**
 * In-app modal — never window.alert/window.confirm. Esc closes, backdrop
 * click closes, focus moves into the dialog on open. Zero shadows: hairlines.
 */
export function Modal({ open, onClose, label, children, surface = 'paper', className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
    }
    document.addEventListener('keydown', onKeyDown)
    const previous = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previous?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/70 p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className={cn(
          'relative max-h-[88svh] w-full max-w-md overflow-y-auto rounded-card border outline-none',
          surface === 'paper' ? 'on-paper border-ink-hairline bg-paper text-ink' : 'border-hairline bg-cobalt-deep text-paper',
          className,
        )}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className={cn(
            'absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-pill',
            surface === 'paper' ? 'text-ink-muted hover:bg-ink/5 hover:text-ink' : 'text-paper-muted hover:bg-paper/10 hover:text-paper',
          )}
        >
          <X className="h-4 w-4" />
        </button>
        {children}
      </div>
    </div>
  )
}

export default Modal