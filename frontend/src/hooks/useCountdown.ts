import { useEffect, useState } from 'react'

/** Whole seconds remaining until `endsAt` (epoch ms); re-renders each second. */
export function useCountdownSeconds(endsAt: number | undefined): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (endsAt === undefined) return
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [endsAt])
  if (endsAt === undefined) return 0
  return Math.max(0, Math.ceil((endsAt - now) / 1000))
}