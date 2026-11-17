import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'

interface SerratedDividerProps {
  /** Edge that carries the scalloped teeth. */
  position?: 'top' | 'bottom'
  /** Tooth width in px; height is derived. */
  tooth?: number
  /** Colour of the divider body (usually the surface it caps). */
  color?: string
  className?: string
}

/**
 * A serrated paper edge built from a repeating radial-gradient mask —
 * no images, fully resolution-independent.
 */
export function SerratedDivider({
  position = 'top',
  tooth = 22,
  color = '#0C0A09',
  className,
}: SerratedDividerProps) {
  const height = Math.ceil(tooth / 2) + 3
  const style = {
    '--tooth': `${tooth}px`,
    height: `${height}px`,
    backgroundColor: color,
  } as CSSProperties

  return (
    <div
      aria-hidden="true"
      role="presentation"
      style={style}
      className={cn(
        'serrated w-full',
        position === 'top' ? 'serrated-top' : 'serrated-bottom',
        className,
      )}
    />
  )
}

export default SerratedDivider
