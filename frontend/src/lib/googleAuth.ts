import { api } from '@/lib/api'

/** Starts OAuth when configured; returns false so callers can open quick setup. */
export async function startGoogleSignIn(): Promise<boolean> {
  const status = await api.googleAuthStatus()
  if (!status.configured) return false
  const { auth_url } = await api.googleAuthStart()
  window.location.assign(auth_url)
  return true
}
