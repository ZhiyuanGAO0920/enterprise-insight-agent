// utils/config.js — 全局配置
const config = {
  // 后端 API 基础地址。开发阶段可通过微信开发者工具"不校验合法域名"开关使用本地地址
  // 真机测试：改成电脑的局域网 IP（ipconfig 查看，本机也能访问所以模拟器不受影响）
  // 生产环境需配置 HTTPS 域名到微信后台
  baseUrl: 'http://172.20.10.4:8002/api/v1',

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
  streamEnabled: false,
};

module.exports = config;
