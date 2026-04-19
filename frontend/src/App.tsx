import { Routes, Route, Navigate } from 'react-router-dom'
import ProjectList from './pages/ProjectList'
import ProjectCreate from './pages/ProjectCreate'
import ProjectDashboard from './pages/ProjectDashboard'
import RatingInterface from './pages/RatingInterface'
import ProfileView from './pages/ProfileView'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/projects/new" element={<ProjectCreate />} />
      <Route path="/projects/:projectId" element={<ProjectDashboard />} />
      <Route path="/projects/:projectId/rate" element={<RatingInterface />} />
      <Route path="/projects/:projectId/profile" element={<ProfileView />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
