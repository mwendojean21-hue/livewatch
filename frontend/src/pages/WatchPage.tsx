import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Heart, Flag, Send, Eye } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { getCategory } from '@/lib/categories'
import { VideoPlayer } from '@/components/VideoPlayer'
import { LiveBadge, DemoBanner, SectionHeading, Skeleton } from '@/components/ui'
import { StreamCard } from '@/components/StreamCard'

export function WatchPage() {
  const { streamId } = useParams<{ streamId: string }>()
  const id = streamId ?? ''

  const { data: all, loading } = useAsync(() => api.catalog(undefined, 100), [])
  const stream = all?.find((s) => s.id === id) ?? all?.[0]

  const { data: comments } = useAsync(() => api.comments(id), [id])
  const [liked, setLiked] = useState(false)
  const [likeCount, setLikeCount] = useState<number | null>(null)
  const [comment, setComment] = useState('')

  async function handleLike() {
    setLiked((v) => !v)
    try {
      const res = await api.likeStream(id)
      setLikeCount(res.like_count)
    } catch {
      /* pas grave en mode démo */
    }
  }

  if (loading) {
    return <div className="mx-auto max-w-5xl"><Skeleton className="aspect-video w-full" /></div>
  }
  if (!stream) {
    return <div className="mx-auto max-w-5xl card p-10 text-center text-ink-muted">Chaîne introuvable.</div>
  }

  const cat = getCategory(stream.category)

  return (
    <div className="mx-auto max-w-5xl">
      <DemoBanner />
      <VideoPlayer
        src={stream.stream_type === 'youtube' ? `https://www.youtube.com/embed/${stream.id}?autoplay=1` : `/proxy/stream?id=${stream.id}`}
        type={stream.stream_type}
        title={stream.title}
      />

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <LiveBadge />
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cat.chip} ${cat.ink}`}>{cat.name}</span>
          </div>
          <h1 className="font-display text-xl font-semibold sm:text-2xl">{stream.title}</h1>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-muted">
            <Eye size={14} /> {(stream.viewers ?? 0).toLocaleString('fr-FR')} spectateurs · {stream.country}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleLike}
            className={`flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              liked ? 'border-accent bg-accent/10 text-accent' : 'border-border text-ink-muted hover:text-ink'
            }`}
          >
            <Heart size={15} fill={liked ? 'currentColor' : 'none'} />
            {likeCount ?? "J'aime"}
          </button>
          <button
            type="button"
            onClick={() => api.reportStream(id, 'contenu inapproprié').catch(() => {})}
            className="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink"
          >
            <Flag size={15} /> Signaler
          </button>
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_320px]">
        <div>
          <SectionHeading title="Commentaires" />
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (!comment.trim()) return
              api.postComment(id, comment).catch(() => {})
              setComment('')
            }}
            className="mb-4 flex items-center gap-2"
          >
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Ajouter un commentaire…"
              className="flex-1 rounded-full border border-border bg-surface px-4 py-2.5 text-sm outline-none focus-visible:border-accent-2"
            />
            <button type="submit" aria-label="Envoyer" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-2 text-white">
              <Send size={15} />
            </button>
          </form>
          <div className="space-y-3">
            {comments?.map((c) => (
              <div key={c.id} className="card p-3.5 text-sm">
                <p>{c.content}</p>
                <p className="mt-1 text-xs text-ink-muted">{new Date(c.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <SectionHeading title="Chaînes similaires" />
          <div className="grid gap-3">
            {all?.filter((s) => s.id !== id && s.category === stream.category).slice(0, 4).map((s) => (
              <StreamCard key={s.id} stream={s} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
