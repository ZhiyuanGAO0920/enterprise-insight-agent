"""V4 Demo 自动录制 v3 — 严格按 docs/Demo视频脚本-V4.md 执行。

新特性：
  - 虚拟鼠标光标（红色圆点 + 点击波纹）
  - 关键步骤画面文字标注（彩色标签）
  - SRT 字幕文件自动生成（demo_output/demo_v4.srt）

输出: demo_output/
  demo_v4.webm         完整流程视频
  demo_v4.srt          旁白字幕文件
  v4_*.png             各阶段截图
  v2/v3_screenshot.png 版本对比
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "demo_output"
OUTPUT_DIR.mkdir(exist_ok=True)

V4_PORT, V3_PORT, V2_PORT = 8002, 8001, 8000

# ======================================================================
# SRT 字幕数据 — 9 段时间戳 + 旁白内容
# ======================================================================
SRT_SEGMENTS = [
    # (start_sec, end_sec, text)
    (0, 10, "Enterprise Insight Agent V4 —— 10 个 AI Agent\n5 个业务域、Docker 一键部署的企业经营分析平台"),
    (10, 30, "连锁零售企业每天面对几十家门店、上万笔订单\nV4 用中文提问，60 秒拿到带图表的诊断报告"),
    (30, 70, "输入 admin 账号登录。V4 支持多租户、RBAC 角色权限\n行级门店数据隔离，不同角色看到的数据范围完全不同"),
    (70, 100, "登录后默认进入经营看板。6 个 KPI 卡片带环比箭头\n近 30 天趋势图、区域占比、门店 Top 10，按用户权限自动过滤"),
    (100, 150, "查询型问题：上个月销售额最高的三家门店\n11 步流式进度条实时推送。新建会话清空对话\n每条报告底部有点赞点踩反馈按钮"),
    (150, 230, "核心演示：华东区销售为什么下降\nSupervisor 按需激活多个领域 Agent 并行执行（进度条如实展示）\nReflection 四维质检确保报告质量"),
    (230, 280, "综合经营分析：销售、会员、库存跨维度交叉验证\n多轮对话追问，报告底部有追问建议按钮"),
    (280, 330, "V4 独有亮点：PDF 导出、退出登录、角色快捷问题\nzhangsan 登录验证数据隔离——华东 22 店 vs 全量"),
    (330, 380, "V2 到 V4 版本演进：3 个 Agent → 10 个 Agent\n无流式 → 11 步流式进度，无看板 → 经营看板\nDocker 一键部署，5 个容器 2 分钟跑起来"),
    (380, 390, "代码已开源。我是高志远，欢迎 Star 和联系"),
]


def generate_srt(segments, output_path: Path):
    """将字幕片段写入 SRT 文件。"""
    def fmt(sec: float) -> str:
        h, m = divmod(int(sec), 3600)
        m, s = divmod(m, 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, (start, end, text) in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{fmt(start)} --> {fmt(end)}")
        lines.append(text.replace("\n", "\n"))
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  SRT: {output_path} ({len(segments)} segments)")


# ======================================================================
# 画面标注辅助函数
# ======================================================================

async def inject_cursor(page):
    """注入虚拟鼠标光标（红色圆点 + 点击波纹），跟随 Playwright 鼠标位置。"""
    await page.add_style_tag(content="""
        #__demo_cursor {
            position: fixed; z-index: 99999; pointer-events: none;
            width: 18px; height: 18px; border-radius: 50%;
            background: rgba(239,68,68,0.85);
            box-shadow: 0 0 8px rgba(239,68,68,0.5);
            transform: translate(-50%, -50%);
            transition: left 0.08s linear, top 0.08s linear;
        }
        #__demo_cursor.clicking {
            animation: clickPulse 0.3s ease-out;
        }
        @keyframes clickPulse {
            0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.8); }
            100% { box-shadow: 0 0 0 20px rgba(239,68,68,0); }
        }
    """)
    await page.evaluate("""() => {
        const c = document.createElement('div');
        c.id = '__demo_cursor';
        document.body.appendChild(c);
    }""")
    # 持续跟踪鼠标位置
    await page.evaluate("""() => {
        document.addEventListener('mousemove', e => {
            const c = document.getElementById('__demo_cursor');
            if (c) { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }
        });
    }""")


async def show_annotation(page, text: str, color: str = "#6366f1", duration_ms: int = 3000):
    """顶部居中标注，醒目但不遮挡。"""
    await page.evaluate("""
        ([text, color, duration]) => {
            const el = document.createElement('div');
            el.textContent = text;
            el.style.cssText = 'position:fixed;top:100px;left:50%;transform:translateX(-50%);'
                + 'z-index:99998;padding:8px 22px;border-radius:8px;'
                + 'background:' + color + ';color:#fff;font-size:16px;font-weight:600;'
                + 'letter-spacing:2px;pointer-events:none;opacity:0;'
                + 'transition:opacity 0.3s;white-space:nowrap;'
                + 'box-shadow:0 4px 16px rgba(0,0,0,.3);font-family:system-ui;';
            document.body.appendChild(el);
            requestAnimationFrame(() => { el.style.opacity = '0.92'; });
            setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, duration);
        }
    """, [text, color, duration_ms])


async def keep_intro_visible(page):
    """V4.6+ 兼容：阻止欢迎页 5 秒后自动跳转登录，保持欢迎页可见供演示点击。

    index.html 内联脚本在无 token 时 5s 后自动调用 showLogin() 隐藏欢迎页，
    录制需要欢迎页停留以演示「点击进入系统」，故暂时将 showLogin 替换为空操作，
    并把原函数存到 __origShowLogin；段 3 完成跳转后调用 restore_intro_auto 恢复
    （logout() 内部依赖 showLogin 显示登录页，不能长期禁用）。
    本方法不跨导航保留，仅用于首次加载后的欢迎页阶段。
    """
    try:
        await page.evaluate("""() => {
            if (!window.__demoShowLoginPatched) {
                window.__origShowLogin = window.showLogin;
                window.showLogin = function(){};
                window.__demoShowLoginPatched = true;
            }
        }""")
    except Exception:
        pass  # 页面未就绪时忽略，自动跳转兜底不影响后续流程


async def restore_intro_auto(page):
    """恢复原始 showLogin（logout 依赖它显示登录页）。"""
    try:
        await page.evaluate("""() => {
            if (window.__origShowLogin) {
                window.showLogin = window.__origShowLogin;
            }
        }""")
    except Exception:
        pass


async def move_mouse_smooth(page, x: int, y: int, steps: int = 15):
    """平滑移动鼠标到目标位置。"""
    current = await page.evaluate("() => ({x: window.__demo_mx || 500, y: window.__demo_my || 300})")
    # 更新跟踪变量
    await page.evaluate(f"() => {{ window.__demo_mx = {x}; window.__demo_my = {y}; }}")
    for i in range(1, steps + 1):
        t = i / steps
        ix = int(current["x"] + (x - current["x"]) * t)
        iy = int(current["y"] + (y - current["y"]) * t)
        await page.mouse.move(ix, iy)
        await asyncio.sleep(0.01)


async def click_with_animation(page, selector: str | None = None, x: int | None = None, y: int | None = None):
    """点击元素或坐标，带波纹动画。"""
    if selector:
        box = await page.locator(selector).bounding_box()
        if box:
            x = int(box["x"] + box["width"] / 2)
            y = int(box["y"] + box["height"] / 2)
    if x is not None and y is not None:
        await move_mouse_smooth(page, x, y)
        await page.evaluate("""() => {
            const c = document.getElementById('__demo_cursor');
            if (c) { c.classList.add('clicking'); setTimeout(() => c.classList.remove('clicking'), 300); }
        }""")
        await page.mouse.click(x, y)
    elif selector:
        await page.click(selector)


async def type_with_cursor(page, selector: str, text: str, delay_ms: int = 80):
    """逐字输入（先清空），同时鼠标停留在输入框上。"""
    await click_with_animation(page, selector=selector)
    await page.fill(selector, "")
    await page.type(selector, text, delay=delay_ms)


async def wait_for_analysis_complete(page, timeout_sec: float = 120):
    """等待分析完成：#pM 进度面板从 DOM 移除（被 analysis done 事件 remove 掉）。"""
    try:
        await page.wait_for_selector("#pM", state="attached", timeout=15000)
        await page.wait_for_selector("#pM", state="detached", timeout=timeout_sec * 1000)
    except Exception:
        pass
    await asyncio.sleep(2)
    try:
        await page.wait_for_selector(".msg.assistant .bubble.stream-content", state="attached", timeout=timeout_sec * 1000)
    except Exception:
        pass


async def screenshot(page, name: str):
    """截图到 demo_output/"""
    await page.screenshot(path=str(OUTPUT_DIR / name), full_page=False)
    print(f"  [shot] {name}")


# ======================================================================
# 9 段 Demo 录制
# ======================================================================

async def record_demo(page, port: int):
    v4 = f"http://localhost:{port}"

    # 初始化鼠标位置
    await page.evaluate("() => { window.__demo_mx = 960; window.__demo_my = 540; }")
    await inject_cursor(page)

    # ============================================================
    # 段 1：片头 + 欢迎页 (0:00-0:15)
    # ============================================================
    print("\n[1/9] Welcome + intro page...")
    await page.goto(v4, wait_until="networkidle")
    await keep_intro_visible(page)
    await page.wait_for_selector("#introOverlay", timeout=10000)
    await asyncio.sleep(2)
    await show_annotation(page, "10 AI Agent · 5 业务域 · Docker 一键部署", "#6366f1", 4000)
    await asyncio.sleep(3)
    await screenshot(page, "v4_intro.png")

    # ============================================================
    # 段 2：问题场景还原 (0:15-0:40) — 旁白
    # ============================================================
    print("[2/9] Problem scenario (narration)...")
    await show_annotation(page, '用中文提问，60 秒拿到带图表的经营报告', "#f59e0b", 5000)
    await asyncio.sleep(5)

    # ============================================================
    # 段 3：登录 + 多角色权限 (0:40-1:20)
    # ============================================================
    print("[3/9] Login as admin...")

    # 鼠标移到「进入系统」并点击
    await click_with_animation(page, selector=".intro-cta")
    await asyncio.sleep(0.8)
    await page.wait_for_selector("#loginOverlay", state="visible", timeout=5000)
    await restore_intro_auto(page)  # 恢复 showLogin（logout 依赖它）
    await show_annotation(page, "多租户 · RBAC 角色权限 · 行级数据隔离", "#10b981", 4000)
    await asyncio.sleep(1)

    # 逐字输入 admin
    await type_with_cursor(page, "#loginUser", "admin", delay_ms=100)
    await asyncio.sleep(0.3)
    # 逐字输入 admin123
    await type_with_cursor(page, "#loginPass", "admin123", delay_ms=80)
    await asyncio.sleep(0.3)

    # 点击登录
    await click_with_animation(page, selector="#loginBtn")
    await page.wait_for_selector("#dashKpis", state="attached", timeout=15000)
    await asyncio.sleep(5)  # 等待 switchTab('dashboard') 完成 + ECharts 渲染

    # 展开管理面板
    await click_with_animation(page, selector="#adminNavBtn")
    await asyncio.sleep(2)
    await screenshot(page, "v4_admin_panel.png")
    await click_with_animation(page, selector=".ap-close")
    await asyncio.sleep(0.5)

    # ============================================================
    # 段 4：经营看板 (1:20-1:45)
    # ============================================================
    print("[4/9] Dashboard...")
    await show_annotation(page, "6 个 KPI · 环比箭头 · 30 天趋势 · 区域占比 · 门店 Top 10", "#8b5cf6", 5000)
    await asyncio.sleep(3)
    await screenshot(page, "v4_dashboard.png")
    await asyncio.sleep(2)

    # ============================================================
    # 段 5：查询型问题 (1:45-2:25)
    # ============================================================
    print("[5/9] Query: top 3 stores...")
    await click_with_animation(page, selector=".nav-item[data-tab='analysis']")
    await asyncio.sleep(0.5)
    await show_annotation(page, "查询型问题：直接给数据，避免信息过载", "#f59e0b", 3000)
    await asyncio.sleep(0.5)

    await type_with_cursor(page, "#question", "上个月销售额最高的三家门店", delay_ms=60)
    await asyncio.sleep(0.3)
    await screenshot(page, "v4_query_input.png")

    await click_with_animation(page, selector="#btn")
    await show_annotation(page, "7 步全自动 · 流式进度实时推送", "#6366f1", 3000)
    await wait_for_analysis_complete(page, timeout_sec=60)
    await asyncio.sleep(1)
    await screenshot(page, "v4_query_result.png")

    # --- 新建会话 + 反馈演示 ---
    await show_annotation(page, "新建会话：清空对话，重新开始", "#10b981", 2000)
    await asyncio.sleep(0.5)
    # 点击侧边栏「＋ 新建会话」
    await click_with_animation(page, selector=".btn-new-session")
    await asyncio.sleep(1)

    # 第二个查询：退款率
    await type_with_cursor(page, "#question", "退款率最高的门店", delay_ms=60)
    await asyncio.sleep(0.3)
    await click_with_animation(page, selector="#btn")
    await wait_for_analysis_complete(page, timeout_sec=60)
    await asyncio.sleep(1)

    # 点击 👍 反馈按钮
    await page.evaluate("() => { const c = document.getElementById('chat'); if(c) c.scrollTop = c.scrollHeight; }")
    await asyncio.sleep(0.5)
    await show_annotation(page, "用户反馈：👍👎 评价分析质量", "#f59e0b", 2000)
    try:
        await click_with_animation(page, selector=".feedback-btn")
        await asyncio.sleep(0.5)
        # 填写反馈内容
        feedback_box = page.locator("#feedbackText")
        if await feedback_box.count() > 0:
            await feedback_box.fill("数据准确，分析维度完整")
            await asyncio.sleep(0.3)
            await click_with_animation(page, selector=".btn-submit")
            await asyncio.sleep(1)
    except Exception:
        pass

    # ============================================================
    # 段 6：分析型问题 ★ 核心 (2:25-3:45)
    # ============================================================
    print("[6/9] Analysis: East China sales decline...")

    await type_with_cursor(page, "#question",
        "最近30天华东区销售为什么下降了？分析具体原因并给出改进建议", delay_ms=45)
    await asyncio.sleep(0.3)

    await click_with_animation(page, selector="#btn")
    await show_annotation(page, "3 Agent 并行执行 · LangGraph Send 扇出", "#ef4444", 4000)
    await asyncio.sleep(4)
    await show_annotation(page, "领域 Agent 并行查数据库 · 按需激活", "#f59e0b", 4000)
    await asyncio.sleep(4)
    await show_annotation(page, "Reflection 4 维质检：一致性 / 逻辑 / 可操作 / 完整", "#10b981", 4000)

    await wait_for_analysis_complete(page, timeout_sec=120)
    await asyncio.sleep(2)
    await screenshot(page, "v4_report.png")

    # 滚动到底部看反馈按钮
    await page.evaluate("() => { const c = document.getElementById('chat'); if(c) c.scrollTop = c.scrollHeight; }")
    await asyncio.sleep(1)
    await screenshot(page, "v4_feedback.png")
    await show_annotation(page, "👍👎 反馈 · SQL 溯源 · 追问建议 · PDF 导出", "#8b5cf6", 4000)

    # ============================================================
    # 段 7：综合经营分析 (3:45-4:40)
    # ============================================================
    print("[7/9] Comprehensive analysis...")
    await type_with_cursor(page, "#question", "分析最近一周的整体经营情况，涵盖销售、会员、库存", delay_ms=45)
    await asyncio.sleep(0.3)

    await click_with_animation(page, selector="#btn")
    await show_annotation(page, "按需激活：多领域 Agent 交叉验证", "#6366f1", 4000)
    await wait_for_analysis_complete(page, timeout_sec=120)
    await asyncio.sleep(1)

    # ============================================================
    # 段 8：V4 独有亮点 (4:40-5:15)
    # ============================================================
    print("[8/9] Feature highlights...")

    # PDF
    await page.evaluate("() => { const c = document.getElementById('chat'); if(c) c.scrollTop = c.scrollHeight; }")
    await asyncio.sleep(0.5)
    try:
        pdf_btn = page.locator("span.share-btn").first
        await pdf_btn.click()
        await asyncio.sleep(1.5)
        await show_annotation(page, "一键 PDF 导出 · 自动降级 Markdown", "#10b981", 2500)
    except Exception:
        pass
    await asyncio.sleep(1)

    # 退出登录
    await click_with_animation(page, selector="#userMenuBtn")
    await asyncio.sleep(0.5)
    await page.click("text=退出登录")
    await asyncio.sleep(1)
    await page.wait_for_selector("#loginOverlay", state="visible", timeout=5000)
    await show_annotation(page, "JWT 持久化 · 刷新自动恢复 · 退出注销令牌", "#f59e0b", 3000)
    await asyncio.sleep(2)

    # zhangsan 登录验证数据隔离
    # 退出后刷新回到欢迎页（introOverlay），再点击进入系统
    # 注意：此处不打 keep_intro_visible 补丁——点击在 5s 自动跳转窗口内，
    # 且保留自动跳转作为兜底（即使点击错过窗口，登录页也会在 5s 自动出现）
    await page.goto(f"http://localhost:{port}", wait_until="networkidle", timeout=10000)
    await asyncio.sleep(1)
    await page.wait_for_selector("#introOverlay", state="visible", timeout=5000)
    await click_with_animation(page, selector=".intro-cta")
    await asyncio.sleep(0.8)
    await page.wait_for_selector("#loginOverlay", state="visible", timeout=5000)
    await asyncio.sleep(0.3)

    await type_with_cursor(page, "#loginUser", "zhangsan", delay_ms=100)
    await asyncio.sleep(0.2)
    await type_with_cursor(page, "#loginPass", "admin123", delay_ms=80)
    await asyncio.sleep(0.2)
    await click_with_animation(page, selector="#loginBtn")
    # state="visible"：真实验证登录成功（attached 在隐藏的 #app 容器里也会命中）
    await page.wait_for_selector("#dashKpis", state="visible", timeout=15000)
    await asyncio.sleep(4)
    await show_annotation(page, "zhangsan 华东区域经理 · 只看到华东 22 店 · 数据隔离", "#ef4444", 4000)
    await asyncio.sleep(2)
    await screenshot(page, "v4_zhangsan_dashboard.png")

    # ============================================================
    # 段 9：V2→V3→V4 逐项对比 (5:20-6:20)
    # ============================================================
    print("[9/9] Version comparison tour...")

    # --- V2 (8000) ---
    try:
        await page.goto(f"http://localhost:{V2_PORT}", wait_until="networkidle", timeout=10000)
        await asyncio.sleep(2)
        await show_annotation(page, "V2 (2024)：3 Agent · 无看板 · 无流式 · 无图表 · pip install", "#94a3b8", 3000)
        await asyncio.sleep(1)
        await screenshot(page, "v2_home.png")
        # V2 login: 等待账号卡片渲染后点击 admin 卡片，再提交表单，等待弹窗消失
        try:
            await page.wait_for_selector("#acct-admin", state="visible", timeout=5000)
            await page.click("#acct-admin")
            await asyncio.sleep(0.3)
            await page.click("#loginForm button[type='submit']")
            await page.wait_for_selector("#loginOverlay", state="hidden", timeout=8000)
            await asyncio.sleep(1)
            await screenshot(page, "v2_chat.png")
            await show_annotation(page, "V2 登录后：直接进聊天页，无看板无进度条", "#94a3b8", 3000)
        except Exception as e:
            print(f"  V2 login failed: {e}")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  V2 failed: {e}")

    # --- V3 (8001) ---
    try:
        await page.goto(f"http://localhost:{V3_PORT}", wait_until="networkidle", timeout=10000)
        await asyncio.sleep(2)
        await show_annotation(page, "V3 (2025)：8 Agent · 基础图表 · 多轮对话 · 仍无看板", "#64748b", 3000)
        await asyncio.sleep(1)
        await screenshot(page, "v3_home.png")
        try:
            await page.fill("#loginUser", "admin")
            await page.fill("#loginPass", "admin123")
            await page.click("#loginForm button[type='submit']")
            await page.wait_for_selector("#loginOverlay", state="hidden", timeout=8000)
            await asyncio.sleep(1)
            await screenshot(page, "v3_chat.png")
            await show_annotation(page, "V3：有图表有对话，但无看板页、无流式进度", "#64748b", 3000)
        except Exception as e:
            print(f"  V3 login failed: {e}")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  V3 failed: {e}")

    # --- 回到 V4 展示对比表 ---
    await page.goto(f"http://localhost:{V4_PORT}", wait_until="networkidle", timeout=10000)
    await asyncio.sleep(1)
    # 快速登录（显式点击进入系统；5s 自动跳转兜底）
    try:
        await click_with_animation(page, selector=".intro-cta")
        await asyncio.sleep(0.8)
        await page.wait_for_selector("#loginOverlay", state="visible", timeout=5000)
        await page.fill("#loginUser", "admin")
        await page.fill("#loginPass", "admin123")
        await page.click("#loginBtn")
        await page.wait_for_selector("#dashKpis", state="visible", timeout=10000)
        await asyncio.sleep(3)
    except Exception:
        pass

    # 对比标注序列
    comparisons = [
        ("V2：3 Agent，直接登录弹窗", "#94a3b8"),
        ("V3：8 Agent，仍无欢迎页和看板", "#64748b"),
        ("V4：10 Agent，欢迎页 → 看板 → 流式进度 → 溯源 → 反馈", "#6366f1"),
        ("V4 独有：11 步流式进度条 · ECharts 5 种图表 · SQL 溯源面板", "#10b981"),
        ("V4 独有：经营看板 · 点赞反馈 · PDF 导出 · 取消分析", "#f59e0b"),
        ("V4 独有：角色快捷问题 · 会话持久化 · Docker 一键部署", "#ef4444"),
    ]
    for text, color in comparisons:
        await show_annotation(page, text, color, 2500)
        await asyncio.sleep(1.5)

    await screenshot(page, "v4_final.png")

    print("\nDemo recording complete!")


# ======================================================================
# 主函数
# ======================================================================

async def main():
    headless = "--headless" in sys.argv

    print("=" * 60)
    print("  V4 Demo Recorder v3 — mouse + captions + SRT")
    print(f"  Output: {OUTPUT_DIR}")
    print("=" * 60)

    # 生成 SRT
    generate_srt(SRT_SEGMENTS, OUTPUT_DIR / "demo_v4.srt")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(OUTPUT_DIR),
            record_video_size={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()

        try:
            await record_demo(page, V4_PORT)
        finally:
            await context.close()
            await browser.close()

            # 重命名视频
            for f in OUTPUT_DIR.glob("*.webm"):
                target = OUTPUT_DIR / "demo_v4.webm"
                try:
                    if target.exists():
                        target.unlink()
                    f.rename(target)
                    print(f"\nVideo: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
                except Exception as e:
                    print(f"\nVideo rename failed: {e}")

    print(f"\n=== Output ===")
    for f in sorted(OUTPUT_DIR.glob("*")):
        if f.is_file():
            print(f"  {f.name} ({f.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
