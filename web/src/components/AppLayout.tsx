import { useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Drawer, Dropdown, Tag, Button } from 'antd';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useAppStore } from '../stores/appStore';
import client from '../api/client';
import { DARK } from '../theme';
import FeedbackHistoryModal from './FeedbackHistory';
import ContactModal from './ContactModal';

const NAV_ITEMS = [
  { key: 'dashboard', path: '/dashboard', icon: '📊', label: '经营看板' },
  { key: 'analysis', path: '/analysis', icon: '💬', label: '分析对话' },
  { key: 'history', path: '/history', icon: '📝', label: '历史记录' },
  { key: 'monitor', path: '/monitor', icon: '📋', label: '质量监控', adminOnly: true },
  { key: 'admin', path: '/admin', icon: '⚙️', label: '系统管理', adminOnly: true },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { username, role, logout } = useAuth();
  const { sessionId, setSession } = useAppStore();

  const [fbOpen, setFbOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [entityMemory, setEntityMemory] = useState<Record<string, { type?: string }> | null>(null);
  /* 后端健康检查（真实状态，替换原硬编码"● 就绪"） */
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    fetch('/health', { signal: ctrl.signal })
      .then((r) => setHealthy(r.ok))
      .catch(() => setHealthy(false))
      .finally(() => clearTimeout(timer));
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, []);

  /* 移动端检测（对齐原生 768px 断点） */
  const [mobile, setMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const fn = (e: MediaQueryListEvent) => setMobile(e.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, []);

  const currentKey = NAV_ITEMS.find((n) => n.path && location.pathname.startsWith(n.path))?.key;
  const isAdminRoute = location.pathname.startsWith('/admin');

  /* ── 会话信息（含实体记忆，对齐原生 loadSessionInfo） ── */
  const loadSession = useCallback(async () => {
    if (!sessionId) { setEntityMemory(null); return; }
    try {
      const res = await client.get(`/session/${sessionId}`);
      const em = res.data.entity_memory || {};
      const keys = Object.keys(em);
      setEntityMemory(keys.length ? em : null);
    } catch { /* 会话过期时静默；同时清空残留记忆避免展示过期实体 */ setEntityMemory(null); }
  }, [sessionId]);

  useEffect(() => { loadSession(); }, [loadSession]);

  const newSession = async () => {
    try {
      const res = await client.post('/session/create');
      setSession(res.data.session_id);
      setEntityMemory(null);
      /* 清除跳转来源 state（如历史页带过来的 recordId），配合 Analysis 的 sessionId 重置 effect */
      navigate('/analysis', { state: null });
    } catch { /* noop */ }
  };

  const navStyle = (active: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '10px 14px',
    background: active ? 'rgba(99,102,241,0.15)' : 'transparent',
    color: active ? '#fff' : DARK.muted, border: 'none', borderRadius: 8, cursor: 'pointer',
    fontSize: 13, fontWeight: active ? 600 : 400, textAlign: 'left',
    borderLeft: active ? `3px solid ${DARK.accent}` : '3px solid transparent',
  });

  /* 侧边栏内容（桌面固定版 + 移动端抽屉共用） */
  const SidebarContent = () => (
    <>
      <h1 style={{ margin: '0 8px 4px', fontSize: 15, color: DARK.text, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: DARK.accent, display: 'inline-block' }} />
        智能经营分析
      </h1>
      <p style={{ margin: '0 8px 16px', fontSize: 11, color: healthy === false ? DARK.down : DARK.up }}>
        {healthy === false ? '○ 服务未连接' : '● 就绪'}
      </p>

      {/* 导航 */}
      <nav>
        {NAV_ITEMS.filter((n) => !n.adminOnly || role === 'admin' || role === 'regional_director').map((n) => (
          <button
            key={n.key}
            style={{ ...navStyle(currentKey === n.key), marginBottom: 2 }}
            onClick={() => { navigate(n.path!); setNavOpen(false); }}
          >
            <span>{n.icon}</span> {n.label}
          </button>
        ))}
      </nav>

      <hr style={{ borderColor: DARK.border, margin: '14px 0' }} />

      {/* 新建会话 */}
      <button onClick={() => { newSession(); setNavOpen(false); }} style={{
        padding: '9px 14px', borderRadius: 8, border: `1px dashed ${DARK.border}`,
        background: 'transparent', color: DARK.accent, cursor: 'pointer', fontSize: 13, fontWeight: 600,
      }}>＋ 新建会话</button>
      <p style={{ fontSize: 10, color: DARK.muted, textAlign: 'center', marginTop: 6 }}>
        会话 ID：<span>{sessionId ? sessionId.slice(0, 8) + '...' : '未创建'}</span>
      </p>

      {/* 角色信息 */}
      <div style={{
        fontSize: 11, color: DARK.muted, background: DARK.bg, padding: '8px 10px',
        borderRadius: 6, marginTop: 8, display: role ? 'block' : 'none',
      }}>
        <p style={{ margin: 0 }}>当前角色：<strong style={{ color: DARK.text }}>{role || '-'}</strong></p>
      </div>

      {/* 实体记忆 */}
      <div style={{ marginTop: 10, fontSize: 11, color: DARK.muted, display: entityMemory ? 'block' : 'none' }}>
        <p style={{ margin: '0 0 4px' }}>已记住的实体：</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {entityMemory && Object.entries(entityMemory).map(([k, v]) => (
            <span key={k} style={{
              background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 10,
              padding: '2px 8px', fontSize: 11, color: DARK.text,
            }}>
              {v.type === 'member' ? '👤 ' : '🏪 '}{k}
            </span>
          ))}
        </div>
      </div>

      <div style={{ fontSize: 11, color: DARK.muted, marginTop: 'auto', paddingTop: 10 }}>大模型：DeepSeek</div>
    </>
  );

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: DARK.bg }}>
      {/* ═══════════ 侧边栏（桌面固定，对齐原生 sidebar） ═══════════ */}
      {!mobile && (
        <aside style={{
          width: 220, minHeight: '100vh', background: '#15152e',
          borderRight: `1px solid ${DARK.border}`, display: 'flex', flexDirection: 'column',
          padding: '16px 12px', flexShrink: 0, position: 'sticky', top: 0, height: '100vh',
        }}>
          <SidebarContent />
        </aside>
      )}

      {/* ═══════════ 主区 ═══════════ */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* 顶部 Header（对齐原生 header） */}
        <header style={{
          height: 56, background: DARK.bg, borderBottom: `1px solid ${DARK.border}`,
          display: 'flex', alignItems: 'center', padding: '0 16px', position: 'sticky', top: 0, zIndex: 100,
        }}>
          {/* 移动端：汉堡菜单 */}
          {mobile && (
            <Button type="text" style={{ color: DARK.text, marginRight: 8, fontSize: 18 }} onClick={() => setNavOpen(true)}>☰</Button>
          )}
          <h2 style={{ margin: 0, fontSize: 15, color: DARK.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>企业智能经营分析平台</h2>
          <Tag style={{ marginLeft: 8 }} color="purple">v4.6</Tag>

          {/* 用户菜单（对齐原生 user-menu） */}
          <div style={{ marginLeft: 'auto' }}>
            <Dropdown
              menu={{
                items: [
                  { key: 'fb', label: '📝 我的反馈' },
                  { key: 'contact', label: '💬 意见反馈' },
                  { key: 'switch', label: '🔄 切换账户' },
                  { type: 'divider' },
                  { key: 'logout', label: '🚪 退出登录', danger: true },
                ],
                onClick: ({ key }) => {
                  if (key === 'fb') setFbOpen(true);
                  else if (key === 'contact') setContactOpen(true);
                  else if (key === 'switch') { logout(); navigate('/login'); }
                  else if (key === 'logout') logout();
                },
              }}
            >
              <button style={{
                display: 'flex', alignItems: 'center', gap: 8, background: 'transparent',
                border: 'none', cursor: 'pointer', padding: '6px 10px', borderRadius: 8,
              }}>
                <span style={{
                  width: 28, height: 28, borderRadius: '50%', background: DARK.accent,
                  color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, fontWeight: 700,
                }}>{(username || 'u')[0].toUpperCase()}</span>
                <span style={{ color: DARK.text, fontSize: 13 }}>{username}</span>
                <span style={{ color: DARK.muted, fontSize: 10 }}>▾</span>
              </button>
            </Dropdown>
          </div>
        </header>

        {/* 内容区 */}
        <main style={{ padding: 24 }}>
          <Outlet />
        </main>
      </div>

      {/* 路由守卫：非管理员直访 /admin 重定向回看板（导航入口已按角色过滤）。
          必须放在所有 hooks 之后，保证 hook 调用顺序稳定（rules-of-hooks） */}
      {isAdminRoute && role !== 'admin' && role !== 'regional_director' && <Navigate to="/dashboard" replace />}

      {/* ═══════════ 移动端：导航抽屉 ═══════════ */}
      <Drawer
        placement="left" open={mobile && navOpen} onClose={() => setNavOpen(false)}
        width={240} styles={{ body: { padding: '16px 12px', background: '#15152e', display: 'flex', flexDirection: 'column' } }}
      >
        <SidebarContent />
      </Drawer>

      {/* ═══════════ 我的反馈 ═══════════ */}
      <FeedbackHistoryModal open={fbOpen} onClose={() => setFbOpen(false)} />

      {/* ═══════════ 意见反馈 ═══════════ */}
      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  );
}
