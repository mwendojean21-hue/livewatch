import { useState } from 'react'
import { Check } from 'lucide-react'
import { useTheme } from '@/context/ThemeContext'
import { api } from '@/api/client'
import { ThemeToggle } from '@/components/ThemeToggle'
import { DemoBanner } from '@/components/ui'

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-3.5">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        {hint && <span className="block text-xs text-ink-muted">{hint}</span>}
      </span>
      <span
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? 'bg-accent-2' : 'bg-surface-2'}`}
      >
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </span>
    </label>
  )
}

export function SettingsPage() {
  const { mode } = useTheme()
  const [language, setLanguage] = useState('fr')
  const [autoplay, setAutoplay] = useState(true)
  const [notifications, setNotifications] = useState(true)
  const [dataSaver, setDataSaver] = useState(false)
  const [saved, setSaved] = useState(false)

  async function handleSave() {
    try {
      await api.saveSettings({ theme: mode, language, autoplay, notifications, dataSaver })
    } catch {
      /* ok en mode démo */
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return (
    <div className="mx-auto max-w-2xl">
      <DemoBanner />
      <h1 className="mb-6 font-display text-2xl font-semibold">Paramètres</h1>

      <section className="card mb-5 p-5">
        <h2 className="mb-3 text-sm font-semibold text-ink-muted">Apparence</h2>
        <div className="flex items-center justify-between py-2">
          <span className="text-sm font-medium">Thème</span>
          <ThemeToggle />
        </div>
      </section>

      <section className="card mb-5 p-5">
        <h2 className="mb-1 text-sm font-semibold text-ink-muted">Lecture</h2>
        <div className="divide-y divide-border">
          <Toggle checked={autoplay} onChange={setAutoplay} label="Lecture automatique" hint="Démarrer le direct dès l'ouverture de la page" />
          <Toggle checked={dataSaver} onChange={setDataSaver} label="Économie de données" hint="Réduire la qualité par défaut sur réseau mobile" />
        </div>
      </section>

      <section className="card mb-5 p-5">
        <h2 className="mb-1 text-sm font-semibold text-ink-muted">Général</h2>
        <div className="flex items-center justify-between py-3.5">
          <span className="text-sm font-medium">Langue</span>
          <select
            value={language} onChange={(e) => setLanguage(e.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm outline-none"
          >
            <option value="fr">Français</option>
            <option value="en">English</option>
            <option value="sw">Kiswahili</option>
            <option value="ln">Lingala</option>
          </select>
        </div>
        <div className="divide-y divide-border border-t border-border">
          <Toggle checked={notifications} onChange={setNotifications} label="Notifications" hint="Événements et directs à venir" />
        </div>
      </section>

      <button
        type="button"
        onClick={handleSave}
        className="flex items-center gap-2 rounded-xl bg-accent-2 px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
      >
        {saved ? <Check size={16} /> : null} {saved ? 'Enregistré' : 'Enregistrer'}
      </button>
    </div>
  )
}
