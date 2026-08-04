import { create } from 'zustand';

interface AppState {
  token: string;
  username: string;
  role: string;
  sessionId: string | null;
  setAuth: (token: string, username: string, role: string) => void;
  setSession: (id: string) => void;
  logout: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  token: localStorage.getItem('token') || '',
  username: localStorage.getItem('username') || '',
  role: localStorage.getItem('role') || '',
  /* 会话持久化：刷新后恢复多轮对话上下文（对齐原生 restoreSession） */
  sessionId: localStorage.getItem('session_id') || null,
  setAuth: (token, username, role) => {
    localStorage.setItem('token', token);
    localStorage.setItem('username', username);
    localStorage.setItem('role', role);
    set({ token, username, role });
  },
  setSession: (id) => {
    localStorage.setItem('session_id', id);
    set({ sessionId: id });
  },
  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
    localStorage.removeItem('session_id');
    set({ token: '', username: '', role: '', sessionId: null });
  },
}));
