import { useAppStore } from '../stores/appStore';
import client from '../api/client';

export function useAuth() {
  const store = useAppStore();

  const login = async (username: string, password: string) => {
    const res = await client.post('/auth/login', { username, password });
    const data = res.data;
    store.setAuth(data.access_token, username, data.role || '');
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
