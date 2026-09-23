import { useState } from 'react'
import { Cast, Copy, Check, Radio, Square, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { CATEGORIES } from '@/lib/categories'
import { DemoBanner } from '@/components/ui'

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-ink-muted">{label}</p>
      <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-4 py-3">
        <code className="flex-1 truncate text-left text-sm">{value}</code>
        <button
          type="button"
          onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
          className="text-ink-muted hover:text-ink"
          aria-label={`Copier ${label}`}
        >
          {copied ? <Check size={16} /> : <Copy size={16} />}
        </button>
      </div>
    </div>
  )
}

export function GoLivePage() {
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('entertainment')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ id: string; stream_key: string; rtmpUrl: string; hlsUrl: string; watchUrl: string } | null>(null)
  const [isLive, setIsLive] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.createStream({ title, category, description })
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de créer le direct pour l'instant.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleToggleLive() {
    if (!result) return
    setToggling(true)
    try {
      if (isLive) {
        await api.stopStream(result.id)
        setIsLive(false)
      } else {
        await api.startStream(result.id)
        setIsLive(true)
      }
    } catch {
      setError("Impossible de mettre à jour l'état du direct.")
    } finally {
      setToggling(false)
    }
  }

  if (result) {
    return (
      <div className="mx-auto max-w-lg">
        <div className="card p-7">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Cast size={26} />
          </div>
          <h1 className="text-center font-display text-xl font-semibold">Votre direct est prêt</h1>
          <p className="mt-1.5 text-center text-sm text-ink-muted">
            Configurez votre logiciel de diffusion (OBS, Streamlabs…) avec les informations
            ci-dessous, puis lancez la diffusion avant de cliquer sur « Je suis en direct ».
          </p>

          <div className="mt-5 space-y-3">
            <CopyField label="URL du serveur (RTMP)" value={result.rtmpUrl} />
            <CopyField label="Clé de diffusion" value={result.stream_key} />
          </div>

          {error && <p className="mt-3 text-sm text-accent">{error}</p>}

          <button
            type="button"
            onClick={handleToggleLive}
            disabled={toggling}
            className={`mt-5 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60 ${
              isLive ? 'bg-ink-muted' : 'bg-accent'
            }`}
          >
            {isLive ? <Square size={16} /> : <Radio size={16} />}
            {toggling ? 'Mise à jour…' : isLive ? 'Arrêter le direct' : 'Je suis en direct'}
          </button>

          {isLive && (
            <Link
              to={result.watchUrl}
              className="mt-3 flex items-center justify-center gap-1.5 text-sm font-medium text-accent-2 hover:underline"
            >
              <ExternalLink size={14} /> Voir la page de mon direct
            </Link>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-lg">
      <DemoBanner />
      <h1 className="mb-1 font-display text-2xl font-semibold">Démarrer un direct</h1>
      <p className="mb-6 text-sm text-ink-muted">Configurez votre diffusion avant de la lancer.</p>

      <form onSubmit={handleSubmit} className="card space-y-5 p-6">
        <div>
          <label htmlFor="title" className="mb-1.5 block text-sm font-medium">Titre du direct</label>
          <input
            id="title" required value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Ex : Match amical en direct"
            className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none focus-visible:border-accent-2"
          />
        </div>

        <div>
          <label htmlFor="category" className="mb-1.5 block text-sm font-medium">Catégorie</label>
          <select
            id="category" value={category} onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none focus-visible:border-accent-2"
          >
            {CATEGORIES.filter((c) => !c.id.startsWith('iptv')).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="description" className="mb-1.5 block text-sm font-medium">Description (optionnel)</label>
          <textarea
            id="description" value={description} onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full resize-none rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none focus-visible:border-accent-2"
          />
        </div>

        {error && <p className="text-sm text-accent">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          <Cast size={16} /> {submitting ? 'Création…' : 'Générer ma clé de diffusion'}
        </button>
      </form>
    </div>
  )
}
