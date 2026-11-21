import { useCallback, useState } from 'react'
import { DEFAULT_PANE_LAYOUT, getPaneLayout, setPaneLayout, type PaneLayout } from '@/lib/localAdapter'
import { clamp } from '@/lib/utils'

export const LEFT_MIN = 220
export const LEFT_MAX = 360
export const RIGHT_MIN = 360
export const RIGHT_MAX = 620
export const LEFT_COLLAPSED_WIDTH = 56

/** Resizable/collapsible pane widths, persisted in localStorage. */
export function usePaneLayout() {
  const [layout, setLayout] = useState<PaneLayout>(() => {
    try { return getPaneLayout() } catch { return DEFAULT_PANE_LAYOUT }
  })

  const update = useCallback((patch: Partial<PaneLayout>) => {
    setLayout((current) => {
      const next: PaneLayout = {
        leftWidth: clamp(patch.leftWidth ?? current.leftWidth, LEFT_MIN, LEFT_MAX),
        rightWidth: clamp(patch.rightWidth ?? current.rightWidth, RIGHT_MIN, RIGHT_MAX),
        leftCollapsed: patch.leftCollapsed ?? current.leftCollapsed,
        rightCollapsed: patch.rightCollapsed ?? current.rightCollapsed,
      }
      setPaneLayout(next)
      return next
    })
  }, [])

  return { layout, update }
}