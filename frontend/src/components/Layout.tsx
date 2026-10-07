import { FileText, LayoutGrid, LineChart, ListChecks, LogOut, Settings } from 'lucide-react'
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
    `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors sm:px-3 ${
      isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
    }`

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <span className="flex items-center gap-2 text-sm font-semibold">
            Helm Analytics Manager
            {isDemo && <Badge variant="outline">Demo mode — read-only</Badge>}
          </span>
          <nav className="flex shrink-0 items-center gap-0.5 sm:gap-1">
            <NavLink to="/" end title="Overview" aria-label="Overview" className={navLinkClass}>
              <LayoutGrid size={16} /> <span className="hidden sm:inline">Overview</span>
            </NavLink>
            <NavLink to="/traffic" title="Traffic" aria-label="Traffic" className={navLinkClass}>
              <LineChart size={16} /> <span className="hidden sm:inline">Traffic</span>
            </NavLink>
            <NavLink to="/tasks" title="Tasks" aria-label="Tasks" className={navLinkClass}>
              <ListChecks size={16} /> <span className="hidden sm:inline">Tasks</span>
            </NavLink>
            <NavLink to="/reports" title="Reports" aria-label="Reports" className={navLinkClass}>
              <FileText size={16} /> <span className="hidden sm:inline">Reports</span>
            </NavLink>
            <NavLink to="/settings" title="Settings" aria-label="Settings" className={navLinkClass}>
              <Settings size={16} /> <span className="hidden sm:inline">Settings</span>
            </NavLink>
            <ThemeToggle className="mx-1" />
            <Button variant="ghost" size="sm" aria-label="Log out" onClick={handleLogout}>
              <LogOut size={16} /> <span className="hidden sm:inline">Log out</span>
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
