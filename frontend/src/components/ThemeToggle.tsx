import { Moon, Sun, Monitor } from 'lucide-react'
import { useTheme, type ThemeMode } from '@/context/ThemeContext'

const OPTIONS: { mode: ThemeMode; icon: typeof Sun; label: string }[] = [
  { mode: 'light', icon: Sun, label: 'Clair' },
  { mode: 'dark', icon: Moon, label: 'Sombre' },
  { mode: 'system', icon: Monitor, label: 'Système' },
]

export function ThemeToggle() {
  const { mode, setMode } = useTheme()
  return (
    <div className="flex items-center rounded-full border border-border bg-surface p-1">
      {OPTIONS.map(({ mode: m, icon: Icon, label }) => (
        <button
          key={m}
          type="button"
          aria-label={label}
          aria-pressed={mode === m}
          onClick={() => setMode(m)}
          className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
            mode === m ? 'bg-accent-2 text-white' : 'text-ink-muted hover:text-ink'
          }`}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  )
}
