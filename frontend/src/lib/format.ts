/** Presentation helpers for dates, counts and stylometry labels. */

export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  const diffMs = now.getTime() - then.getTime()
  const min = Math.round(diffMs / 60_000)
  if (Number.isNaN(min)) return ''
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hrs = Math.round(min / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.round(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function formatDateLong(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return String(n)
}

export function formatPct(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`
}

export function formatGpuMemory(mib?: number): string {
  if (!mib) return '—'
  return `${(mib / 1024).toFixed(1)} GB`
}

/** Group sessions into Today / Previous 7 Days / Earlier buckets. */
export type SessionBucket = 'Today' | 'Previous 7 Days' | 'Earlier'

export function sessionBucket(iso: string, now: Date = new Date()): SessionBucket {
  const then = new Date(iso)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const sevenDaysAgo = new Date(startOfToday.getTime() - 7 * 24 * 60 * 60 * 1000)
  if (then >= startOfToday) return 'Today'
  if (then >= sevenDaysAgo) return 'Previous 7 Days'
  return 'Earlier'
}
