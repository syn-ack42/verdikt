import { Routes, Route, Navigate } from 'react-router-dom'
import ProjectList from './pages/ProjectList'
import ProjectCreate from './pages/ProjectCreate'
import ProjectDashboard from './pages/ProjectDashboard'
import RatingInterface from './pages/RatingInterface'
import DiscoveryInterface from './pages/DiscoveryInterface'
import ProfileView from './pages/ProfileView'
import Login from './pages/Login'
import Register from './pages/Register'
import ConfirmEmail from './pages/ConfirmEmail'
import AdminUsers from './pages/AdminUsers'
import AdminModels from './pages/AdminModels'
import AdminSettings from './pages/AdminSettings'
import UserSettings from './pages/UserSettings'
import Usage from './pages/Usage'
import Help from './pages/Help'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/confirm-email" element={<ConfirmEmail />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/new" element={<ProjectCreate />} />
        <Route path="/projects/:projectId" element={<ProjectDashboard />} />
        <Route path="/projects/:projectId/rate" element={<RatingInterface />} />
        <Route path="/projects/:projectId/discover" element={<DiscoveryInterface />} />
        <Route path="/projects/:projectId/profile" element={<ProfileView />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/models" element={<AdminModels />} />
        <Route path="/admin/settings" element={<AdminSettings />} />
        <Route path="/settings/password" element={<UserSettings />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/help" element={<Help />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
