import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { audienceFor } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'
import type { ExplainabilityMeta, SuppressedRuleExplainability, WorkspaceDraft } from '@/types'

export interface ExplainabilityCardProps {
  draft: WorkspaceDraft
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : []
}

function asSuppressedRules(value: unknown): SuppressedRuleExplainability[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      rule: typeof item.rule === 'string' ? item.rule : '',
      reason: typeof item.reason === 'string' ? item.reason : '',
    }))
    .filter((item) => item.rule.length > 0)
}

function resolveExplainability(draft: WorkspaceDraft): ExplainabilityMeta | null {
  const raw = draft.resolutionMeta?.explainability as Record<string, unknown> | undefined
  if (raw && typeof raw === 'object' && typeof raw.audience_type === 'string') {
    const audType = raw.audience_type === 'group_cc' || raw.audience_type === 'broadcast_bcc'
      ? raw.audience_type
      : '1on1_private'
    const audLabel = audType === 'broadcast_bcc'
      ? 'Broadcast BCC'
      : audType === 'group_cc'
        ? 'Group CC'
        : '1:1 Private'
    const conf = raw.confidence_level === 'high' || raw.confidence_level === 'medium' || raw.confidence_level === 'low'
      ? raw.confidence_level
      : 'low'
    const count = typeof raw.retrieved_examples_count === 'number' && Number.isFinite(raw.retrieved_examples_count)
      ? Math.max(0, raw.retrieved_examples_count)
      : 0
    return {
      audience_type: audType,
      audience_label: typeof raw.audience_label === 'string' && (raw.audience_label === '1:1 Private' || raw.audience_label === 'Group CC' || raw.audience_label === 'Broadcast BCC')
        ? raw.audience_label
        : audLabel,
      audience_reason: typeof raw.audience_reason === 'string' && raw.audience_reason
        ? raw.audience_reason
        : audienceFor(draft.to, draft.cc, draft.bcc).why,
      confidence_level: conf,
      retrieved_examples_count: count,
      retrieved_examples_summary: typeof raw.retrieved_examples_summary === 'string' && raw.retrieved_examples_summary
        ? raw.retrieved_examples_summary
        : `${count} relevant example${count === 1 ? '' : 's'} retrieved`,
      recipient_rules_used: asStringArray(raw.recipient_rules_used),
      global_rules_used: asStringArray(raw.global_rules_used),
      suppressed_rules: asSuppressedRules(raw.suppressed_rules),
      default_style_used: Boolean(raw.default_style_used),
      default_style_reason: typeof raw.default_style_reason === 'string' ? raw.default_style_reason : null,
    }
  }

  // Backward-compatible minimal fallback for older persisted drafts lacking explainability
  const meta = draft.resolutionMeta
  if (!meta || Object.keys(meta).length === 0) return null
  const aud = audienceFor(draft.to, draft.cc, draft.bcc)
  const confRaw = meta.confidence?.level
  const conf = confRaw === 'high' || confRaw === 'medium' ? confRaw : 'low'
  const matched = typeof meta.confidence?.signals?.usable_example_count === 'number'
    ? meta.confidence.signals.usable_example_count
    : typeof meta.examples_matched === 'number'
      ? meta.examples_matched
      : 0
  const fallbackUsed = Boolean(meta.cold_start_fallback ?? conf === 'low')
  return {
    audience_type: aud.mode,
    audience_label: aud.label as ExplainabilityMeta['audience_label'],
    audience_reason: aud.mode === 'broadcast_bcc'
      ? 'Bcc recipients detected'
      : aud.mode === 'group_cc'
        ? 'Cc or multiple To recipients detected'
        : '1 recipient in To, no Cc/Bcc',
    confidence_level: conf,
    retrieved_examples_count: matched,
    retrieved_examples_summary: matched > 0
      ? `${matched} relevant example${matched === 1 ? '' : 's'} retrieved`
      : 'No prior matching conversations found',
    recipient_rules_used: [],
    global_rules_used: [],
    suppressed_rules: [],
    default_style_used: fallbackUsed,
    default_style_reason: fallbackUsed
      ? 'Global professional style applied for this audience.'
      : null,
  }
}

export function ExplainabilityCard({ draft }: ExplainabilityCardProps) {
  const setProfileOpen = useWorkspaceUI((state) => state.setProfileOpen)
  const [expanded, setExpanded] = useState(false)
  const [prevDraftId, setPrevDraftId] = useState(draft.id)
  if (draft.id !== prevDraftId) {
    setPrevDraftId(draft.id)
    setExpanded(false)
  }

  const info = resolveExplainability(draft)
  if (!info) return null

  const confidenceLabel = info.confidence_level === 'high'
    ? 'High'
    : info.confidence_level === 'medium'
      ? 'Medium'
      : 'Low'
  const confidenceClass = info.confidence_level === 'high'
    ? 'border-foam-ink/35 text-foam-ink'
    : info.confidence_level === 'low'
      ? 'border-ember-ink/35 text-ember-ink'
      : 'border-ink-hairline text-ink'

  const summaryParts: string[] = [info.audience_label]
  if (info.retrieved_examples_count > 0) {
    summaryParts.push(`${info.retrieved_examples_count} example${info.retrieved_examples_count === 1 ? '' : 's'}`)
  } else if (info.default_style_used) {
    summaryParts.push('Default style used')
  } else {
    summaryParts.push('0 examples')
  }
  if (info.suppressed_rules.length > 0) {
    summaryParts.push(`${info.suppressed_rules.length} rule${info.suppressed_rules.length === 1 ? '' : 's'} suppressed`)
  } else if (info.default_style_used && info.retrieved_examples_count > 0) {
    summaryParts.push('Default style used')
  }

  return (
    <div className="rounded-card border border-ink-hairline bg-paper text-ink">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 px-3.5 py-2 text-left text-[12px] text-ink-muted transition-colors hover:text-ink"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="font-mono uppercase tracking-[0.08em] text-ink">Why this draft</span>
          <span aria-hidden>·</span>
          <span>{summaryParts[0]}</span>
          <span aria-hidden>·</span>
          <span>{summaryParts[1]}</span>
          {summaryParts[2] ? (
            <>
              <span aria-hidden>·</span>
              <span className={cn(info.suppressed_rules.length > 0 && 'text-ember-ink font-medium')}>
                {summaryParts[2]}
              </span>
            </>
          ) : null}
        </span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', expanded && 'rotate-180')} aria-hidden />
      </button>

      {expanded ? (
        <div className="space-y-3 border-t border-ink-hairline px-3.5 py-3 text-[12.5px] leading-relaxed">
          {/* 1. Audience & Confidence */}
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">Audience</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="rounded-pill border border-ink-hairline px-2.5 py-0.5 font-mono text-[12px] text-ink">
                {info.audience_label}
              </span>
              <span className={cn('rounded-pill border px-2.5 py-0.5 font-mono text-[12px] font-medium', confidenceClass)}>
                {confidenceLabel} confidence
              </span>
              <span className="text-ink-muted">{info.audience_reason}</span>
            </div>
          </div>

          {/* 2. Historical Evidence */}
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">Historical evidence</p>
            <p className="mt-1 text-ink">{info.retrieved_examples_summary}</p>
          </div>

          {/* 3. Recipient Rules Applied */}
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">Recipient rules applied</p>
            {info.recipient_rules_used.length > 0 ? (
              <ul className="mt-1 list-disc space-y-1 pl-4 text-ink">
                {info.recipient_rules_used.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-ink-muted">No recipient-specific rules applied</p>
            )}
          </div>

          {/* 4. Rules Suppressed */}
          {info.suppressed_rules.length > 0 ? (
            <div>
              <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-ember-ink">Rules suppressed</p>
              <ul className="mt-1 space-y-1.5 text-ember-ink">
                {info.suppressed_rules.map((item) => (
                  <li key={`${item.rule}-${item.reason}`} className="rounded-card border border-ember-ink/25 bg-ember-ink/5 px-2.5 py-1.5">
                    <span className="font-medium">“{item.rule}”</span>
                    <span className="block text-[12px] text-ember-ink">— {item.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* 5. Default Style Fallback */}
          {info.default_style_used && info.default_style_reason ? (
            <div>
              <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-ink-muted">Default style fallback</p>
              <p className="mt-1 text-ink">{info.default_style_reason}</p>
            </div>
          ) : null}

          <div className="border-t border-ink-hairline pt-2.5">
            <button
              type="button"
              onClick={() => setProfileOpen(true)}
              className="rounded-card border border-ink-hairline px-2.5 py-1 font-mono text-[12px] text-ink-muted transition-colors hover:border-ink/50 hover:text-ink"
            >
              Manage rules →
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default ExplainabilityCard
