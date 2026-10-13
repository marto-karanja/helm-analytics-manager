import * as React from 'react'
import { fetchMe, TOKEN_STORAGE_KEY, UNAUTHORIZED_EVENT } from '@/lib/api'

interface AuthContextValue {
  token: string | null
  setToken: (token: string | null) => void
  isAuthenticated: boolean
  isDemo: boolean
}

const AuthContext = React.createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = React.useState<string | null>(() =>
    localStorage.getItem(TOKEN_STORAGE_KEY),
  )
  const [isDemo, setIsDemo] = React.useState(false)

  React.useEffect(() => {
    if (!token) {
      setIsDemo(false)
      return
    }
    fetchMe()
      .then((me) => setIsDemo(me.is_demo))
      .catch(() => setIsDemo(false))
  }, [token])

  // The server rejected our token (expired or revoked): drop it so the route guard sends us to the sign-in page.
  React.useEffect(() => {
    const onUnauthorized = () => {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      setTokenState(null)
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const setToken = React.useCallback((next: string | null) => {
    if (next) {
      localStorage.setItem(TOKEN_STORAGE_KEY, next)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
    setTokenState(next)
  }, [])

  const value = React.useMemo(
    () => ({ token, setToken, isAuthenticated: token !== null, isDemo }),
    [token, setToken, isDemo],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
