import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import LoginPage from './pages/Login';
import AnalysisPage from './pages/Analysis';
import DashboardPage from './pages/Dashboard';
import AdminPage from './pages/Admin';
import MonitorPage from './pages/Monitor';

export default function App() {
  const { token } = useAuth();

  if (!token) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route path="/monitor" element={<MonitorPage />} />
      <Route path="/analysis" element={<AnalysisPage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/" element={<Navigate to="/monitor" replace />} />
      <Route path="*" element={<Navigate to="/monitor" replace />} />
    </Routes>
  );
}
