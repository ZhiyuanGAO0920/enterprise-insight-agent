import axios from 'axios';

const BASE = '/api/v1';

const client = axios.create({
  baseURL: BASE,
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    // 登录接口的 401 是「用户名或密码错误」，不能触发清态刷新——reload 会把错误提示冲掉（表现为"登录没反应也没提示"）
    const isLoginRequest = err.config?.url?.includes('/auth/login');
    if (err.response?.status === 401 && !isLoginRequest) {
      // 清理全部登录态（含 username/role/session_id，避免残留脏数据）
      localStorage.removeItem('token');
      localStorage.removeItem('username');
      localStorage.removeItem('role');
      localStorage.removeItem('session_id');
      window.location.reload();
    }
    return Promise.reject(err);
  }
);

export default client;
