import { ApiError, api } from '@/lib/api'

export type OAuthProvider = 'gmail' | 'outlook' | 'zoho'

const MISSING_CONFIG_CODES = new Set([
  'MISSING_OAUTH_CONFIG',
  'MISSING_OUTLOOK_OAUTH_CONFIG',
  'MISSING_ZOHO_OAUTH_CONFIG',
])

/** Starts OAuth for the chosen provider; returns false only when local OAuth config is missing. */
export async function startProviderSignIn(provider: OAuthProvider): Promise<boolean> {
  try {
    const result =
      provider === 'outlook'
        ? await api.outlookAuthStart()
        : provider === 'zoho'
          ? await api.zohoAuthStart()
          : await api.googleAuthStart()
    const authUrl = result?.auth_url || (result as unknown as { url?: string })?.url
    if (!authUrl) {
      throw new Error('Backend did not return an authorization URL.')
    }
    window.location.href = authUrl
    return true
  } catch (error) {
    if (
      error instanceof ApiError &&
      (MISSING_CONFIG_CODES.has(error.message) || error.message.includes('not configured'))
    ) {
      return false
    }
    throw error
  }
}

/** Starts the Google identity OAuth flow; returns false only for an explicit missing-config response. */
export async function startGoogleSignIn(): Promise<boolean> {
  return startProviderSignIn('gmail')
}
