import { useState } from 'react'
import { ShieldCheck, LogIn } from 'lucide-react'
import { api } from '@/api/client'

export function AdminLoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const ok = await api.adminLogin(username, password)
      if (ok) {
        onSuccess()
      } else {
        setError('Identifiants incorrects.')
      }
    } catch {
      setError("Impossible de contacter le serveur. Réessayez.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center">
      <div className="card p-7">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-2-soft text-accent-2">
          <ShieldCheck size={22} />
        </div>
        <h1 className="mb-1 text-center font-display text-xl font-semibold">Espace admin</h1>
        <p className="mb-6 text-center text-sm text-ink-muted">Connectez-vous pour accéder au tableau de bord.</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="mb-1.5 block text-sm font-medium">Identifiant ou email</label>
            <input
              id="username" required autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none focus-visible:border-accent-2"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium">Mot de passe</label>
            <input
              id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none focus-visible:border-accent-2"
            />
          </div>

          {error && <p className="text-sm text-accent">{error}</p>}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent-2 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            <LogIn size={16} /> {submitting ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </div>
    </div>
  )
}
