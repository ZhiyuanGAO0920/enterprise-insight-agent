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

/* 毫秒 → 秒（两位小数），如 4523 → "4.52s"、45 → "0.05s"（全站耗时统一秒单位） */
export function fmtSec(ms?: number | null): string {
  return ((ms ?? 0) / 1000).toFixed(2) + 's';
}

/* 后端统一存 naive UTC（models._utcnow），isoformat() 输出无时区标记（如 "2026-08-07T01:55:26"）。
   JS 的 new Date() 会把无 Z 的 ISO 串当本地时间解析 → 差 8 小时。
   这里补 'Z' 按 UTC 解析，再转浏览器本地时区展示（用户在北京/东八区时即北京时间）。 */
function parseBackendTs(ts: string): Date {
  const isNaiveIso =
    /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(ts) &&
    !/[Zz]$/.test(ts) &&
    !/[+-]\d{2}:?\d{2}$/.test(ts);
  return new Date(isNaiveIso ? ts.replace(' ', 'T') + 'Z' : ts);
}

/* YYYY-MM-DD HH:mm */
export function formatTime(ts?: string): string {
  if (!ts) return '';
  const d = parseBackendTs(ts);
  if (isNaN(d.getTime())) return ts;
  const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* MM-DD HH:mm（列表场景短格式） */
export function formatShortTime(ts?: string): string {
  if (!ts) return '';
  const d = parseBackendTs(ts);
  if (isNaN(d.getTime())) return ts;
  const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
