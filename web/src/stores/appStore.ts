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
  sessionId: null,
  setAuth: (token, username, role) => {
    localStorage.setItem('token', token);
    localStorage.setItem('username', username);
    localStorage.setItem('role', role);
    set({ token, username, role });
  },
  setSession: (id) => set({ sessionId: id }),
  logout: () => {
    localStorage.clear();
    set({ token: '', username: '', role: '', sessionId: null });
  },
}));
