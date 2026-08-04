import { useAppStore } from '../stores/appStore';
import client from '../api/client';

export function useAuth() {
  const store = useAppStore();

  const login = async (username: string, password: string) => {
    const res = await client.post('/auth/login', { username, password });
    const data = res.data;
    // 先写入 token，后续请求的拦截器才能带上 Authorization
    localStorage.setItem('token', data.access_token);
    // V4.6+ 登录响应直接携带 role（不再依赖 /admin/users 旁路猜测，非 admin 用户也能正确识别角色）
    // 旧后端无 role 字段时回退到原有查询逻辑
    let role = data.role || 'store_manager';
    if (!data.role) {
      try {
        const me = await client.get('/admin/users', { params: { search: username } });
        const found = (me.data.users || []).find((u: { username: string; role?: string }) => u.username === username);
        if (found?.role) role = found.role;
      } catch { /* 无 user:manage 权限时保持默认 */ }
    }
    store.setAuth(data.access_token, username, role);
    return data;
  };

  const logout = () => store.logout();

  return {
    token: store.token,
    username: store.username,
    role: store.role,
    login,
    logout,
  };
}
