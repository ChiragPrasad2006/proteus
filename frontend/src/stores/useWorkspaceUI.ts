import { create } from 'zustand'

export type MobileTab = 'chat' | 'draft' | 'sessions'

interface WorkspaceUIState {
  paletteOpen: boolean
  profileOpen: boolean
  shortcutsOpen: boolean
  /** Draft slide-over sheet for viewports < 1100px. */
  draftSheetOpen: boolean
  mobileTab: MobileTab
  autoSendConfirmOpen: boolean
  setPaletteOpen: (open: boolean) => void
  setProfileOpen: (open: boolean) => void
  setShortcutsOpen: (open: boolean) => void
  setDraftSheetOpen: (open: boolean) => void
  setMobileTab: (tab: MobileTab) => void
  setAutoSendConfirmOpen: (open: boolean) => void
  /** Close every overlay (Esc handling, account switch). */
  closeAll: () => void
}

export const useWorkspaceUI = create<WorkspaceUIState>((set) => ({
  paletteOpen: false,
  profileOpen: false,
  shortcutsOpen: false,
  draftSheetOpen: false,
  mobileTab: 'chat',
  autoSendConfirmOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setProfileOpen: (profileOpen) => set({ profileOpen }),
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
  setDraftSheetOpen: (draftSheetOpen) => set({ draftSheetOpen }),
  setMobileTab: (mobileTab) => set({ mobileTab }),
  setAutoSendConfirmOpen: (autoSendConfirmOpen) => set({ autoSendConfirmOpen }),
  closeAll: () => set({ paletteOpen: false, profileOpen: false, shortcutsOpen: false, draftSheetOpen: false, autoSendConfirmOpen: false }),
}))