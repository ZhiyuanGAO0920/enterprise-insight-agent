import { lazy, Suspense, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { useAuth } from './hooks/useAuth';
import AppLayout from './components/AppLayout';
import Intro from './components/Intro';

/* 路由级懒加载：antd + echarts 不进首屏，按需加载 */
const LoginPage = lazy(() => import('./pages/Login'));
const AnalysisPage = lazy(() => import('./pages/Analysis'));
const DashboardPage = lazy(() => import('./pages/Dashboard'));
const MonitorPage = lazy(() => import('./pages/Monitor'));
const HistoryPage = lazy(() => import('./pages/History'));
const SharePage = lazy(() => import('./pages/Share'));
const AdminPanel = lazy(() => import('./pages/Admin'));

function PageFallback() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#1a1a2e' }}>
      <Spin size="large" />
    </div>
  );
}

export default function App() {
  const { token } = useAuth();
  /* 有 token 的用户从不需要 Intro（含切换/退出账户后），仅无 token 首访显示欢迎页 */
  const [introDone, setIntroDone] = useState(() => Boolean(token));

  const routes = (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        {/* 公开分享页：免登录（在鉴权检查之前） */}
        <Route path="/share/:token" element={<SharePage />} />
        {token ? (
          <>
            {/* 侧边栏布局（对齐原生 sidebar + header） */}
            <Route element={<AppLayout />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="/admin" element={<AdminPanel />} />
              {/* 默认首页 = 经营看板（对齐原生默认 tab） */}
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </>
        ) : (
          <>
            <Route path="*" element={<LoginPage />} />
          </>
        )}
      </Routes>
    </Suspense>
  );

  return (
    <>
      {/* Intro 欢迎页：全屏浮层，必须在 <Routes> 之外渲染（react-router v6 要求 Routes 子元素必须是 <Route>） */}
      {!token && !introDone && <Intro onEnter={() => setIntroDone(true)} />}
      {routes}
    </>
  );
}
