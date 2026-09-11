import { useEffect, useRef, useState } from 'react'
import { isDemoMode, onDemoModeChange } from '@/api/client'

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fnRef.current()
      .then((res) => { if (!cancelled) setData(res) })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Erreur inconnue') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}

export function useDemoMode() {
  const [demo, setDemo] = useState(isDemoMode)
  useEffect(() => {
    const unsubscribe = onDemoModeChange(setDemo)
    return unsubscribe
  }, [])
  return demo
}
