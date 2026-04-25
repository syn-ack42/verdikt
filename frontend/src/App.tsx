import { Routes, Route, Navigate } from 'react-router-dom'
import ProjectList from './pages/ProjectList'
import ProjectCreate from './pages/ProjectCreate'
import ProjectDashboard from './pages/ProjectDashboard'
import RatingInterface from './pages/RatingInterface'
import ProfileView from './pages/ProfileView'
import Login from './pages/Login'
import Register from './pages/Register'
import AdminUsers from './pages/AdminUsers'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/new" element={<ProjectCreate />} />
        <Route path="/projects/:projectId" element={<ProjectDashboard />} />
        <Route path="/projects/:projectId/rate" element={<RatingInterface />} />
        <Route path="/projects/:projectId/profile" element={<ProfileView />} />
        <Route path="/admin/users" element={<AdminUsers />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
