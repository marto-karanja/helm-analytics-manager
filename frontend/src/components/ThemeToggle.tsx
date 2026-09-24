import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme, type ThemeMode } from '@/contexts/ThemeContext'
import { cn } from '@/lib/utils'

const options: { mode: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { mode: 'system', label: 'System', Icon: Monitor },
  { mode: 'light', label: 'Light', Icon: Sun },
  { mode: 'dark', label: 'Dark', Icon: Moon },
]

export function ThemeToggle({ className }: { className?: string }) {
  const { mode, setMode } = useTheme()

  return (
    <div role="group" aria-label="Theme" className={cn('inline-flex items-center gap-0.5', className)}>
      {options.map(({ mode: option, label, Icon }) => {
        const selected = mode === option
        return (
          <Button
            key={option}
            type="button"
            variant={selected ? 'outline' : 'ghost'}
            size="sm"
            aria-label={`${label} theme`}
            aria-pressed={selected}
            title={`${label} theme`}
            className={cn('w-8 px-0', selected ? 'border-foreground/40 bg-accent text-accent-foreground' : 'text-muted-foreground')}
            onClick={() => setMode(option)}
          >
            <Icon size={16} />
          </Button>
        )
      })}
    </div>
  )
}
