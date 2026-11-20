import { ApiError, api } from '@/lib/api'

/** Starts the identity OAuth flow; returns false only for an explicit missing-config response. */
export async function startGoogleSignIn(): Promise<boolean> {
  try {
    const { auth_url } = await api.googleAuthStart()
    window.location.href = auth_url
    return true
  } catch (error) {
    if (error instanceof ApiError && error.message === 'MISSING_OAUTH_CONFIG') return false
    throw error
  }
}
