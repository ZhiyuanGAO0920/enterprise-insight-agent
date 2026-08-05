import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Spin, DatePicker, Space, Typography } from 'antd';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
import client from '../api/client';
import { DARK } from '../theme';
import { fmtSec } from '../lib/format';

const { Title } = Typography;

/* ── Agent 中文名（对齐原生 lm） ── */
const AGENT_LABELS: Record<string, string> = {
  sales: '销售', crm: 'CRM', finance: '财务', inventory: '库存', supply_chain: '供应链',
  supervisor: '规划', aggregator: '聚合', chart_advisor: '图表', report: '报告', reflection: '质检',
  reflection_agent: '质检', save_memory: '记忆',
};

/* ── 错误信息中文映射（对齐原生 _errCn） ── */
const ERR_CN: Record<string, string> = {
  timeout: '超时', 'connection refused': '连接拒绝', 'deadline exceeded': '超时',
  refused: '拒绝', 'connection reset': '连接重置', closed: '连接关闭',
  eof: '连接断开', reset: '重置', 'timed out': '超时',
};

const PRESETS: Array<[string, string]> = [['7', '近7天'], ['30', '近30天'], ['month', '本月'], ['prevMonth', '上月'], ['custom', '自定义']];

const LEVEL = { ok: '#22c55e', warn: '#f59e0b', err: '#ef4444' };

interface OverviewData {
  period_days: number;
  total_analyses: number;
  reflection_pass_rate: number;
  // V4.6.3: 三态口径（未过/解析兜底），与离线评估对齐
  reflection_failed: number;
  reflection_fallback: number;
  feedback_helpful_rate: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  retry_rate: number;
  fix_rate: number;
  p50_duration_ms: number;
  p90_duration_ms: number;
  estimated_daily_cost: number;
  estimated_monthly_cost: number;
  agents: { agent: string; total_runs: number; error_count: number; error_rate: number; avg_ms: number; max_ms: number }[];
  token_trend?: { date: string; input_tokens: number; output_tokens: number; cost: number }[];
  health?: Record<string, string>;
}

interface ErrorRecord { time: string; agent: string; error: string; elapsed_ms: number; session: string; }
interface ErrorsData { errors: ErrorRecord[]; total_errors: number; }

/* 状态等级（对齐原生 good/warn/bad） */
function rateLevel(v: number, good: number, warn: number): { label: string; color: string } {
  if (v >= good) return { label: '优秀', color: LEVEL.ok };
  if (v >= warn) return { label: '良好', color: LEVEL.warn };
  return { label: '需关注', color: LEVEL.err };
}
function fmtTokens(v: number): string {
  return v >= 1000000 ? (v / 1000000).toFixed(1) + 'M' : v >= 1000 ? (v / 1000).toFixed(1) + 'K' : String(v);
}
function errIcon(msg: string): string {
  if (/timeout|超时|time.?out/i.test(msg)) return '⏱️';
  if (/SQL|sql|语法|column|table|relation/i.test(msg)) return '🗃️';
  return '⚠️';
}

export default function MonitorPage() {
  const [preset, setPreset] = useState('30');
  const [days, setDays] = useState(30);
  const [startDate, setStartDate] = useState<string | null>(null);
  const [endDate, setEndDate] = useState<string | null>(null);
  const [ov, setOv] = useState<OverviewData | null>(null);
  const [er, setEr] = useState<ErrorsData | null>(null);
  const [error, setError] = useState(false);
  const [customRange, setCustomRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const cacheRef = useRef<{ key: string; time: number; ov: OverviewData; er: ErrorsData } | null>(null);
  /* 切换到「自定义」时跳过本次 effect 触发，避免用旧 days 值（近30天）先发一次加载 */
  const skipLoadRef = useRef(false);

  const periodLabel = preset === 'prevMonth' ? '上月' : preset === 'month' ? '本月' : preset === '7' ? '近7天' : preset === '30' ? '近30天' : `近${days}天`;

  const load = useCallback(async (p: string, d: number, sd: string | null, ed: string | null) => {
    const key = `${p}_${d}_${sd}_${ed}`;
    // 30s 缓存（对齐原生 _cache 30000ms）
    if (cacheRef.current && cacheRef.current.key === key && Date.now() - cacheRef.current.time < 30000) {
      setOv(cacheRef.current.ov); setEr(cacheRef.current.er); return;
    }
    setError(false);
    try {
      const params: Record<string, unknown> = { days: Math.min(d, 90) };
      if (sd) params.start_date = sd;
      if (ed) params.end_date = ed;
      const [oRes, eRes] = await Promise.all([
        client.get('/monitor/overview', { params }),
        client.get('/monitor/errors', { params: { days: Math.min(d, 90), limit: 50 } }),
      ]);
      cacheRef.current = { key, time: Date.now(), ov: oRes.data, er: eRes.data };
      setOv(oRes.data); setEr(eRes.data);
    } catch { setError(true); }
  }, []);

  useEffect(() => {
    if (skipLoadRef.current) { skipLoadRef.current = false; return; }
    load(preset, days, startDate, endDate);
  }, [load, preset, days, startDate, endDate]);

  const setPresetAndLoad = (p: string) => {
    if (p === 'custom') {
      /* 只切到日期选择面板，不沿用旧 days 发请求（点「确认」后按自定义范围加载） */
      if (preset !== 'custom') skipLoadRef.current = true;
      setPreset('custom');
      return;
    }
    const n = new Date();
    let d = 30, sd: string | null = null, ed: string | null = null;
    if (p === '7') d = 7;
    else if (p === 'month') { d = n.getDate(); sd = new Date(n.getFullYear(), n.getMonth(), 1).toISOString().slice(0, 10); }
    else if (p === 'prevMonth') { sd = new Date(n.getFullYear(), n.getMonth() - 1, 1).toISOString().slice(0, 10); ed = new Date(n.getFullYear(), n.getMonth(), 0).toISOString().slice(0, 10); d = 30; }
    setPreset(p); setDays(d); setStartDate(sd); setEndDate(ed);
  };

  const applyCustom = () => {
    if (!customRange?.[0]) return;
    const sd = customRange[0].format('YYYY-MM-DD');
    const ed = customRange[1]?.format('YYYY-MM-DD') || '';
    const d = Math.max(1, Math.round(((customRange[1] || dayjs()).diff(customRange[0], 'day')) + 1));
    setDays(d); setStartDate(sd); setEndDate(ed || null);
  };

  const pr = ov?.reflection_pass_rate || 0;
  const p50 = ov?.latency_p50_ms || 0;
  const p95 = ov?.latency_p95_ms || 0;
  const fbr = ov?.feedback_helpful_rate || 0;
  const da = ov?.total_analyses ? Math.round(ov.total_analyses / (ov.period_days || 1)) : 0;
  const rr = ov?.retry_rate || 0;
  const fr = ov?.fix_rate || 0;
  const p90d = ov?.p90_duration_ms || 0;
  const dcost = ov?.estimated_daily_cost || 0;
  const mcost = ov?.estimated_monthly_cost || 0;

  /* ── Token 消耗趋势（对齐原生 mTC 图，双 Y 轴） ── */
  const tokenOption = (() => {
    const trend = ov?.token_trend || [];
    if (!trend.length) return null;
    const show = trend.slice(-14);
    const dates = show.map((t) => (t.date || '').slice(5));
    const inS = show.map((t) => t.input_tokens);
    const outS = show.map((t) => t.output_tokens);
    /* 成本存真实值（元），不再 ×10000 换算；tooltip/轴统一用 ¥ 格式化 */
    const costS = show.map((t) => (t.cost ? +t.cost.toFixed(4) : 0));
    return {
      tooltip: {
        trigger: 'axis', backgroundColor: 'rgba(30,35,55,0.95)', borderColor: '#334155', textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: (p: Array<{ seriesName: string; value: number; marker: string }>) =>
          p.map((x) => `${x.marker}${x.seriesName}: ${x.seriesName === '成本(元)' ? '¥' + x.value.toFixed(4) : fmtTokens(x.value)}`).join('<br/>'),
      },
      legend: { data: ['Input', 'Output', '成本(元)'], textStyle: { color: '#94a3b8', fontSize: 11 }, top: 0, right: 0, icon: 'circle', itemWidth: 8, itemHeight: 8 },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#94a3b8', fontSize: 10 }, axisLine: { lineStyle: { color: '#334155' } }, axisTick: { show: false } },
      yAxis: [
        { type: 'value', name: 'Tokens', nameTextStyle: { color: '#94a3b8', fontSize: 10 }, axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (v: number) => fmtTokens(v) }, splitLine: { lineStyle: { color: '#1e293b' } } },
        { type: 'value', name: '成本(元)', nameTextStyle: { color: '#94a3b8', fontSize: 10 }, axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (v: number) => '¥' + v.toFixed(2) }, splitLine: { show: false } },
      ],
      series: [
        { name: 'Input', type: 'line', data: inS, smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2, color: '#6366f1' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.25)' }, { offset: 1, color: 'rgba(99,102,241,0)' }] } } },
        { name: 'Output', type: 'line', data: outS, smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2, color: '#22c55e' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(34,197,94,0.2)' }, { offset: 1, color: 'rgba(34,197,94,0)' }] } } },
        { name: '成本(元)', type: 'bar', yAxisIndex: 1, data: costS, itemStyle: { color: 'rgba(245,158,11,0.5)', borderColor: '#f59e0b', borderWidth: 1, borderRadius: [2, 2, 0, 0] } },
      ],
    };
  })();
  const trendSum = (ov?.token_trend || []).slice(-14).reduce((acc, t) => ({ in: acc.in + (t.input_tokens || 0), out: acc.out + (t.output_tokens || 0), cost: acc.cost + (t.cost || 0) }), { in: 0, out: 0, cost: 0 });

  /* 小卡片 */
  const smCard = (label: string, value: string, sub: string, color: string) => (
    <div style={{ flex: 1, minWidth: 150, background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: '14px 16px' }}>
      <div style={{ fontSize: 11, color: DARK.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: DARK.muted, marginTop: 4 }}>{sub}</div>
    </div>
  );

  const heroCard = (icon: string, label: string, value: string, status: { label: string; color: string }, sub?: string) => (
    <div style={{ flex: 1, minWidth: 220, background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 14, padding: '18px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span style={{ fontSize: 11, color: status.color, fontWeight: 600 }}>{status.label}</span>
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: DARK.text }}>{value}</div>
      <div style={{ fontSize: 12, color: DARK.muted, marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: DARK.muted, marginTop: 6 }}>{sub}</div>}
    </div>
  );

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* ── 头部：标题 + 周期 pills（对齐原生 mq-header/mq-pills） ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
        <Space size={8}>
          <Title level={4} style={{ margin: 0, color: DARK.text }}>AI 质量监控</Title>
          <span style={{ fontSize: 12, color: DARK.muted }}>{periodLabel}</span>
        </Space>
        <Space wrap size={6}>
          {PRESETS.map(([p, label]) => (
            <Button key={p} size="small" onClick={() => setPresetAndLoad(p)}
              style={preset === p ? { background: DARK.accent, borderColor: DARK.accent, color: '#fff' } : { background: DARK.cardBg, borderColor: DARK.border, color: DARK.text }}>
              {label}
            </Button>
          ))}
        </Space>
      </div>

      {/* 自定义日期范围 */}
      {preset === 'custom' && (
        <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 14, padding: '18px 24px', marginBottom: 16, maxWidth: 520 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: DARK.text, marginBottom: 12 }}>📅 选择日期范围</div>
          <Space>
            <DatePicker value={customRange?.[0] ?? null} onChange={(v) => setCustomRange((prev) => [v, prev?.[1] ?? null])} style={{ background: DARK.bg, borderColor: DARK.border }} />
            <span style={{ color: DARK.muted }}>至</span>
            <DatePicker value={customRange?.[1] ?? null} onChange={(v) => setCustomRange((prev) => [prev?.[0] ?? null, v])} style={{ background: DARK.bg, borderColor: DARK.border }} />
            <Button type="primary" size="small" onClick={applyCustom}>确认</Button>
            <Button size="small" onClick={() => setPresetAndLoad('30')}>取消</Button>
          </Space>
        </div>
      )}

      {error && !ov ? (
        <div style={{ textAlign: 'center', padding: 60, color: DARK.muted }}>❌ 加载失败</div>
      ) : !ov ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : (
        <>
          {/* ── Hero 大卡（对齐原生 mq-hero） ── */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
            {heroCard('📊', '日均分析量', String(da), { label: `日均 ${da} 次`, color: LEVEL.ok })}
            {heroCard('✅', '质检通过率', `${pr}%`, rateLevel(pr, 90, 75),
              `好评率 ${fbr}% · 未过 ${ov?.reflection_failed ?? 0} 条 · 解析兜底 ${ov?.reflection_fallback ?? 0} 条`)}
            {heroCard('⚡', '中位响应延迟', fmtSec(p50), rateLevel(100 - Math.min(p50 / 10, 100), 95, 90), `95% 请求 ${fmtSec(p95)} 内 · 完整分析 ${fmtSec(ov.p50_duration_ms)}`)}
          </div>

          {/* ── 质量指标 + 成本指标（对齐原生 mq-groups） ── */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
            <div style={{ flex: 2, minWidth: 320 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text, marginBottom: 8 }}>🔬 质量指标</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {smCard('重试率', `${rr}%`, `修复率 ${fr}%`, rr > 10 ? LEVEL.err : rr > 5 ? LEVEL.warn : LEVEL.ok)}
                {smCard('修复率', `${fr}%`, '重试后通过比例', fr >= 70 ? LEVEL.ok : fr >= 50 ? LEVEL.warn : LEVEL.err)}
                {smCard('用户好评率', `${fbr}%`, '反馈有帮助比例', fbr >= 85 ? LEVEL.ok : fbr >= 70 ? LEVEL.warn : LEVEL.err)}
                {smCard('完整分析 90% 分位', fmtSec(p90d), '90% 在此时间内完成', p90d < 30000 ? LEVEL.ok : LEVEL.warn)}
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text, marginBottom: 8 }}>💰 成本指标</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {smCard('日均成本', `¥${ov.total_analyses ? dcost.toFixed(4) : '—'}`, '每日 LLM 调用费用', dcost > 0.05 ? LEVEL.warn : LEVEL.ok)}
                {smCard('月均成本', `¥${ov.total_analyses ? mcost.toFixed(4) : '—'}`, '累计 Token 消耗', mcost > 1 ? LEVEL.warn : LEVEL.ok)}
              </div>
            </div>
          </div>

          {/* ── Agent 健康度（对齐原生 mq-table，错误率进度条） ── */}
          <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 14, padding: 18, marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text, marginBottom: 4 }}>🤖 Agent 健康度</div>
            <div style={{ fontSize: 11, color: DARK.muted, marginBottom: 12 }}>错误率排行 · 性能指标</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Agent', '运行', '错误', '错误率', '平均(s)', '最大(s)'].map((h) => (
                    <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: DARK.muted, fontSize: 11, borderBottom: `1px solid ${DARK.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(ov.agents || []).length === 0 && (
                  <tr><td colSpan={6} style={{ textAlign: 'center', color: DARK.muted, padding: 24 }}>暂无数据</td></tr>
                )}
                {(ov.agents || []).map((a) => {
                  const c = a.error_rate > 5 ? LEVEL.err : a.error_rate > 2 ? LEVEL.warn : LEVEL.ok;
                  return (
                    <tr key={a.agent}>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>
                        <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: c, marginRight: 8 }} />
                        {AGENT_LABELS[a.agent] || a.agent}
                      </td>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>{a.total_runs}</td>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>{a.error_count}</td>
                      <td style={{ padding: '8px 10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ flex: 1, maxWidth: 120, background: '#15152a', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.min(a.error_rate * 10, 100)}%`, height: '100%', background: c }} />
                          </div>
                          <span style={{ color: c, fontSize: 12, fontWeight: 600 }}>{a.error_rate}%</span>
                        </div>
                      </td>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>{fmtSec(a.avg_ms)}</td>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>{fmtSec(a.max_ms)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── 最近错误（带表头表格，对齐 Agent 健康度风格：时间/类型/详情/耗时） ── */}
          <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 14, padding: 18, marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text, marginBottom: 4 }}>❌ 最近错误</div>
            <div style={{ fontSize: 11, color: DARK.muted, marginBottom: 12 }}>按时间倒序</div>
            {!er?.errors?.length ? (
              <div style={{ color: LEVEL.ok, fontSize: 13, padding: '8px 0' }}>✅ 无错误记录</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['时间', '类型', '错误详情', '耗时'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: DARK.muted, fontSize: 11, borderBottom: `1px solid ${DARK.border}` }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {er.errors.map((e, i) => (
                    <tr key={i}>
                      <td style={{ padding: '8px 10px', color: DARK.muted, fontSize: 12, whiteSpace: 'nowrap' }}>
                        {errIcon(e.error || '')} {(e.time || '').slice(5, 16)}
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                        <span style={{ fontSize: 11, background: '#2d2d44', color: DARK.text, borderRadius: 8, padding: '1px 8px' }}>{AGENT_LABELS[e.agent] || e.agent}</span>
                      </td>
                      <td style={{ padding: '8px 10px', color: DARK.text }}>{ERR_CN[e.error] || e.error || ''}</td>
                      <td style={{ padding: '8px 10px', color: DARK.muted, fontSize: 12, whiteSpace: 'nowrap', width: 90 }}>{fmtSec(e.elapsed_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* ── Token 消耗趋势（对齐原生 mTC 双轴图 + 累计统计） ── */}
          {tokenOption && (
            <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 14, padding: 18 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text, marginBottom: 4 }}>📊 Token 消耗趋势</div>
              <div style={{ fontSize: 11, color: DARK.muted, marginBottom: 12 }}>近 14 天 · 含 Input/Output/Cost</div>
              <ReactECharts option={tokenOption} style={{ height: 260 }} notMerge />
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 8 }}>
                <div><span style={{ fontSize: 11, color: DARK.muted }}>累计 Input </span><span style={{ fontSize: 13, fontWeight: 600, color: DARK.text }}>{fmtTokens(trendSum.in)}</span></div>
                <div><span style={{ fontSize: 11, color: DARK.muted }}>累计 Output </span><span style={{ fontSize: 13, fontWeight: 600, color: DARK.text }}>{fmtTokens(trendSum.out)}</span></div>
                <div><span style={{ fontSize: 11, color: DARK.muted }}>总成本 </span><span style={{ fontSize: 13, fontWeight: 600, color: DARK.text }}>¥{trendSum.cost.toFixed(4)}</span></div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
