import { Eye, EyeOff } from 'lucide-react'
import * as React from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { login, signInErrorMessage } from '@/lib/api'

/** Only follow in-app paths, so a crafted link cannot send a signed-in user to another site. */
function safeDestination(from: unknown): string {
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') && !from.startsWith('/login') ? from : '/'
}

export function LoginPage() {
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [showPassword, setShowPassword] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)
  const { setToken, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const destination = safeDestination((location.state as { from?: unknown } | null)?.from)

  // Already signed in (for instance a bookmarked /login): go straight in.
  if (isAuthenticated && !pending) return <Navigate to={destination} replace />

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (pending) return
    setError(null)
    setPending(true)
    try {
      const token = await login(email.trim(), password)
      setToken(token)
      navigate(destination, { replace: true })
    } catch (err) {
      setError(signInErrorMessage(err, 'Invalid email or password.'))
      setPending(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-2">
      <BrandPanel />
      <main className="flex items-center justify-center p-4 sm:p-8">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <Logo size={40} tagline className="mb-2 lg:hidden" />
            <h1 className="sr-only">Sign in to Helm Analytics Manager</h1>
            <CardDescription>Sign in to view your portfolio.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? 'login-error' : undefined}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? 'login-error' : undefined}
                    className="pr-10"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    className="absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-md text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
                  </button>
                </div>
              </div>
              <div id="login-error" role="alert" aria-live="assertive">
                {error && <p className="text-sm text-destructive">{error}</p>}
              </div>
              <Button type="submit" disabled={pending}>
                {pending ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
            <div className="mt-4 flex justify-center">
              <ThemeToggle />
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}

/** The brand side of the login screen: gradient, tagline and an abstract chart. Hidden on small screens. */
function BrandPanel() {
  return (
    <div
      aria-hidden
      className="relative hidden overflow-hidden bg-gradient-to-br from-[#4338ca] via-[#3b4cc0] to-[#0d6f66] p-10 text-white lg:flex lg:flex-col lg:justify-between"
    >
      <Logo size={44} className="text-white" />
      <div className="relative z-10 max-w-md">
        <p className="text-3xl font-semibold leading-tight tracking-tight">See what search is doing to every site you run</p>
        <p className="mt-3 text-sm text-white">Traffic, indexing, keywords and publishing queues in one place.</p>
      </div>
      <svg viewBox="0 0 520 300" className="pointer-events-none absolute inset-x-0 bottom-0 h-72 w-full opacity-30" preserveAspectRatio="none">
        <defs>
          <linearGradient id="login-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fff" stopOpacity="0.45" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M0 240 L60 215 L120 225 L180 170 L240 185 L300 120 L360 140 L420 70 L520 30 L520 300 L0 300Z" fill="url(#login-fill)" />
        <path d="M0 240 L60 215 L120 225 L180 170 L240 185 L300 120 L360 140 L420 70 L520 30" fill="none" stroke="#fff" strokeWidth="3" strokeLinejoin="round" />
      </svg>
    </div>
  )
}
