import { ApiError, api } from '@/lib/api'

/** Starts the identity OAuth flow; returns false only for an explicit missing-config response. */
export async function startGoogleSignIn(): Promise<boolean> {
  try {
    const result = await api.googleAuthStart()
    const authUrl = result?.auth_url || (result as unknown as { url?: string })?.url
    if (!authUrl) {
      throw new Error('Backend did not return an authorization URL.')
    }
    window.location.href = authUrl
    return true
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.message === 'MISSING_OAUTH_CONFIG' ||
       error.message.includes('not configured'))
    ) {
      return false
    }
    throw error
  }
}
