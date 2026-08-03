# 企业经营助手 — 微信小程序

> Demo 版本 V1.0 · 面向连锁零售的 AI 经营分析移动端

---

## 目录结构

```
miniprogram/
├── app.js / app.json / app.wxss     # 小程序入口 + 全局配置
├── project.config.json              # 微信开发者工具项目配置
├── sitemap.json                     # 页面索引配置
├── pages/
│   ├── login/                       # 登录页（微信一键登录）
│   ├── bind/                        # 绑定页（首次绑定系统账号）
│   ├── home/                        # 首页（今日快报 + 经营看板）
│   ├── chat/                        # AI 问数页（SSE 流式对话）
│   └── mine/                        # 我的页
├── pages_ai/                        # AI 分包
│   └── report-full/                 # 报告详情页（Markdown 渲染 + 反馈）
├── pages_share/                     # 分享分包
│   └── share/                       # 分享落地页
├── utils/
│   ├── config.js                    # 全局配置 + API 端点
│   ├── request.js                   # 网络请求拦截器（JWT 自动注入）
│   ├── sse.js                       # SSE 流式请求解析器
│   └── util.js                      # 通用工具函数
└── miniprogram_npm/
    └── tdesign-miniprogram/         # 轻量 TDesign 风格组件
        ├── icon/                    # 图标组件
        └── tag/                     # 标签组件
```

---

## 快速开始

### 1. 前置条件

- 安装 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
- 启动后端服务（V4 端口 8002）
- 确保 PostgreSQL 运行

### 2. 导入项目

1. 打开微信开发者工具
2. 点击「导入项目」，目录选择 `miniprogram/` 文件夹
3. AppID 选择「测试号」（已配置为 `touristappid`）
4. 项目名称填「企业经营助手」

### 3. 开启本地调试

1. 开发者工具右上角 → 详情 → 本地设置
2. ✅ 勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」
3. 确保 `utils/config.js` 中 `baseUrl` 指向正确的后端地址（默认 `http://localhost:8002/api/v1`）

### 4. 启动后端

```bash
# 确保已安装依赖
pip install -e ".[dev]"

# 运行数据库迁移
alembic upgrade head

# 启动服务
uvicorn app.api.main:app --host 0.0.0.0 --port 8002 --reload
```

### 5. 登录测试

1. 打开小程序，点击「微信一键登录」
2. 首次使用需绑定：输入 `admin / admin123`
3. 绑定成功后进入首页

---

## 核心功能说明

### 🔐 登录流程

```
用户点击登录 → wx.login() 获取 code
  → POST /api/v1/auth/wechat-login {code}
  → 后端 Demo 模式：hash(code) 生成 openid
  → 已绑定 → 返回 JWT，直接进入首页
  → 未绑定 → 返回 4021，跳转绑定页
  → 绑定页输入 admin/admin123 → POST /api/v1/auth/wechat-bind
  → 绑定成功 → 返回 JWT，跳转首页
```

### 💬 AI 问数（SSE 流式）

```
用户输入问题 → POST /api/v1/analysis/analyze-stream
  → 启用 enableChunked: true
  → 手动解析 SSE 帧（data: {...}\n\n）
  → 按事件类型分发：
    - type: "phase"   → 9 步进度条更新
    - type: "step"    → 节点完成标记
    - type: "done"    → 完整报告渲染
    - type: "error"   → 错误提示
```

### 🏠 首页视图切换

- **今日快报**：红绿灯告警卡片 + 销售指标 + 趋势图 + Top5 门店
- **经营看板**：区域销售占比 + 退款率监控

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/auth/wechat-login` | POST | 微信一键登录（code → JWT） |
| `/auth/wechat-bind` | POST | 绑定微信账号到系统账号 |
| `/auth/verify` | GET | 验证 Token 有效性 |
| `/dashboard/today-summary` | GET | 获取今日经营快报 |
| `/dashboard/overview` | GET | 获取经营看板数据 |
| `/analysis/analyze` | POST | 同步分析（降级方案） |
| `/analysis/analyze-stream` | POST | SSE 流式分析 |
| `/analysis/history` | GET | 历史分析记录 |
| `/analysis/share/{token}` | GET | 分享落地页数据 |
| `/feedback/submit` | POST | 用户反馈提交 |

---

## 设计规范

### 色彩系统

| 用途 | 色值 | 说明 |
|------|------|------|
| 主色 | `#1A73E8` | 品牌蓝、按钮、链接 |
| 成功 | `#30D158` | 绿灯、正向指标 |
| 警告 | `#FF9500` | 黄灯、注意项 |
| 危险 | `#FF3B30` | 红灯、危险指标 |
| 背景 | `#F5F5F7` | 页面背景 |
| 卡片 | `#FFFFFF` | 卡片背景 |
| 主文字 | `#1D1D1F` | 标题、正文 |
| 次文字 | `#86868B` | 说明、辅助信息 |

### 字体规范

- 标题：36-40rpx / font-weight: 600-700
- 正文：28-30rpx / font-weight: 400-500
- 辅助：24-26rpx / font-weight: 400

### 圆角规范

- 大卡片：24rpx
- 卡片：20rpx
- 按钮：12-16rpx
- 标签：8rpx

---

## 分包策略

| 包 | 页面 | 大小控制 |
|----|------|----------|
| 主包 | login, bind, home, chat, mine | < 500KB |
| pages_ai | report-full | 按需加载 |
| pages_share | share | 按需加载 |

> 分包确保主包体积 < 500KB，满足微信小程序提交审核要求。

---

## 开发注意事项

1. **Demo 模式**：未配置 `WECHAT_APPID` 时，后端使用 code 的 hash 作为 openid，方便测试
2. **域名配置**：生产环境需在微信后台配置 HTTPS 合法域名
3. **Token 存储**：使用 `wx.setStorageSync` 存储，key 为 `token`
4. **路由守卫**：401 响应自动清除 Token 并跳转登录页
5. **错误处理**：网络请求失败自动 Toast 提示，支持下拉刷新重试

---

## 常见问题

**Q: 登录提示"微信账号未绑定系统账号"？**
A: 首次使用请点击"绑定系统账号"，输入 admin/admin123 完成绑定。

**Q: 页面数据为空？**
A: 请确认后端服务已启动（`http://localhost:8002`），且种子数据已导入（`python scripts/seed_data.py`）。

**Q: AI 问数无响应？**
A: 检查后端 DeepSeek API Key 是否配置正确，查看后端日志是否有错误。

**Q: 如何切换到真实微信模式？**
A: 在 `.env` 中配置 `WECHAT_APPID` 和 `WECHAT_SECRET` 即可切换到真实微信 API 模式。

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-07-31 | 初始版本，支持登录、首页快报、AI 问数、报告查看、分享 |
