import { Suspense, lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { LoadingFallback } from '@/components/ui'

const HomePage = lazy(() => import('@/pages/HomePage').then((m) => ({ default: m.HomePage })))
const SearchPage = lazy(() => import('@/pages/SearchPage').then((m) => ({ default: m.SearchPage })))
const WatchPage = lazy(() => import('@/pages/WatchPage').then((m) => ({ default: m.WatchPage })))
const GoLivePage = lazy(() => import('@/pages/GoLivePage').then((m) => ({ default: m.GoLivePage })))
const EventsPage = lazy(() => import('@/pages/EventsPage').then((m) => ({ default: m.EventsPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const AdminPage = lazy(() => import('@/pages/AdminPage').then((m) => ({ default: m.AdminPage })))
const ProfilePage = lazy(() => import('@/pages/MiscPages').then((m) => ({ default: m.ProfilePage })))
const NotFoundPage = lazy(() => import('@/pages/MiscPages').then((m) => ({ default: m.NotFoundPage })))

export default function App() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingFallback />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/category/:categoryId" element={<HomePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/watch/:kind/:streamId" element={<WatchPage />} />
          <Route path="/go-live" element={<GoLivePage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/admin/dashboard" element={<AdminPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  )
}
