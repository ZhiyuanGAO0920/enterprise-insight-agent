// utils/config.js — 全局配置（环境切换）
// =====================================================================
// 环境说明（上线必读）：
// 微信小程序所有网络请求必须是 HTTPS，且域名需在微信后台
// 「开发管理 → 开发设置 → 服务器域名」白名单内（request 合法域名 + uploadFile/downloadFile 按需）。
//
// - 开发 / 真机调试：走 dev（HTTP 局域网地址，需开发者工具勾选「不校验合法域名」）
// - 体验版 / 正式版：走 prod（HTTPS 合法域名，必须已配置到微信后台）
//
// 切换逻辑：默认按小程序 envVersion 自动识别
//   develop / trial → dev，release → prod。
// 如需强制锁定某环境，改下方 FORCE_ENV（'dev' | 'prod' | null）。
// 注意：本地后端端口固定 8002（见 docker-compose.yml / 重启服务.bat）。
// =====================================================================

const ENV = {
  // 开发环境：本地后端，HTTP 即可。
  // ⚠️ 必须用电脑【局域网 IP】而非 127.0.0.1：模拟器里 127.0.0.1 由工具代理到本机可用，
  //    但真机上 127.0.0.1 指向手机自己 → 请求必失败（表现为"登录失败"）。
  //    当前：172.20.10.4 = iPhone 热点网段（ipconfig 查 WLAN IPv4 可得）。
  //    ⚠️ 换热点/换 WiFi 后 IP 必变，须重新 ipconfig 查并同步改这里（模拟器同机兼容）。
  //    前置：手机与电脑同一 WiFi；开发者工具「详情 → 本地设置」勾选「不校验合法域名」。
  dev: {
    baseUrl: 'http://172.20.10.4:8002/api/v1',
  },
  // 生产环境：HTTPS 合法域名。上线前替换为你自己的域名，并在微信后台配置。
  prod: {
    baseUrl: 'https://your-domain.com/api/v1',
  },
};

// 强制环境：'dev' | 'prod' | null（null = 按 envVersion 自动识别）
const FORCE_ENV = null;

function resolveEnv() {
  if (FORCE_ENV === 'dev' || FORCE_ENV === 'prod') return FORCE_ENV;
  try {
    // develop=开发版/真机预览(可HTTP) → dev；trial=体验版、release=正式版(必校验HTTPS) → prod
    const envVersion = wx.getAccountInfoSync().miniProgram.envVersion;
    return envVersion === 'develop' ? 'dev' : 'prod';
  } catch (e) {
    return 'dev'; // 兜底：拿不到环境信息时按开发态处理
  }
}

const active = ENV[resolveEnv()];

const config = {
  // 当前生效的基础地址（由 resolveEnv 自动决定，勿直接手写此处）
  baseUrl: active.baseUrl,
  // 当前环境标识，便于运行时排查（dev / prod）
  env: resolveEnv(),

  // API 端点
  endpoints: {
    wechatLogin: '/auth/wechat-login',
    wechatBind: '/auth/wechat-bind',
    login: '/auth/login',
    verify: '/auth/verify',
    logout: '/auth/logout',
    todaySummary: '/dashboard/today-summary',
    overview: '/dashboard/overview',
    analyze: '/analysis/analyze',
    analyzeStream: '/analysis/analyze-stream',
    history: '/analysis/history',
    share: '/analysis/share',
    sessionCreate: '/session/create',
    feedback: '/feedback/submit',
    contactFeedback: '/feedback/contact',
  },

  // 本地存储键
  storageKeys: {
    token: 'token',
    userInfo: 'userInfo',
    recentSessions: 'recentSessions',
  },

  // SSE 事件类型
  sseEvents: {
    PHASE: 'phase',
    STEP: 'step',
    DONE: 'done',
    ERROR: 'error',
  },

  // 流式开关：微信 enableChunked 在开发者工具/部分真机不稳定（移动端方案 §3.3 预判风险）
  // true  = 走 /analyze-stream（有实时进度，但环境不稳可能卡死）
  // false = 走同步 /analyze（可靠，V1.0 默认）
  // 真机压测稳定后可切 true 体现「实时」卖点。
  streamEnabled: false,
};

module.exports = config;
