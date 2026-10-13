import * as React from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { useAuth } from '@/contexts/AuthContext'
import { LoginPage } from '@/pages/LoginPage'

const ContentPage = React.lazy(() => import('@/pages/ContentPage').then((m) => ({ default: m.ContentPage })))
const OverviewPage = React.lazy(() => import('@/pages/OverviewPage').then((m) => ({ default: m.OverviewPage })))
const ReportsPage = React.lazy(() => import('@/pages/ReportsPage').then((m) => ({ default: m.ReportsPage })))
const SettingsPage = React.lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const ProjectDetailPage = React.lazy(() => import('@/pages/ProjectDetailPage').then((m) => ({ default: m.ProjectDetailPage })))
const TasksPage = React.lazy(() => import('@/pages/TasksPage').then((m) => ({ default: m.TasksPage })))
const TrafficPage = React.lazy(() => import('@/pages/TrafficPage').then((m) => ({ default: m.TrafficPage })))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  // Remember where the user was going, so signing in lands there instead of on the overview.
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<OverviewPage />} />
        <Route path="/content" element={<ContentPage />} />
        <Route path="/traffic" element={<TrafficPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
