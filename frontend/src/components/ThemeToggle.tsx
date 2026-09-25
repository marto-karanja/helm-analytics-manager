import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme, type ThemeMode } from '@/contexts/ThemeContext'
import { cn } from '@/lib/utils'

const CYCLE: { mode: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { mode: 'system', label: 'System', Icon: Monitor },
  { mode: 'light', label: 'Light', Icon: Sun },
  { mode: 'dark', label: 'Dark', Icon: Moon },
]

export function ThemeToggle({ className }: { className?: string }) {
  const { mode, setMode } = useTheme()
  const index = CYCLE.findIndex((option) => option.mode === mode)
  const current = CYCLE[index]
  const next = CYCLE[(index + 1) % CYCLE.length]

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={`Theme: ${current.label}. Switch to ${next.label}`}
      title={`Theme: ${current.label} (click for ${next.label})`}
      className={cn('w-[5.5rem] text-muted-foreground', className)}
      onClick={() => setMode(next.mode)}
    >
      <current.Icon size={16} />
      {current.label}
    </Button>
  )
}
