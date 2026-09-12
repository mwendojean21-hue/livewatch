import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { AlertTriangle } from 'lucide-react'

interface Props {
  src: string
  type?: string
  poster?: string
  title: string
}

export function VideoPlayer({ src, type = 'hls', poster, title }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    if (type === 'youtube' || type === 'iframe' || type === 'audio') return
    const video = videoRef.current
    if (!video) return

    // Muet obligatoire : les navigateurs bloquent silencieusement l'autoplay
    // avec le son (aucune erreur JS, aucune ligne dans les logs réseau — le
    // flux se charge très bien côté serveur, la vidéo reste juste figée sur
    // une image noire). C'est très probablement la cause de "ça ne montre
    // rien" alors que les requêtes /proxy/stream et /proxy/segment
    // réussissaient déjà côté backend. L'utilisateur peut réactiver le son
    // avec les contrôles natifs juste après.
    video.muted = true

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari lit le HLS nativement
      video.src = src
      video.play().catch(() => { /* ignoré : lecture au clic si bloquée malgré le mute */ })
      return
    }
    if (Hls.isSupported()) {
      const hls = new Hls()
      hls.loadSource(src)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => { /* ignoré : lecture au clic si bloquée malgré le mute */ })
      })
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data.fatal) setError("Impossible de charger ce flux pour le moment.")
      })
      return () => hls.destroy()
    }
    setError('Votre navigateur ne supporte pas la lecture de ce flux.')
  }, [src, type])

  if (type === 'youtube' || type === 'iframe') {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
        <iframe
          src={src}
          title={title}
          allow="autoplay; encrypted-media; picture-in-picture"
          allowFullScreen
          className="h-full w-full border-0"
        />
      </div>
    )
  }

  if (type === 'audio') {
    return (
      <div className="flex aspect-video w-full flex-col items-center justify-center gap-4 rounded-2xl bg-black text-white">
        <span className="text-sm text-white/70">{title}</span>
        {/* Pas d'autoPlay ici : un <audio> avec son est bloqué par les
            navigateurs comme la vidéo, mais contrairement à la vidéo il n'y
            a pas d'image "figée" trompeuse — les contrôles restent visibles
            et cliquables, donc pas besoin de couper le son pour démarrer. */}
        <audio src={src} controls className="w-11/12 max-w-md" />
      </div>
    )
  }

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black">
      {error ? (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-6 text-center text-white/80">
          <AlertTriangle size={26} />
          <p className="text-sm">{error}</p>
        </div>
      ) : (
        <video
          ref={videoRef}
          poster={poster}
          controls
          autoPlay
          muted
          playsInline
          className="h-full w-full"
        />
      )}
    </div>
  )
}
