import { useState } from 'react';

/* Intro 欢迎页（对齐原生 intro-overlay：品牌 + 统计 + 进入系统按钮） */
export default function Intro({ onEnter }: { onEnter: () => void }) {
  const [phase, setPhase] = useState<'show' | 'fade'>('show');

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
      {/* 移动端缩放（对齐原生 768px 断点） */}
      <style>{`
        @media(max-width:768px){
          .intro-title{font-size:36px !important;letter-spacing:1px !important}
          .intro-subtitle{font-size:18px !important;letter-spacing:4px !important;margin-bottom:36px !important}
          .intro-stat-num{font-size:32px !important}
          .intro-stat-label{font-size:12px !important}
          .intro-cta{padding:12px 36px !important;font-size:16px !important;margin-top:40px !important}
          .intro-stats{gap:24px !important;margin-top:36px !important}
        }
      `}</style>
      {/* 背景网格 */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.15,
        backgroundImage: 'linear-gradient(rgba(99,102,241,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.4) 1px, transparent 1px)',
        backgroundSize: '44px 44px',
      }} />

      {/* 品牌 */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px' }}>
        <div className="intro-badge" style={{
          display: 'inline-block', fontSize: 14, letterSpacing: 4, color: '#60a5fa',
          border: '1px solid rgba(99,102,241,0.5)', borderRadius: 999, padding: '7px 24px', marginBottom: 26,
        }}>AI 经营分析平台</div>
        <div className="intro-title" style={{ fontSize: 72, fontWeight: 700, letterSpacing: 2, color: '#fff', lineHeight: 1.1 }}>
          Enterprise Insight Agent
        </div>
        <div className="intro-subtitle" style={{ fontSize: 28, color: '#94a3b8', fontWeight: 300, letterSpacing: 8, marginTop: 18 }}>
          V4.6 正式发布
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
