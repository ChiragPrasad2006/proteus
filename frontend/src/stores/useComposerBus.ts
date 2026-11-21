import { create } from 'zustand'

/**
 * Tiny bus for cross-component composer requests (suggestion chips, contact
 * pills, "Edit & resend", quick macros). The Composer consumes each request
 * exactly once via its nonce.
 */
interface ComposerRequest {
  text: string
  mode: 'replace' | 'append'
  nonce: number
}

interface ComposerBusState {
  request: ComposerRequest | null
  insert: (text: string, mode?: ComposerRequest['mode']) => void
  consume: (nonce: number) => void
}

export const useComposerBus = create<ComposerBusState>((set) => ({
  request: null,
  insert: (text, mode = 'replace') => set((state) => ({
    request: { text, mode, nonce: (state.request?.nonce ?? 0) + 1 },
  })),
  consume: (nonce) => set((state) => (state.request?.nonce === nonce ? { request: null } : {})),
}))