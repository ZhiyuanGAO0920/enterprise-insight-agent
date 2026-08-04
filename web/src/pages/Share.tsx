import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';
import { buildEChartsOption, processReport } from '../lib/report';

/* ── 报告解析管线统一来自 src/lib/report.ts（与 Analysis.tsx 共用） ── */

/* ── 分享页正文的浅色排版样式 ── */
const MD_STYLE = `
  .share-md { color: #1e293b; font-size: 14px; line-height: 1.75; word-break: break-word; }
  .share-md h1 { font-size: 20px; margin: 18px 0 10px; }
  .share-md h2 { font-size: 17px; margin: 16px 0 8px; border-left: 3px solid #4f46e5; padding-left: 8px; }
  .share-md h3 { font-size: 15px; margin: 14px 0 6px; }
  .share-md table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
  .share-md th, .share-md td { border: 1px solid #e2e8f0; padding: 6px 10px; text-align: left; }
  .share-md th { background: #f8fafc; font-weight: 600; }
  .share-md code { background: #f1f5f9; border-radius: 4px; padding: 1px 5px; font-size: 12px; }
  .share-md a { color: #4f46e5; }
  .share-md strong { font-weight: 600; }
  @media print { .sh-header, .sh-question, .sh-footer { display: none !important; } .sh-container { margin: 0; } .sh-report { border: none !important; box-shadow: none !important; } }
`;

export default function SharePage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<{ question?: string; report?: string; create_time?: string } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) { setError('无效的分享链接'); return; }
    const controller = new AbortController();
    /* 15s 超时兜底：连接挂起时不再无限"正在加载" */
    const timer = window.setTimeout(() => controller.abort(), 15_000);
    fetch(`/api/v1/analysis/share/${encodeURIComponent(token)}`, { headers: { Accept: 'application/json' }, signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error('not found');
        return r.json();
      })
      .then(setData)
      .catch((e) => {
        setError(e?.name === 'AbortError' ? '加载超时，请稍后重试' : '分享链接不存在或已过期');
      })
      .finally(() => clearTimeout(timer));
    return () => { clearTimeout(timer); controller.abort(); };
  }, [token]);

  const { html, charts } = data?.report ? processReport(data.report) : { html: '', charts: [] };

  return (
    <div style={{ background: '#f4f6fb', minHeight: '100vh', fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif' }}>
      <style>{MD_STYLE}</style>

      {/* 头部 */}
      <div className="sh-header" style={{ background: 'linear-gradient(135deg,#2563eb,#4f46e5)', color: '#fff', padding: '28px 20px', textAlign: 'center' }}>
        <div style={{ fontSize: 14, opacity: 0.9, marginBottom: 6 }}>📊 企业洞察 Agent · 智能经营分析</div>
        <div style={{ fontSize: 20, fontWeight: 700 }}>经营分析报告分享</div>
      </div>

      <div className="sh-container" style={{ maxWidth: 860, margin: '24px auto 48px', padding: '0 16px' }}>
        {error ? (
          <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '48px 20px', textAlign: 'center', color: '#64748b' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🔗</div>
            <div>{error}</div>
            <div style={{ marginTop: 16, fontSize: 12, color: '#94a3b8' }}>如有疑问，请联系报告分享者重新生成链接</div>
          </div>
        ) : !data ? (
          <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '48px 20px', textAlign: 'center', color: '#64748b' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>⏳</div>
            <div>正在加载报告...</div>
          </div>
        ) : (
          <>
            {/* 问题 */}
            {data.question && (
              <div className="sh-question" style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '16px 20px', marginBottom: 16, fontSize: 15 }}>
                <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>📝 分析问题</div>
                {data.question}
              </div>
            )}

            {/* 报告 */}
            <div className="sh-report" style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '24px 28px' }}>
              {html && <div className="share-md" dangerouslySetInnerHTML={{ __html: html }} />}
              {charts.map((c, i) => (
                <div key={i} style={{ margin: '12px 0' }}>
                  <ReactECharts option={buildEChartsOption(c.type, c)} style={{ height: Math.min(c.height || 400, 600), maxWidth: '100%' }} notMerge />
                </div>
              ))}
              {data.create_time && (
                <div style={{ marginTop: 20, fontSize: 11, color: '#94a3b8', textAlign: 'right' }}>
                  生成时间：{new Date(data.create_time).toLocaleString('zh-CN')}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 页脚 */}
      <div className="sh-footer" style={{ maxWidth: 860, margin: '0 auto 40px', padding: '0 16px', fontSize: 11, color: '#94a3b8', textAlign: 'center', lineHeight: 1.8 }}>
        本报告由企业洞察 Agent 基于多 Agent 协作自动生成，仅供经营决策参考，数据与结论以实际业务为准。
        <br />© 企业洞察 Agent · AI 生成内容符合《生成式人工智能服务管理暂行办法》
      </div>
    </div>
  );
}
