import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { AlertTriangle } from 'lucide-react'

interface Props {
  /** URL passée par /proxy/stream — le chemin qui marche presque toujours
   * (CORS/referer gérés côté serveur), utilisé en 2ᵉ position. */
  src: string
  /** URL brute de la source (sans passer par le proxy) — certaines sources
   * autorisent le CORS directement, auquel cas on évite de charger notre
   * propre proxy inutilement. Utilisée en 1ère position, et en dernier
   * recours (niveaux 4 et 5). Absente pour youtube/iframe/audio. */
  directUrl?: string
  type?: string
  poster?: string
  title: string
}

/** Charge dash.js à la demande depuis le même CDN que l'ancienne version
 * (dashjs n'est volontairement pas ajouté aux dépendances npm : ça évite
 * d'alourdir le bundle pour un format utilisé par une minorité de chaînes,
 * et cette version CDN précise est celle dont on sait qu'elle fonctionnait
 * déjà en production). Résout une fois le script chargé et window.dashjs
 * disponible ; résout immédiatement s'il l'est déjà. */
let dashJsPromise: Promise<any> | null = null
function loadDashJs(): Promise<any> {
  if ((window as any).dashjs) return Promise.resolve((window as any).dashjs)
  if (!dashJsPromise) {
    dashJsPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://cdn.jsdelivr.net/npm/dashjs@4.7.4/dist/dash.all.min.js'
      script.onload = () => resolve((window as any).dashjs)
      script.onerror = () => reject(new Error('dash.js indisponible'))
      document.head.appendChild(script)
    })
  }
  return dashJsPromise
}

/**
 * Chaîne de secours à 5 niveaux, reprise de l'ancien lecteur (Livewatch.py /
 * JS vanilla : _initHLSDirect → _initHLSProxy → _initSafariProxy →
 * _initMP4Direct → _initIframe). La toute première réécriture de ce
 * composant ne tentait qu'UNE méthode et abandonnait au premier échec ; une
 * deuxième passe avait ajouté 4 niveaux mais oublié le 5ᵉ (iframe), qui est
 * pourtant le vrai dernier recours de l'ancien code pour les sources qui
 * sont en fait des pages web/lecteurs embarqués plutôt que des fichiers
 * média bruts.
 *  1. hls.js sur l'URL directe (évite le proxy si la source autorise le CORS)
 *  2. hls.js sur l'URL proxifiée (le cas normal pour la plupart des flux IPTV)
 *  3. <video> natif sur l'URL proxifiée (Safari lit le HLS nativement)
 *  4. <video> natif sur l'URL directe
 *  5. <iframe> sur l'URL directe (dernier recours, comme l'ancien code)
 *
 * Sur chaque erreur FATALE de hls.js, on tente d'abord une auto-guérison en
 * place avant de passer au niveau suivant — recommandation officielle
 * hls.js (voir docs/API.md « fatal error recovery ») : hls.startLoad() pour
 * une erreur réseau, hls.recoverMediaError() pour une erreur média. Ces
 * deux tentatives sont bornées (2 essais max) : les retenter indéfiniment
 * est un piège documenté qui peut créer une boucle de rechargement infinie
 * plutôt que d'aider.
 */
export function VideoPlayer({ src, directUrl, type = 'hls', poster, title }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [iframeUrl, setIframeUrl] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    setIframeUrl(null)
    if (type === 'youtube' || type === 'iframe' || type === 'audio') return
    const video = videoRef.current
    if (!video) return

    // RTMP n'a aucun chemin de lecture possible dans un navigateur (Flash
    // n'existe plus, aucun navigateur ne sait lire du RTMP nativement) —
    // l'ancienne version n'avait pas non plus de vraie solution pour ce cas,
    // mieux vaut le dire clairement que de faire semblant d'essayer.
    if (type === 'rtmp') {
      setError('Ce flux (RTMP) ne peut pas être lu directement dans le navigateur.')
      return
    }

    let cancelled = false

    // Niveau 5 : iframe sur l'URL directe — dernier recours absolu, avant
    // d'abandonner franchement (matche _initIframe de l'ancien code).
    const stageIframe = () => {
      if (cancelled) return
      if (directUrl) setIframeUrl(directUrl)
      else setError('Impossible de charger ce flux pour le moment.')
    }

    // DASH (.mpd) : hls.js ne sait pas lire ce format, il faut dash.js — une
    // bibliothèque séparée, chargée à la demande (voir loadDashJs ci-dessus).
    // L'ancienne version tombe directement sur l'iframe (niveau 5) en cas
    // d'échec DASH plutôt que d'essayer le HLS/MP4 natif (peu de chances
    // qu'une source DASH cassée soit lisible autrement) — reproduit ici.
    if (type === 'dash') {
      let dashPlayer: any = null
      loadDashJs()
        .then((dashjs) => {
          if (cancelled) return
          dashPlayer = dashjs.MediaPlayer().create()
          dashPlayer.initialize(video, directUrl || src, true)
          dashPlayer.on(dashjs.MediaPlayer.events.ERROR, () => {
            if (dashPlayer) { dashPlayer.reset(); dashPlayer = null }
            stageIframe()
          })
        })
        .catch(() => stageIframe())
      return () => { cancelled = true; if (dashPlayer) dashPlayer.reset() }
    }

    // Muet obligatoire : les navigateurs bloquent silencieusement l'autoplay
    // avec le son (aucune erreur JS, aucune ligne dans les logs réseau — le
    // flux se charge très bien côté serveur, la vidéo reste juste figée sur
    // une image noire).
    video.muted = true

    let hls: Hls | null = null
    const cleanupHls = () => { if (hls) { hls.destroy(); hls = null } }

    const tryHlsJs = (url: string, opts: ConstructorParameters<typeof Hls>[0], onFatal: () => void) => {
      cleanupHls()
      hls = new Hls(opts)
      const instance = hls
      let networkRetries = 0
      let mediaRetries = 0
      instance.loadSource(url)
      instance.attachMedia(video)
      instance.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => { /* lecture au clic si bloquée malgré le mute */ })
      })
      instance.on(Hls.Events.ERROR, (_evt, data) => {
        if (cancelled || !data.fatal) return // hls.js gère déjà les erreurs non-fatales lui-même
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            if (networkRetries < 2) {
              networkRetries++
              instance.startLoad()
              return
            }
            break
          case Hls.ErrorTypes.MEDIA_ERROR:
            if (mediaRetries < 2) {
              mediaRetries++
              instance.recoverMediaError()
              return
            }
            break
        }
        cleanupHls()
        onFatal()
      })
    }

    const tryNative = (url: string, onFail: () => void) => {
      cleanupHls()
      video.src = url
      video.load()
      video.play().catch(() => { /* lecture au clic si bloquée malgré le mute */ })
      video.addEventListener('error', onFail, { once: true })
    }

    // Niveau 4 : natif sur l'URL directe
    const stageNativeDirect = () => {
      if (directUrl) tryNative(directUrl, stageIframe)
      else stageIframe()
    }
    // Niveau 3 : natif sur l'URL proxifiée
    const stageNativeProxy = () => tryNative(src, stageNativeDirect)
    // Niveau 2 : hls.js sur l'URL proxifiée (timeouts plus tolérants, c'est
    // le chemin qui doit marcher dans la grande majorité des cas)
    const stageHlsProxy = () => {
      if (Hls.isSupported()) {
        tryHlsJs(src, {
          enableWorker: true, lowLatencyMode: false,
          manifestLoadingTimeOut: 15000, manifestLoadingMaxRetry: 2,
          levelLoadingTimeOut: 15000, fragLoadingTimeOut: 25000,
        }, stageNativeProxy)
      } else {
        stageNativeProxy()
      }
    }
    // Niveau 1 : hls.js sur l'URL directe (sauté si pas d'URL directe dispo)
    const stageHlsDirect = () => {
      if (directUrl && Hls.isSupported()) {
        tryHlsJs(directUrl, {
          enableWorker: true, lowLatencyMode: true,
          backBufferLength: 30, maxBufferLength: 90,
          manifestLoadingTimeOut: 10000, manifestLoadingMaxRetry: 1,
          levelLoadingTimeOut: 10000, fragLoadingTimeOut: 20000,
        }, stageHlsProxy)
      } else {
        stageHlsProxy()
      }
    }

    // mp4 (et formats vidéo simples type mkv/webm/mov) : pas besoin de
    // hls.js, qui échouerait de toute façon à parser un fichier vidéo brut
    // comme un manifeste — <video> natif suffit directement.
    if (type === 'mp4') {
      tryNative(directUrl ?? src, () => tryNative(src, stageNativeDirect))
      return () => { cancelled = true; cleanupHls() }
    }

    // Safari lit le HLS nativement et n'a pas besoin de hls.js — mais on
    // tente quand même hls.js d'abord partout ailleurs (Chrome/Firefox n'ont
    // pas de support HLS natif, et hls.js gère mieux les erreurs réseau).
    if (video.canPlayType('application/vnd.apple.mpegurl') && !Hls.isSupported()) {
      tryNative(directUrl ?? src, () => tryNative(src, stageNativeDirect))
    } else {
      stageHlsDirect()
    }

    return () => { cancelled = true; cleanupHls() }
  }, [src, directUrl, type])

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

  if (iframeUrl) {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
        <iframe
          src={iframeUrl}
          title={title}
          allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
          allowFullScreen
          className="h-full w-full border-0"
          onError={() => setError('Impossible de charger ce flux pour le moment.')}
        />
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
