import { useMemo, useState } from 'react';

/* Intro 欢迎页（对齐原生 intro-overlay：品牌 + 统计 + 进入系统按钮） */
export default function Intro({ onEnter }: { onEnter: () => void }) {
  const [phase, setPhase] = useState<'show' | 'fade'>('show');

  /* 粒子参数一次性生成（对齐原生 initIntroParticles：20 个、2-5px、透明度 0.2-0.5、6-14s 周期、0-5s 延迟） */
  const particles = useMemo(() => Array.from({ length: 20 }, () => ({
    left: Math.random() * 100,
    top: Math.random() * 100,
    size: 2 + Math.random() * 3,
    opacity: 0.2 + Math.random() * 0.3,
    duration: 6 + Math.random() * 8,
    delay: Math.random() * 5,
  })), []);

  const enter = () => {
    setPhase('fade');
    setTimeout(onEnter, 500);
  };

  return (
    <div
      onClick={enter}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999, cursor: 'pointer',
        background: 'radial-gradient(ellipse at 50% 30%, #1e1e4a 0%, #15152e 55%, #0f0f22 100%)',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        textAlign: 'center', transition: 'opacity .5s ease', opacity: phase === 'show' ? 1 : 0,
        pointerEvents: phase === 'show' ? 'auto' : 'none',
      }}
    >
      {/* 动态渐变动画（对齐原生 intro：gridMove 网格平移 / glow 呼吸 / 粒子上升 / fadeInUp 错峰入场）
          统一 intro 前缀命名，避免与全局（语音按钮 pulse 等）同名 keyframes 冲突 */}
      <style>{`
        @keyframes introGridMove{0%{transform:translate(0,0)}100%{transform:translate(44px,44px)}}
        @keyframes introGlow{0%,100%{transform:translate(-50%,-50%) scale(1);opacity:.6}50%{transform:translate(-50%,-50%) scale(1.1);opacity:1}}
        @keyframes introFloatUp{0%{transform:translateY(110vh) scale(0);opacity:0}10%{opacity:1}90%{opacity:1}100%{transform:translateY(-10vh) scale(1);opacity:0}}
        @keyframes introFadeInUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
        @keyframes introFadeIn{from{opacity:0}to{opacity:1}}
        .intro-badge{opacity:0;animation:introFadeInUp .6s ease .2s forwards}
        .intro-title{opacity:0;animation:introFadeInUp .8s ease .5s forwards}
        .intro-subtitle{opacity:0;animation:introFadeInUp .8s ease .8s forwards}
        .intro-stats{opacity:0;animation:introFadeInUp .8s ease 1.1s forwards}
        .intro-cta{opacity:0;animation:introFadeInUp .8s ease 1.4s forwards}
        .intro-version{opacity:0;animation:introFadeIn 1s ease 1.5s forwards}
        @media(max-width:768px){
          .intro-title{font-size:36px !important;letter-spacing:1px !important}
          .intro-subtitle{font-size:18px !important;letter-spacing:4px !important;margin-bottom:36px !important}
          .intro-stat-num{font-size:32px !important}
          .intro-stat-label{font-size:12px !important}
          .intro-cta{padding:12px 36px !important;font-size:16px !important;margin-top:40px !important}
          .intro-stats{gap:24px !important;margin-top:36px !important}
          .intro-glow{width:300px !important;height:300px !important}
          .intro-particles{display:none !important}
        }
      `}</style>

      {/* 背景网格（60s 无感平移，44px 网格配 44px 位移无缝循环） */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.15,
        backgroundImage: 'linear-gradient(rgba(99,102,241,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.4) 1px, transparent 1px)',
        backgroundSize: '44px 44px',
        animation: 'introGridMove 20s linear infinite',
      }} />

      {/* 呼吸光晕（对齐原生 intro-glow） */}
      <div className="intro-glow" style={{
        position: 'absolute', width: 600, height: 600, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%)',
        top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
        animation: 'introGlow 3s ease-in-out infinite',
      }} />

      {/* 上升粒子（对齐原生 initIntroParticles：20 个随机尺寸/透明度/速度） */}
      <div className="intro-particles" style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
        {particles.map((p, i) => (
          <div key={i} style={{
            position: 'absolute', width: p.size, height: p.size, borderRadius: '50%',
            background: `rgba(99,102,241,${p.opacity})`,
            left: `${p.left}%`, top: `${p.top}%`,
            animation: `introFloatUp ${p.duration}s linear infinite`,
            animationDelay: `${p.delay}s`,
          }} />
        ))}
      </div>

      {/* 品牌 */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px' }}>
        <div className="intro-badge" style={{
          display: 'inline-block', fontSize: 14, letterSpacing: 4, color: '#60a5fa',
          border: '1px solid rgba(99,102,241,0.5)', borderRadius: 999, padding: '7px 24px', marginBottom: 26,
        }}>AI 经营分析平台</div>
        {/* 标题渐变文字（对齐原生 intro-title：白→浅蓝→蓝，background-clip: text） */}
        <div className="intro-title" style={{
          fontSize: 72, fontWeight: 700, letterSpacing: 2, lineHeight: 1.1,
          background: 'linear-gradient(135deg,#fff 0%,#93c5fd 50%,#3b82f6 100%)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text',
        }}>
          Enterprise Insight Agent
        </div>
        <div className="intro-subtitle" style={{ fontSize: 28, color: '#94a3b8', fontWeight: 300, letterSpacing: 8, marginTop: 18 }}>
          V5.0 收官版正式发布
        </div>

        {/* 4 个统计（对齐原生 intro-stats） */}
        <div className="intro-stats" style={{ display: 'flex', gap: 48, justifyContent: 'center', flexWrap: 'wrap', marginTop: 44 }}>
          {[
            { num: '11', label: 'AI AGENT' },
            { num: '5', label: '业务域' },
            { num: 'SQL', label: '全链路追溯' },
            { num: '60s', label: '生成报告' },
          ].map((s) => (
            <div key={s.label}>
              <div className="intro-stat-num" style={{ fontSize: 48, fontWeight: 700, color: '#3b82f6', lineHeight: 1 }}>{s.num}</div>
              <div className="intro-stat-label" style={{ fontSize: 14, color: '#64748b', letterSpacing: 2, marginTop: 8 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* 进入系统 */}
        <button className="intro-cta" onClick={enter} style={{
          marginTop: 52, padding: '13px 56px', fontSize: 18, fontWeight: 600, letterSpacing: 2, color: '#fff',
          background: 'linear-gradient(135deg, #6366f1, #4f46e5)', border: 'none', borderRadius: 12,
          cursor: 'pointer', transition: 'transform .15s, box-shadow .15s',
          boxShadow: '0 8px 30px rgba(99,102,241,0.35)',
        }}>进入系统</button>

        {/* 底部版本行 */}
        <div className="intro-version" style={{ fontSize: 14, color: '#475569', letterSpacing: 2, marginTop: 46 }}>React 18 · FastAPI · LangGraph · ECharts 5</div>
      </div>
    </div>
  );
}
