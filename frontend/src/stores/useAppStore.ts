import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Account, ChatMessage, EmailDraft, RecipientContact, Session } from '@/types'
import { api } from '@/lib/api'

interface AppState {
  accounts: Account[]
  activeAccountId: string | null
  sessions: Session[]
  activeSessionId: string | null
  messages: ChatMessage[]
  contacts: RecipientContact[]
  styleProfile: unknown | null
  pendingDrafts: unknown[]
  sidebarCollapsed: boolean
  autoSend: boolean
  tweakHint: string
  setAccounts: (accounts: Account[], activeAccountId: string | null) => void
  updateAccount: (account: Account) => void
  setActiveAccount: (id: string) => Promise<void>
  createSession: () => Promise<void>
  selectSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => void
  toggleSidebar: () => void
  setAutoSend: (value: boolean) => void
  setTweakHint: (value: string) => void
  appendMessage: (message: ChatMessage) => void
  updateDraft: (messageId: string, patch: Partial<EmailDraft>) => void
  markDraftSent: (messageId: string) => void
  setSessions: (sessions: Session[]) => void
  setMessages: (messages: ChatMessage[]) => void
  setContacts: (contacts: RecipientContact[]) => void
  setStyleProfile: (profile: unknown) => void
  setPendingDrafts: (drafts: unknown[]) => void
  clearAccountState: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      accounts: [], activeAccountId: null, sessions: [], activeSessionId: null, messages: [], contacts: [], styleProfile: null, pendingDrafts: [],
      sidebarCollapsed: false, autoSend: false, tweakHint: '',
      clearAccountState: () => set({ sessions: [], activeSessionId: null, messages: [], contacts: [], styleProfile: null, pendingDrafts: [] }),
      setAccounts: (accounts, activeAccountId) => set({ accounts, activeAccountId }),
      updateAccount: (account) => set((state) => ({
        accounts: state.accounts.map((item) => item.id === account.id ? account : item),
      })),
      setActiveAccount: async (id) => {
        if (!get().accounts.some((account) => account.id === id)) return
        get().clearAccountState()
        set({ activeAccountId: id })
        try {
          await api.switchAccount(id)
          const [sessionsResult, profileResult, contactsResult] = await Promise.allSettled([api.listSessions(id), api.profile(id), api.listContacts(id)])
          if (get().activeAccountId !== id) return
          if (sessionsResult.status === 'fulfilled') set({ sessions: sessionsResult.value.sessions, activeSessionId: sessionsResult.value.sessions[0]?.id ?? null })
          if (profileResult.status === 'fulfilled') set({ styleProfile: profileResult.value })
          if (contactsResult.status === 'fulfilled') set({ contacts: contactsResult.value.contacts ?? [] })
        } catch { /* State stays empty instead of retaining another account's data. */ }
      },
      createSession: async () => {
        const accountId = get().activeAccountId
        if (!accountId) return
        const session = await api.createSession({ title: 'New session' }, accountId)
        if (get().activeAccountId === accountId) set((state) => ({ sessions: [session, ...state.sessions], activeSessionId: session.id, messages: [] }))
      },
      selectSession: async (id) => {
        const accountId = get().activeAccountId
        if (!accountId || id === get().activeSessionId) return
        set({ activeSessionId: id, messages: [] })
        try {
          const detail = await api.getSession(id, accountId)
          if (get().activeAccountId === accountId && get().activeSessionId === id) set({ messages: detail.messages })
        } catch { if (get().activeAccountId === accountId && get().activeSessionId === id) set({ messages: [] }) }
      },
      renameSession: (id, title) => set((state) => ({ sessions: state.sessions.map((item) => item.id === id ? { ...item, title } : item) })),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setAutoSend: (autoSend) => set({ autoSend }), setTweakHint: (tweakHint) => set({ tweakHint }),
      appendMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
      updateDraft: (messageId, patch) => set((state) => ({ messages: state.messages.map((message) => message.id === messageId && message.draft ? { ...message, draft: { ...message.draft, ...patch } } : message) })),
      markDraftSent: (messageId) => set((state) => ({ messages: state.messages.map((message) => message.id === messageId && message.draft ? { ...message, draft: { ...message.draft, status: 'SENT', warnings: [] } } : message) })),
      setSessions: (sessions) => set({ sessions }), setMessages: (messages) => set({ messages }), setContacts: (contacts) => set({ contacts }),
      setStyleProfile: (styleProfile) => set({ styleProfile }), setPendingDrafts: (pendingDrafts) => set({ pendingDrafts }),
    }),
    { name: 'proteus.workspace.v1', partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed, autoSend: state.autoSend }) },
  ),
)

export const useActiveAccount = () => useAppStore((state) => state.activeAccountId ? state.accounts.find((account) => account.id === state.activeAccountId) ?? null : null)
