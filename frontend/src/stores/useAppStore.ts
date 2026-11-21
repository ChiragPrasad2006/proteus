import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Account, ChatMessage, RecipientContact, Session, UserStyleProfile } from '@/types'
import { api } from '@/lib/api'
import { useDraftState } from '@/hooks/useDraftState'
import { useComposerBus } from '@/stores/useComposerBus'
import { useToastStore } from '@/stores/useToastStore'
import { useWorkspaceUI } from '@/stores/useWorkspaceUI'

interface AppState {
  accounts: Account[]
  activeAccountId: string | null
  sessions: Session[]
  activeSessionId: string | null
  messages: ChatMessage[]
  contacts: RecipientContact[]
  styleProfile: UserStyleProfile | null
  sidebarCollapsed: boolean
  autoSend: boolean
  setAccounts: (accounts: Account[], activeAccountId: string | null) => void
  updateAccount: (account: Account) => void
  setActiveAccount: (id: string) => Promise<void>
  createSession: () => Promise<string | null>
  selectSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>
  /** Apply a backend-auto-summarized title locally (no PATCH — keeps auto-titles alive). */
  applySessionTitle: (id: string, title: string) => void
  /** Bump a session's activity timestamp/preview after a turn. */
  touchSession: (id: string, preview?: string) => void
  deleteSession: (id: string) => Promise<void>
  toggleSidebar: () => void
  setAutoSend: (value: boolean) => void
  appendMessage: (message: ChatMessage) => void
  setSessions: (sessions: Session[]) => void
  setMessages: (messages: ChatMessage[]) => void
  setContacts: (contacts: RecipientContact[]) => void
  setStyleProfile: (profile: UserStyleProfile | null) => void
  clearAccountState: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      accounts: [], activeAccountId: null, sessions: [], activeSessionId: null, messages: [], contacts: [], styleProfile: null,
      sidebarCollapsed: false, autoSend: false,
      clearAccountState: () => {
        // Strict isolation: wipe sessions, drafts, contacts, toasts and overlays.
        useDraftState.getState().reset()
        useToastStore.getState().clear()
        useWorkspaceUI.getState().closeAll()
        useComposerBus.setState({ request: null })
        set({ sessions: [], activeSessionId: null, messages: [], contacts: [], styleProfile: null })
      },
      setAccounts: (accounts, activeAccountId) => set({ accounts, activeAccountId }),
      updateAccount: (account) => set((state) => ({
        accounts: state.accounts.map((item) => item.id === account.id ? account : item),
      })),
      setActiveAccount: async (id) => {
        if (!get().accounts.some((account) => account.id === id)) return
        const selectedAccount = get().accounts.find((account) => account.id === id)
        get().clearAccountState()
        set({ activeAccountId: id })
        try {
          await api.switchAccount(id)
          const [sessionsResult, profileResult, contactsResult] = await Promise.allSettled([
            api.listSessions(id),
            selectedAccount?.mailboxConnected ? api.profile(id) : Promise.resolve(null),
            api.listContacts(id),
          ])
          if (get().activeAccountId !== id) return
          if (sessionsResult.status === 'fulfilled') set({ sessions: sessionsResult.value.sessions, activeSessionId: sessionsResult.value.sessions[0]?.id ?? null })
          if (profileResult.status === 'fulfilled') set({ styleProfile: profileResult.value })
          if (contactsResult.status === 'fulfilled') set({ contacts: contactsResult.value.contacts ?? [] })
          const firstSessionId = sessionsResult.status === 'fulfilled' ? sessionsResult.value.sessions[0]?.id : undefined
          if (firstSessionId) {
            const detail = await api.getSession(firstSessionId, id)
            if (get().activeAccountId === id && get().activeSessionId === firstSessionId) {
              set({ messages: detail.messages })
              useDraftState.getState().hydrate(detail.drafts, firstSessionId, id)
              const latest = Object.values(useDraftState.getState().drafts)
                .filter((draft) => draft.sessionId === firstSessionId)
                .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]
              if (latest) useDraftState.getState().select(latest.id)
            }
          }
        } catch { /* State stays empty instead of retaining another account's data. */ }
      },
      createSession: async () => {
        const accountId = get().activeAccountId
        if (!accountId) return null
        const session = await api.createSession({ title: '' }, accountId)
        if (get().activeAccountId !== accountId) return null
        set((state) => ({ sessions: [session, ...state.sessions], activeSessionId: session.id, messages: [] }))
        return session.id
      },
      selectSession: async (id) => {
        const accountId = get().activeAccountId
        if (!accountId || id === get().activeSessionId) return
        set({ activeSessionId: id, messages: [] })
        useDraftState.getState().select(null)
        try {
          const detail = await api.getSession(id, accountId)
          if (get().activeAccountId === accountId && get().activeSessionId === id) {
            set({ messages: detail.messages })
            useDraftState.getState().hydrate(detail.drafts, id, accountId)
            const latest = Object.values(useDraftState.getState().drafts)
              .filter((draft) => draft.sessionId === id)
              .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]
            if (latest) useDraftState.getState().select(latest.id)
          }
        } catch { if (get().activeAccountId === accountId && get().activeSessionId === id) set({ messages: [] }) }
      },
      renameSession: async (id, title) => {
        const accountId = get().activeAccountId
        if (!accountId) return
        const updated = await api.renameSession(id, title, accountId)
        if (get().activeAccountId !== accountId) return
        set((state) => ({ sessions: state.sessions.map((item) => item.id === id ? { ...item, ...updated, isCustomTitle: true } : item) }))
      },
      applySessionTitle: (id, title) => set((state) => ({
        sessions: state.sessions.map((item) => item.id === id && !item.isCustomTitle ? { ...item, title } : item),
      })),
      touchSession: (id, preview) => set((state) => ({
        sessions: state.sessions.map((item) => item.id === id
          ? { ...item, updatedAt: new Date().toISOString(), preview: preview ?? item.preview }
          : item),
      })),
      deleteSession: async (id) => {
        const accountId = get().activeAccountId
        if (!accountId) return
        await api.deleteSession(id, accountId)
        if (get().activeAccountId !== accountId) return
        set((state) => {
          const sessions = state.sessions.filter((item) => item.id !== id)
          const activeSessionId = state.activeSessionId === id ? (sessions[0]?.id ?? null) : state.activeSessionId
          return { sessions, activeSessionId, messages: state.activeSessionId === id ? [] : state.messages }
        })
      },
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setAutoSend: (autoSend) => set({ autoSend }),
      appendMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
      setSessions: (sessions) => set({ sessions }), setMessages: (messages) => set({ messages }), setContacts: (contacts) => set({ contacts }),
      setStyleProfile: (styleProfile) => set({ styleProfile }),
    }),
    { name: 'proteus.workspace.v1', partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed, autoSend: state.autoSend }) },
  ),
)

export const useActiveAccount = () => useAppStore((state) => state.activeAccountId ? state.accounts.find((account) => account.id === state.activeAccountId) ?? null : null)
