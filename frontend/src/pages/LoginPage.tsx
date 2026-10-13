import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { demoLogin, login } from '@/lib/api'

export function LoginPage() {
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [demoLoading, setDemoLoading] = React.useState(false)
  const { setToken } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const token = await login(email, password)
      setToken(token)
      navigate('/')
    } catch {
      setError('Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  async function handleDemoLogin() {
    setError(null)
    setDemoLoading(true)
    try {
      const token = await demoLogin()
      setToken(token)
      navigate('/')
    } catch {
      setError('Could not start the demo session.')
    } finally {
      setDemoLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-2">
      <BrandPanel />
      <div className="flex items-center justify-center p-4 sm:p-8">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <Logo size={40} tagline className="mb-2 lg:hidden" />
            <CardTitle className="sr-only">Helm Analytics Manager</CardTitle>
            <CardDescription>Sign in to view your portfolio.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" disabled={loading}>
                {loading ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
            <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
              <div className="h-px flex-1 bg-border" />
              or
              <div className="h-px flex-1 bg-border" />
            </div>
            <Button type="button" variant="outline" className="mt-4 w-full" disabled={demoLoading} onClick={handleDemoLogin}>
              {demoLoading ? 'Starting demo…' : 'Log in as Demo'}
            </Button>
            <p className="mt-2 text-center text-xs text-muted-foreground">The demo is read-only and uses sample data.</p>
            <div className="mt-4 flex justify-center">
              <ThemeToggle />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/** The brand side of the login screen: gradient, tagline and an abstract chart. Hidden on small screens. */
function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden bg-gradient-to-br from-[#4f46e5] via-[#4f58d8] to-[#0f9d8f] p-10 text-white lg:flex lg:flex-col lg:justify-between">
      <Logo size={44} className="text-white" />
      <div className="relative z-10 max-w-md">
        <h2 className="text-3xl font-semibold leading-tight tracking-tight">See what search is doing to every site you run</h2>
        <p className="mt-3 text-sm text-white/85">Traffic, indexing, keywords and publishing queues in one place.</p>
      </div>
      <svg aria-hidden viewBox="0 0 520 300" className="pointer-events-none absolute inset-x-0 bottom-0 h-72 w-full opacity-40" preserveAspectRatio="none">
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
