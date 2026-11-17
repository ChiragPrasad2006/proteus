import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  Account,
  ChatMessage,
  EmailDraft,
  Provider,
  RecipientContact,
  Session,
} from '@/types'
import { uid } from '@/lib/utils'

/* ── Seed data ─────────────────────────────────────────────────────────
   A believable local workspace so the UI is fully explorable before the
   backend is wired up. Replaced by live data once /api responds. */

const now = Date.now()
const iso = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString()

export const SEED_ACCOUNTS: Account[] = [
  {
    id: 'acct_northwind',
    name: 'Maya Okonkwo',
    email: 'maya@northwind.co',
    provider: 'gmail',
    initials: 'MO',
    hue: 'from-[#D4F268] to-[#7C9B2E]',
  },
  {
    id: 'acct_work',
    name: 'M. Okonkwo · Work',
    email: 'm.okonkwo@northwind.co',
    provider: 'outlook',
    initials: 'MO',
    hue: 'from-[#8AB4F8] to-[#3B5BDB]',
  },
  {
    id: 'acct_personal',
    name: 'Maya (Personal)',
    email: 'maya.okonkwo@gmail.com',
    provider: 'imap',
    initials: 'MO',
    hue: 'from-[#F0A5C0] to-[#B5487A]',
  },
]

export const SEED_SESSIONS: Session[] = [
  {
    id: 'sess_renewal',
    title: 'Q3 renewal — Acme pricing pushback',
    preview: 'Draft a reply capping the uplift at 8% with quarterly billing…',
    updatedAt: iso(12),
    accountId: 'acct_northwind',
  },
  {
    id: 'sess_intro',
    title: 'Warm intro — Priya ↔ Atlas design review',
    preview: 'Two-line intro, mention the Thursday review slot…',
    updatedAt: iso(96),
    accountId: 'acct_northwind',
  },
  {
    id: 'sess_sec',
    title: 'Vendor security questionnaire follow-up',
    preview: 'Nudge for the SOC 2 addendum without sounding pushy…',
    updatedAt: iso(60 * 27),
    accountId: 'acct_work',
  },
  {
    id: 'sess_atlas',
    title: 'Apology + re-scope — Atlas timeline',
    preview: 'Acknowledge the slip, propose a phased delivery…',
    updatedAt: iso(60 * 24 * 4),
    accountId: 'acct_northwind',
  },
  {
    id: 'sess_offsite',
    title: 'Offsite agenda — facilitator notes',
    preview: 'Tighten the agenda to four sessions, add buffer…',
    updatedAt: iso(60 * 24 * 9),
    accountId: 'acct_personal',
  },
]

const danielContact: RecipientContact = {
  id: 'rc_daniel',
  name: 'Daniel Reyes',
  email: 'd.reyes@acme-holdings.com',
  tier: 'executive_or_client',
  relationship: 'Executive / Client',
  confidence: 0.94,
  sentCount: 14,
}

const priyaContact: RecipientContact = {
  id: 'rc_priya',
  name: 'Priya Nair',
  email: 'priya.nair@atlasdesign.io',
  tier: 'external',
  relationship: 'External Partner',
  confidence: 0.71,
  sentCount: 3,
  isNew: true,
}

export const SEED_DRAFT: EmailDraft = {
  id: 'draft_renewal',
  to: ['d.reyes@acme-holdings.com'],
  cc: ['finance@northwind.co'],
  bcc: [],
  subject: 'Re: Northwind Q3 renewal — revised commercial terms',
  body: `Hi Daniel,

Thanks for the frank feedback on the uplift — I'd rather get this right than get it signed quickly.

Taking your two constraints at face value:

• Uplift capped at 8% for the renewal term (down from 18%)
• Quarterly billing instead of annual-in-advance

The one thing I'd ask in return is a 24-month commitment, which lets us hold the 8% flat through the second year rather than re-opening pricing next Q3.

I've attached the revised order form with those numbers. Happy to walk through it Thursday if that's easier than email.

Best,
Maya`,
  warnings: [
    {
      id: 'w_new',
      severity: 'warning',
      title: 'First-recipient review required',
      detail:
        'Daniel Reyes is flagged as Executive / Client with a commercial-concession topic. Proteus will not auto-send pricing commitments — approve explicitly to dispatch.',
    },
    {
      id: 'w_concession',
      severity: 'info',
      title: 'New commitment detected',
      detail:
        'The draft introduces a 24-month term not present in your intent. It reflects your usual reciprocity framing but is a binding ask — confirm it is intended.',
    },
  ],
  retrievedExamples: [
    {
      message_id: 'msg_8812',
      recipient_email: 'd.reyes@acme-holdings.com',
      subject: 'Re: Northwind ↔ Acme — 2024 scope',
      clean_body:
        'Hi Daniel,\n\nTaking your two constraints at face value: cap the increase and move to quarterly. The trade I\u2019d ask for is a longer commitment so we can hold the number flat.\n\nBest,\nMaya',
      greeting: 'Hi Daniel,',
      signoff: 'Best,\nMaya',
      word_count: 92,
      timestamp: '2025-06-14T09:12:00Z',
    },
    {
      message_id: 'msg_7704',
      recipient_email: 'd.reyes@acme-holdings.com',
      subject: 'Re: Contract amendment',
      clean_body:
        'Hi Daniel,\n\nRevised order form attached with the numbers we discussed. Happy to walk through it live if that is easier than trading paragraphs.\n\nBest,\nMaya',
      greeting: 'Hi Daniel,',
      signoff: 'Best,\nMaya',
      word_count: 61,
      timestamp: '2025-03-02T16:40:00Z',
    },
  ],
  modelUsed: 'Qwen3:8B',
  status: 'PENDING_REVIEW',
  reviewReason: 'Commercial concession · first recipient gate',
}

export const SEED_MESSAGES: ChatMessage[] = [
  {
    id: 'msg_1',
    role: 'assistant',
    content:
      "I've loaded your Northwind corpus — 412 cleaned sent emails, 61 of them to Acme. Ask me to draft anything and I'll match your voice.",
    createdAt: iso(14),
    status: 'done',
  },
  {
    id: 'msg_2',
    role: 'user',
    content:
      "Reply to Daniel about the renewal. He's pushing back on the 18% uplift — wants it capped at 8% and switched to quarterly billing. Keep my tone.",
    createdAt: iso(13),
    status: 'done',
  },
  {
    id: 'msg_3',
    role: 'assistant',
    content:
      "Drafted a reply that concedes the two points and asks for a 24-month term in return — that's the trade you made the last two times you renegotiated with Acme.",
    createdAt: iso(12),
    status: 'done',
    reasoning: [
      'Resolved 1 recipient + 1 CC from the local corpus',
      'Retrieved 2 few-shot examples from your Acme thread history',
      'Applied blurb: blunt-technical, directness high, no emoji',
      'Flagged a new binding commitment for first-recipient review',
    ],
    contacts: [danielContact, priyaContact],
    draft: SEED_DRAFT,
  },
]

/* ── Store ─────────────────────────────────────────────────────────── */

interface AppState {
  accounts: Account[]
  activeAccountId: string
  sessions: Session[]
  activeSessionId: string
  messages: ChatMessage[]
  sidebarCollapsed: boolean
  autoSend: boolean
  tweakHint: string

  setActiveAccount: (id: string) => void
  addAccount: (input: { name: string; email: string; provider: Provider }) => void
  createSession: () => void
  selectSession: (id: string) => void
  renameSession: (id: string, title: string) => void
  toggleSidebar: () => void
  setAutoSend: (value: boolean) => void
  setTweakHint: (value: string) => void
  appendMessage: (message: ChatMessage) => void
  updateDraft: (messageId: string, patch: Partial<EmailDraft>) => void
  markDraftSent: (messageId: string) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      accounts: SEED_ACCOUNTS,
      activeAccountId: SEED_ACCOUNTS[0]!.id,
      sessions: SEED_SESSIONS,
      activeSessionId: SEED_SESSIONS[0]!.id,
      messages: SEED_MESSAGES,
      sidebarCollapsed: false,
      autoSend: false,
      tweakHint: '',

      setActiveAccount: (id) => set({ activeAccountId: id }),

      addAccount: ({ name, email, provider }) => {
        const account: Account = {
          id: uid('acct'),
          name,
          email,
          provider,
          initials:
            name
              .split(/\s+/)
              .filter(Boolean)
              .slice(0, 2)
              .map((p) => p[0]!.toUpperCase())
              .join('') || '??',
          hue: 'from-[#D4F268] to-[#7C9B2E]',
        }
        set((s) => ({ accounts: [...s.accounts, account], activeAccountId: account.id }))
      },

      createSession: () => {
        const session: Session = {
          id: uid('sess'),
          title: 'New session',
          preview: 'Start typing to brief Proteus…',
          updatedAt: new Date().toISOString(),
          accountId: get().activeAccountId,
        }
        set((s) => ({
          sessions: [session, ...s.sessions],
          activeSessionId: session.id,
          messages: [
            {
              id: uid('msg'),
              role: 'assistant',
              content:
                "Fresh session. Tell me who you're writing to and what needs to land — I'll match your voice and flag anything that needs a second look.",
              createdAt: new Date().toISOString(),
              status: 'done',
            },
          ],
        }))
      },

      selectSession: (id) => {
        if (id === get().activeSessionId) return
        set({
          activeSessionId: id,
          messages: [
            {
              id: uid('msg'),
              role: 'assistant',
              content:
                "Loaded that thread's context. Give me the intent and I'll pick up where you left off.",
              createdAt: new Date().toISOString(),
              status: 'done',
            },
          ],
        })
      },

      renameSession: (id, title) =>
        set((s) => ({
          sessions: s.sessions.map((x) => (x.id === id ? { ...x, title } : x)),
        })),

      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setAutoSend: (value) => set({ autoSend: value }),
      setTweakHint: (value) => set({ tweakHint: value }),

      appendMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),

      updateDraft: (messageId, patch) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === messageId && m.draft ? { ...m, draft: { ...m.draft, ...patch } } : m,
          ),
        })),

      markDraftSent: (messageId) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === messageId && m.draft
              ? { ...m, draft: { ...m.draft, status: 'SENT' as const, warnings: [] } }
              : m,
          ),
        })),
    }),
    {
      name: 'proteus.workspace.v1',
      partialize: (s) => ({
        accounts: s.accounts,
        activeAccountId: s.activeAccountId,
        sessions: s.sessions,
        activeSessionId: s.activeSessionId,
        sidebarCollapsed: s.sidebarCollapsed,
        autoSend: s.autoSend,
      }),
    },
  ),
)

export const useActiveAccount = () =>
  useAppStore((s) => s.accounts.find((a) => a.id === s.activeAccountId) ?? s.accounts[0]!)
