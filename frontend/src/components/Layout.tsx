import { LayoutGrid, ListChecks, LogOut } from 'lucide-react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'

export function Layout() {
  const { setToken, isDemo } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    setToken(null)
    navigate('/login')
  }

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
    }`

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2 text-sm font-semibold">
            Helm Analytics Manager
            {isDemo && <Badge variant="outline">Demo mode — read-only</Badge>}
          </span>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navLinkClass}>
              <LayoutGrid size={16} /> Overview
            </NavLink>
            <NavLink to="/tasks" className={navLinkClass}>
              <ListChecks size={16} /> Tasks
            </NavLink>
            <ThemeToggle className="mx-1" />
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              <LogOut size={16} /> Log out
            </Button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
