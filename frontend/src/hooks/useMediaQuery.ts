import { useSyncExternalStore } from 'react'

function subscribe(query: string, callback: () => void): () => void {
  const mql = window.matchMedia(query)
  mql.addEventListener('change', callback)
  return () => mql.removeEventListener('change', callback)
}

/** SSR-safe matchMedia hook (workspace breakpoints: 768px / 1100px). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (callback) => subscribe(query, callback),
    () => window.matchMedia(query).matches,
    () => false,
  )
}

export const useIsMobile = () => useMediaQuery('(max-width: 767px)')
export const useIsTablet = () => useMediaQuery('(max-width: 1099px)')