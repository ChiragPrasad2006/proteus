import { Sparkles, Users } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { cn, initialsFrom } from '@/lib/utils'
import type { RecipientContact, RelationshipTier } from '@/types'

const TIER_TONE: Record<RelationshipTier, 'accent' | 'neutral' | 'warning' | 'success'> = { executive_or_client: 'accent', peer: 'success', direct_report: 'neutral', external: 'warning', unknown: 'neutral' }
const HUE_BY_TIER: Record<RelationshipTier, string> = { executive_or_client: 'from-paper to-foam', peer: 'from-cobalt to-cobalt-deep', direct_report: 'from-foam to-paper', external: 'from-ember to-ember-ink', unknown: 'from-paper-muted to-ink' }
export function ResolvedContactsStrip({ contacts: contactInput }: { contacts?: RecipientContact[] | null }) {
  const contacts = Array.isArray(contactInput) ? contactInput : []
  if (contacts.length === 0) return null
  return (
    <div className="rounded-card border border-hairline bg-cobalt p-3.5">
      <div className="mb-3 flex items-center gap-2"><Users className="h-3.5 w-3.5 text-foam" strokeWidth={1.6} /><span className="font-mono text-[9px] uppercase tracking-[0.16em] text-paper-label">Resolved contacts · {contacts.length}</span></div>
      <div className="flex flex-wrap gap-2">{contacts.map((contact) => <div key={contact.id} className={cn('flex items-center gap-2.5 rounded-pill border py-1.5 pl-1.5 pr-3.5', contact.isNew ? 'border-ember/60 bg-ember/10' : 'border-hairline bg-paper/[0.04]')}><Avatar initials={initialsFrom(contact.name)} hue={HUE_BY_TIER[contact.tier]} size="sm" /><div className="leading-tight"><div className="flex items-center gap-1.5"><span className="text-[12.5px] font-medium text-paper">{contact.name}</span>{contact.isNew ? <span className="inline-flex items-center gap-0.5 font-mono text-[9px] uppercase tracking-wider text-ember"><Sparkles className="h-2.5 w-2.5" /> new</span> : null}</div><span className="font-mono text-[9px] text-paper-label">{contact.email}</span></div><span className="ml-1 hidden items-center gap-1.5 sm:flex"><Badge tone={TIER_TONE[contact.tier]}>{contact.relationship}</Badge><span className="font-mono text-[9px] text-paper-label">{Math.round(contact.confidence * 100)}%</span></span></div>)}</div>
    </div>
  )
}
export default ResolvedContactsStrip
