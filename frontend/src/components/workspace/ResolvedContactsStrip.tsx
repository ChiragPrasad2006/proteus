import { Sparkles, Users } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { cn, initialsFrom } from '@/lib/utils'
import type { RecipientContact, RelationshipTier } from '@/types'

const TIER_TONE: Record<RelationshipTier, 'accent' | 'neutral' | 'warning' | 'success'> = {
  executive_or_client: 'accent',
  peer: 'success',
  direct_report: 'neutral',
  external: 'warning',
  unknown: 'neutral',
}

const HUE_BY_TIER: Record<RelationshipTier, string> = {
  executive_or_client: 'from-[#D4F268] to-[#7C9B2E]',
  peer: 'from-[#8AB4F8] to-[#3B5BDB]',
  direct_report: 'from-[#F0A5C0] to-[#B5487A]',
  external: 'from-[#FCD34D] to-[#B45309]',
  unknown: 'from-[#a8a29e] to-[#57534e]',
}

/** Horizontal strip of contacts the agent resolved from the local corpus. */
export function ResolvedContactsStrip({ contacts: contactInput }: { contacts?: RecipientContact[] | null }) {
  const contacts = Array.isArray(contactInput) ? contactInput : []
  if (contacts.length === 0) return null

  return (
    <div className="rounded-[18px] border border-hairline bg-elevated/40 p-3.5">
      <div className="mb-3 flex items-center gap-2">
        <Users className="h-3.5 w-3.5 text-accent" strokeWidth={1.6} />
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
          Resolved contacts · {contacts.length}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {contacts.map((contact) => (
          <div
            key={contact.id}
            className={cn(
              'flex items-center gap-2.5 rounded-full border py-1.5 pl-1.5 pr-3.5 transition-colors duration-300 ease-proteus',
              contact.isNew
                ? 'border-[#92400e]/50 bg-[#f59e0b]/[0.06]'
                : 'border-hairline bg-white/[0.03] hover:border-hairline-strong',
            )}
          >
            <Avatar
              initials={initialsFrom(contact.name)}
              hue={HUE_BY_TIER[contact.tier]}
              size="sm"
            />
            <div className="leading-tight">
              <div className="flex items-center gap-1.5">
                <span className="text-[12.5px] font-medium text-fg">{contact.name}</span>
                {contact.isNew ? (
                  <span className="inline-flex items-center gap-0.5 font-mono text-[9px] uppercase tracking-wider text-[#fbbf24]">
                    <Sparkles className="h-2.5 w-2.5" /> new
                  </span>
                ) : null}
              </div>
              <span className="font-mono text-[10px] text-fg-faint">{contact.email}</span>
            </div>

            <span className="ml-1 hidden items-center gap-1.5 sm:flex">
              <Badge tone={TIER_TONE[contact.tier]}>{contact.relationship}</Badge>
              <span className="font-mono text-[10px] text-fg-faint">
                {Math.round(contact.confidence * 100)}%
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ResolvedContactsStrip
