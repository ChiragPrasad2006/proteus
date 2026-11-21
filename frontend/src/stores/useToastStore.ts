import { create } from 'zustand'
import { uid } from '@/lib/utils'

export interface Toast {
  id: string
  message: string
  tone: 'neutral' | 'success' | 'warning'
  actionLabel?: string
  onAction?: () => void
  /** 0 = sticky until dismissed. */
  durationMs: number
}

interface ToastState {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id'>) => string
  dismiss: (id: string) => void
  clear: () => void
}

const timers = new Map<string, ReturnType<typeof setTimeout>>()

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (toast) => {
    const id = uid('toast')
    set((state) => ({ toasts: [...state.toasts.slice(-3), { ...toast, id }] }))
    if (toast.durationMs > 0) {
      timers.set(id, setTimeout(() => get().dismiss(id), toast.durationMs))
    }
    return id
  },
  dismiss: (id) => {
    const timer = timers.get(id)
    if (timer) { clearTimeout(timer); timers.delete(id) }
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }))
  },
  clear: () => {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    set({ toasts: [] })
  },
}))

/** Convenience helper for the common auto-dismissing case. */
export function toast(message: string, tone: Toast['tone'] = 'neutral', durationMs = 4200): string {
  return useToastStore.getState().push({ message, tone, durationMs })
}