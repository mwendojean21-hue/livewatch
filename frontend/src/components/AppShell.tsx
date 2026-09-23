import { type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import {
  Home, Search, Radio, Calendar, Settings, ShieldCheck, User, Cast, Menu, Download,
} from 'lucide-react'
import { useState } from 'react'
import { ThemeToggle } from './ThemeToggle'

const NAV = [
  { to: '/', label: 'Accueil', icon: Home, end: true },
  { to: '/search', label: 'Recherche', icon: Search, end: false },
  { to: '/category/iptv', label: 'Chaînes TV', icon: Radio, end: false },
  { to: '/events', label: 'Événements', icon: Calendar, end: false },
  { to: '/go-live', label: 'Diffuser', icon: Cast, end: false },
]

const NAV_SECONDARY = [
  { to: '/settings', label: 'Paramètres', icon: Settings },
  { to: '/admin', label: 'Admin', icon: ShieldCheck },
  { to: '/profile', label: 'Profil', icon: User },
]

function NavItem({ to, label, icon: Icon, end, onClick }: {
  to: string; label: string; icon: typeof Home; end?: boolean; onClick?: () => void
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
          isActive
            ? 'bg-white/10 text-white'
            : 'text-white/60 hover:bg-white/5 hover:text-white'
        }`
      }
    >
      <Icon size={18} strokeWidth={2} />
      {label}
    </NavLink>
  )
}

function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col bg-[#0A0E1A] px-4 py-6 lg:flex">
      <Link to="/" className="mb-8 flex items-center gap-2 px-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">
          <Cast size={16} className="text-white" />
        </span>
        <span className="font-display text-lg font-semibold text-white">Livewatch</span>
      </Link>
      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map((item) => <NavItem key={item.to} {...item} />)}
      </nav>
      <div className="mt-4 flex flex-col gap-1 border-t border-white/10 pt-4">
        {NAV_SECONDARY.map((item) => <NavItem key={item.to} {...item} />)}
      </div>
    </aside>
  )
}

function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <aside className="absolute left-0 top-0 flex h-full w-72 flex-col bg-[#0A0E1A] px-4 py-6">
        <Link to="/" onClick={onClose} className="mb-8 flex items-center gap-2 px-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">
            <Cast size={16} className="text-white" />
          </span>
          <span className="font-display text-lg font-semibold text-white">Livewatch</span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1">
          {[...NAV, ...NAV_SECONDARY].map((item) => <NavItem key={item.to} {...item} onClick={onClose} />)}
        </nav>
        <a
          href="/static/livewatch.apk"
          download
          onClick={onClose}
          className="mt-2 flex items-center gap-3 rounded-xl border-t border-white/10 px-3 py-2.5 pt-4 text-sm font-medium text-white/60 hover:text-white"
        >
          <Download size={18} strokeWidth={2} />
          Télécharger l'appli
        </a>
      </aside>
    </div>
  )
}

function BottomNav() {
  const items = [
    { to: '/', label: 'Accueil', icon: Home, end: true },
    { to: '/search', label: 'Recherche', icon: Search, end: false },
    { to: '/go-live', label: 'Diffuser', icon: Cast, end: false, raised: true },
    { to: '/events', label: 'Events', icon: Calendar, end: false },
    { to: '/profile', label: 'Profil', icon: User, end: false },
  ]
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-surface/95 px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
      {items.map(({ to, label, icon: Icon, end, raised }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium ${
              isActive ? 'text-accent-2' : 'text-ink-muted'
            }`
          }
        >
          {({ isActive }) =>
            raised ? (
              <span className="-mt-6 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow-lg">
                <Icon size={20} />
              </span>
            ) : (
              <>
                <Icon size={20} className={isActive ? 'text-accent-2' : ''} />
                {label}
              </>
            )
          }
        </NavLink>
      ))}
    </nav>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const navigate = useNavigate()

  function handleSearchSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const q = new FormData(e.currentTarget).get('q')?.toString().trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      <Sidebar />
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-bg/85 px-4 py-3 backdrop-blur-md sm:px-6">
          <button
            type="button"
            aria-label="Ouvrir le menu"
            onClick={() => setDrawerOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 lg:hidden"
          >
            <Menu size={20} />
          </button>

          <form onSubmit={handleSearchSubmit} className="relative min-w-0 flex-1 max-w-md">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input
              name="q"
              type="search"
              placeholder="Rechercher une chaîne, un direct…"
              className="w-full rounded-full border border-border bg-surface py-2 pl-9 pr-4 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2"
            />
          </form>

          <div className="ml-auto flex items-center gap-2.5">
            <a
              href="/static/livewatch.apk"
              download
              title="Télécharger l'application Android"
              className="hidden h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink sm:flex"
            >
              <Download size={18} />
            </a>
            <ThemeToggle />
            <Link
              to="/go-live"
              className="hidden items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 sm:flex"
            >
              <Cast size={15} /> Go Live
            </Link>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 pb-24 pt-5 sm:px-6 lg:pb-8">{children}</main>
      </div>

      <BottomNav />
    </div>
  )
}
