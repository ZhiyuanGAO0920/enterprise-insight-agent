/* ── 通用格式化工具 ── */

/* 从 catch 的 unknown 错误中提取可展示文案（后端 FastAPI detail 优先） */
export function errMsg(e: unknown, fallback: string): string {
  if (typeof e === 'object' && e !== null) {
    const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (detail) return detail;
    const msg = (e as { message?: string }).message;
    if (msg) return msg;
    const name = (e as { name?: string }).name;
    if (name === 'AbortError') return '请求已取消';
  }
  return fallback;
}

export function formatMoney(v: number): string {
  if (v >= 10000) return `¥${(v / 10000).toFixed(1)}万`;
  return `¥${Math.round(v).toLocaleString()}`;
}

/* YYYY-MM-DD HH:mm */
export function formatTime(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* MM-DD HH:mm（列表场景短格式） */
export function formatShortTime(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
