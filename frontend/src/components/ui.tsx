import type { LucideIcon } from 'lucide-react'
import { WifiOff } from 'lucide-react'
import { useDemoMode } from '@/hooks/useApi'

export function LiveBadge({ label = 'DIRECT' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white">
      <span className="live-dot bg-white" />
      {label}
    </span>
  )
}

export function StatCard({
  label, value, icon: Icon, hint,
}: { label: string; value: string; icon: LucideIcon; hint?: string }) {
  return (
    <div className="card flex items-center gap-4 p-5">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-2-soft text-accent-2">
        <Icon size={20} strokeWidth={2} />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm text-ink-muted">{label}</p>
        <p className="font-display tabular-nums text-2xl font-semibold leading-tight">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}
      </div>
    </div>
  )
}

export function DemoBanner() {
  const demo = useDemoMode()
  if (!demo) return null
  return (
    <div className="mb-5 flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-4 py-2.5 text-sm text-accent">
      <WifiOff size={16} />
      <span>
        Mode démo — l'API backend n'est pas joignable, des données d'exemple sont affichées.
      </span>
    </div>
  )
}

export function SectionHeading({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {action}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-2 ${className}`} />
}

export function LoadingFallback() {
  return <Skeleton className="h-40 w-full" />
}
