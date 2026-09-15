import { useEffect, useState } from 'react'
import { Cast } from 'lucide-react'

const SESSION_KEY = '_lw_seen'
const MIN_DISPLAY_MS = 600
const MAX_DISPLAY_MS = 2000

/** Écran de démarrage affiché une fois par session (comme dans l'ancienne
 * version : logo qui pulse, 3 points animés, fond sombre). Se ferme dès que
 * l'app est montée (délai minimum pour éviter un flash), et de toute façon
 * au bout de MAX_DISPLAY_MS. Les routes profondes (admin, watch…) ne
 * l'affichent pas non plus dans l'ancienne version, mais ici l'app est une
 * SPA : on se contente de sessionStorage pour ne l'afficher qu'une fois par
 * session d'onglet. */
export function SplashScreen() {
  const [visible, setVisible] = useState(() => !sessionStorage.getItem(SESSION_KEY))
  const [fading, setFading] = useState(false)

  useEffect(() => {
    if (!visible) return
    sessionStorage.setItem(SESSION_KEY, '1')

    const minTimer = setTimeout(() => setFading(true), MIN_DISPLAY_MS)
    const maxTimer = setTimeout(() => setFading(true), MAX_DISPLAY_MS)
    return () => { clearTimeout(minTimer); clearTimeout(maxTimer) }
  }, [visible])

  useEffect(() => {
    if (!fading) return
    const t = setTimeout(() => setVisible(false), 500) // durée de la transition d'opacité
    return () => clearTimeout(t)
  }, [fading])

  if (!visible) return null

  return (
    <div
      className="fixed inset-0 z-[99999] flex flex-col items-center justify-center bg-[#0f0f1a] transition-opacity duration-500"
      style={{ opacity: fading ? 0 : 1 }}
      aria-hidden="true"
    >
      <div
        className="mb-6 flex h-[120px] w-[120px] items-center justify-center rounded-3xl shadow-[0_0_40px_rgba(220,38,38,0.5)]"
        style={{
          background: 'linear-gradient(135deg, #dc2626, #f97316)',
          animation: 'lw-splash-pulse 1.2s ease-in-out infinite alternate',
        }}
      >
        <Cast size={48} className="text-white" strokeWidth={2} />
      </div>
      <span className="text-3xl font-black tracking-tight text-white [text-shadow:0_2px_16px_rgba(0,0,0,0.4)]">
        Livewatch
      </span>
      <div className="mt-5 flex gap-2">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" style={{ animationDelay: '0s' }} />
        <span className="h-2 w-2 animate-pulse rounded-full bg-orange-500" style={{ animationDelay: '0.2s' }} />
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" style={{ animationDelay: '0.4s' }} />
      </div>
      <style>{`
        @keyframes lw-splash-pulse {
          from { transform: scale(0.96); opacity: 0.8; }
          to   { transform: scale(1.04); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
