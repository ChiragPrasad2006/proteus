/**
 * Word-level diff (LCS) used by the draft version compare view and the
 * "What I learned" edit diff. Whitespace is preserved as its own tokens so
 * additions/removals render inline without reflowing the whole letter.
 */

export type DiffSegmentType = 'same' | 'add' | 'del'

export interface DiffSegment {
  type: DiffSegmentType
  text: string
}

function tokenize(text: string): string[] {
  return text.split(/(\s+)/).filter((token) => token.length > 0)
}

export function wordDiff(before: string, after: string): DiffSegment[] {
  const a = tokenize(before)
  const b = tokenize(after)
  const n = a.length
  const m = b.length
  // LCS length table (draft bodies are small; O(n·m) is fine here).
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i]![j] = a[i] === b[j] ? table[i + 1]![j + 1]! + 1 : Math.max(table[i + 1]![j]!, table[i]![j + 1]!)
    }
  }
  const segments: DiffSegment[] = []
  const push = (type: DiffSegmentType, text: string) => {
    const last = segments[segments.length - 1]
    if (last && last.type === type) last.text += text
    else segments.push({ type, text })
  }
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { push('same', a[i]!); i += 1; j += 1 }
    else if (table[i + 1]![j]! >= table[i]![j + 1]!) { push('del', a[i]!); i += 1 }
    else { push('add', b[j]!); j += 1 }
  }
  while (i < n) { push('del', a[i]!); i += 1 }
  while (j < m) { push('add', b[j]!); j += 1 }
  return segments
}

export function diffHasChanges(segments: DiffSegment[]): boolean {
  return segments.some((segment) => segment.type !== 'same')
}