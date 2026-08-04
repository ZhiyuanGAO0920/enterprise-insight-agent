import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, Row, Col, Button, Spin, Tooltip, Empty } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import client from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { DARK, THEME_COLORS } from '../theme';
import { formatMoney } from '../lib/format';

interface DashboardData {
  greeting?: string;
  username?: string;
  cached_at?: number;
  today_sales?: number;
  yesterday_sales?: number;
  week_refund_rate?: number;
  active_stores?: number;
  total_members?: number;
  recent_orders_24h?: number;
  trend_dates?: string[];
  trend_values?: number[];
  top_stores?: string[];
  top_store_values?: number[];
  regions?: string[];
  region_values?: number[];
  top_refund_stores?: string[];
  top_refund_values?: number[];
}

/* ── 格式化（与原生版一致；formatMoney 来自 lib/format） ── */
function formatAxisValue(v: number): string {
  return v >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(Math.round(v));
}
function formatPercent(v: number): string {
  return `${v.toFixed(1)}%`;
}

/* ── KPI 数字滚动（350ms，对齐原生版动画） ── */
function useCountUp(target: number, enabled: boolean, duration = 350) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let raf = 0;
    const start = performance.now();
    const tick = (ts: number) => {
      const p = Math.min((ts - start) / duration, 1);
      setValue(Math.round(target * p));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return value;
}

function KpiCard({ label, value, sub, subUp, subColor, fmt }: {
  label: string;
  value: number | undefined;
  sub: string;
  subUp?: boolean;
  subColor?: string;
  fmt: (v: number) => string;
}) {
  const animated = useCountUp(typeof value === 'number' ? value : 0, typeof value === 'number');
  return (
    <Card style={{ background: DARK.cardBg, borderColor: DARK.border, height: '100%' }}
      styles={{ body: { padding: '16px 18px' } }}>
      <div style={{ fontSize: 12, color: DARK.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: DARK.text, lineHeight: 1.2 }}>
        {typeof value === 'number' ? fmt(animated) : '—'}
      </div>
      <div style={{
        fontSize: 11, marginTop: 6,
        color: subColor ?? (subUp === undefined ? DARK.muted : subUp ? DARK.up : DARK.down),
      }}>
        {sub}
      </div>
    </Card>
  );
}

const CARD_STYLE = { background: DARK.cardBg, borderColor: DARK.border, height: '100%' } as const;
const TOOLTIP_STYLE = {
  backgroundColor: 'rgba(30,41,59,0.95)',
  borderColor: '#334155',
  textStyle: { color: '#f1f5f9', fontSize: 12 },
};

export default function DashboardPage() {

  const { username } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState(false);
  const [regionSel, setRegionSel] = useState<Record<string, boolean>>({});
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setError(false);
    try {
      const res = await client.get('/dashboard/overview');
      setData(res.data);
    } catch (e) {
      console.error(e);
      setError(true);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  /* 区域饼图：默认全选 */
  useEffect(() => {
    if (data?.regions?.length) {
      setRegionSel((prev) => {
        if (Object.keys(prev).length) return prev;
        const sel: Record<string, boolean> = {};
        data.regions!.forEach((r) => { sel[r] = true; });
        return sel;
      });
    }
  }, [data]);

  /* ── 30 天销售趋势（折线 + 渐变面积） ── */
  const trendOption = useMemo(() => {
    if (!data) return null;
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', ...TOOLTIP_STYLE },
      grid: { left: 55, right: 20, bottom: 45, top: 10 },
      xAxis: {
        type: 'category',
        data: data.trend_dates,
        axisLabel: { color: DARK.axisLabel, fontSize: 9, rotate: 35 },
        axisLine: { lineStyle: { color: '#334155' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: DARK.axisLabel, fontSize: 9,
          formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v),
        },
        splitLine: { lineStyle: { color: DARK.splitLine } },
      },
      series: [{
        type: 'line',
        data: data.trend_values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 2, color: THEME_COLORS[0] },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: THEME_COLORS[0] + '4d' },
              { offset: 1, color: THEME_COLORS[0] + '00' },
            ],
          },
        },
      }],
    };
  }, [data]);

  /* ── 门店销售额 Top 10（横向条形，倒序） ── */
  const storeOption = useMemo(() => {
    if (!data) return null;
    const names = (data.top_stores || []).slice().reverse();
    const values = (data.top_store_values || []).slice().reverse();
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', ...TOOLTIP_STYLE },
      grid: { left: 120, right: 30, bottom: 20, top: 10 },
      xAxis: {
        type: 'value',
        axisLabel: { color: DARK.axisLabel, fontSize: 9, formatter: (v: number) => formatAxisValue(v) },
        splitLine: { lineStyle: { color: DARK.splitLine } },
      },
      yAxis: {
        type: 'category',
        data: names,
        axisLabel: { color: '#f1f5f9', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: values,
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: 'rgba(99,102,241,0.6)' },
              { offset: 1, color: THEME_COLORS[0] },
            ],
          },
        },
        barMaxWidth: 20,
        label: {
          show: true, position: 'right',
          formatter: (p: { value: number }) => formatAxisValue(p.value),
          color: '#c7d2fe', fontSize: 10,
        },
      }],
    };
  }, [data]);

  /* ── 区域销售占比（环形饼图，支持区域筛选） ── */
  const activeRegionCount = (data?.regions || []).filter((r) => regionSel[r] === true).length;
  const regionOption = useMemo(() => {
    if (!data) return null;
    const pieData = (data.regions || [])
      .map((n, i) => ({ name: n, value: (data.region_values || [])[i] || 0 }))
      .filter((r) => regionSel[r.name]);
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', ...TOOLTIP_STYLE },
      series: [{
        type: 'pie',
        radius: ['35%', '60%'],
        data: pieData,
        label: { color: '#f1f5f9', fontSize: 11, formatter: '{b}: {d}%' },
        itemStyle: { borderColor: 'transparent', borderWidth: 2 },
        color: THEME_COLORS,
      }],
    };
  }, [data, regionSel]);

  /* ── 门店退款率 Top 10（横向条形，红色渐变，升序） ── */
  const refundOption = useMemo(() => {
    if (!data || !data.top_refund_stores?.length) return null;
    const sorted = (data.top_refund_stores || [])
      .map((n, i) => ({ name: n, value: (data.top_refund_values || [])[i] || 0 }))
      .sort((a, b) => a.value - b.value);
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (p: Array<{ name: string; value: number }>) => `${p[0].name}<br/>退款率: ${p[0].value}%`,
        ...TOOLTIP_STYLE,
      },
      grid: { left: 120, right: 35, bottom: 20, top: 10 },
      xAxis: {
        type: 'value',
        axisLabel: { color: DARK.axisLabel, fontSize: 9, formatter: (v: number) => `${v}%` },
        splitLine: { lineStyle: { color: DARK.splitLine } },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((d) => d.name),
        axisLabel: { color: '#f1f5f9', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: sorted.map((d) => d.value),
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: 'rgba(239,68,68,0.3)' },
              { offset: 1, color: '#ef4444' },
            ],
          },
        },
        barMaxWidth: 20,
        label: {
          show: true, position: 'right',
          formatter: (p: { value: number }) => `${p.value}%`,
          color: '#fca5a5', fontSize: 10, fontWeight: 600,
        },
      }],
    };
  }, [data]);

  const freshness = data?.cached_at
    ? `数据更新于 ${new Date(data.cached_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
    : '';

  const t = data?.today_sales || 0;
  const y = data?.yesterday_sales || 0;
  const sc = y > 0 ? ((t - y) / y) * 100 : 0;
  const scUp = sc >= 0;

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* ── 头部：问候 + 数据时效 + 操作 ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 8, marginBottom: 16,
      }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: 700, color: DARK.text }}>
            {data?.greeting || '你好'}，{username || '用户'}
          </span>
          {freshness && <span style={{ fontSize: 11, color: DARK.muted, marginLeft: 8 }}>{freshness}</span>}
        </div>
        <Tooltip title="重新加载（后端缓存 5 分钟）">
          <Button size="small" icon={<ReloadOutlined />} onClick={() => setRefreshKey((k) => k + 1)}>
            刷新
          </Button>
        </Tooltip>
      </div>

      {error && !data ? (
        <Card style={{ ...CARD_STYLE, textAlign: 'center', padding: 40 }}>
          <span style={{ color: DARK.muted }}>看板加载失败，请确认后端服务（8002）运行中，或点击刷新重试。</span>
        </Card>
      ) : !data ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : (
        <>
          {/* ── KPI 卡片 ── */}
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="今日销售额" value={data.today_sales} fmt={formatMoney}
                sub={`${scUp ? '↑' : '↓'} ${Math.abs(sc).toFixed(1)}% vs 昨日`} subUp={scUp} />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="昨日销售额" value={data.yesterday_sales} fmt={formatMoney} sub="基线对比" />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="退款率（近7天）" value={data.week_refund_rate} fmt={(v) => formatPercent(v)}
                sub={(data.week_refund_rate ?? 0) > 5 ? '⚠️ 偏高' : '✅ 正常'}
                subColor={(data.week_refund_rate ?? 0) > 5 ? DARK.down : DARK.up} />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="活跃门店" value={data.active_stores} fmt={(v) => String(Math.round(v))} sub="近7天有订单" />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="会员总数" value={data.total_members} fmt={(v) => Math.round(v).toLocaleString()} sub="累计注册" />
            </Col>
            <Col xs={12} sm={8} md={4}>
              <KpiCard label="近24小时订单" value={data.recent_orders_24h} fmt={(v) => String(Math.round(v))} sub="滚动24小时" />
            </Col>
          </Row>

          {/* ── 趋势 + 区域占比 ── */}
          <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
            <Col xs={24} lg={16}>
              <Card title="近30天销售趋势" size="small" style={{ ...CARD_STYLE, height: '100%' }}
                styles={{ header: { color: DARK.text, borderColor: DARK.border }, body: { paddingTop: 8 } }}>
                <ReactECharts option={trendOption} style={{ height: 300 }} notMerge />
              </Card>
            </Col>
            <Col xs={24} lg={8}>
              <Card title="区域销售占比" size="small" style={{ ...CARD_STYLE, height: '100%' }}
                styles={{ header: { color: DARK.text, borderColor: DARK.border }, body: { paddingTop: 8 } }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                  {(data.regions || []).map((r) => (
                    <Button
                      key={r}
                      size="small"
                      onClick={() => setRegionSel((prev) => ({ ...prev, [r]: !prev[r] }))}
                      style={{
                        padding: '0 10px', borderRadius: 10, fontSize: 11,
                        opacity: regionSel[r] === false ? 0.35 : 1,
                        background: DARK.cardBg, borderColor: DARK.border, color: DARK.text,
                      }}
                    >
                      {r}
                    </Button>
                  ))}
                </div>
                {activeRegionCount > 0 ? (
                  <ReactECharts option={regionOption} style={{ height: 260 }} notMerge />
                ) : (
                  <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请至少选择一个区域" />
                  </div>
                )}
              </Card>
            </Col>
          </Row>

          {/* ── 门店 Top10 + 退款率 Top10 ── */}
          <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
            <Col xs={24} lg={12}>
              <Card title="门店销售额 Top 10" size="small" style={{ ...CARD_STYLE, height: '100%' }}
                styles={{ header: { color: DARK.text, borderColor: DARK.border }, body: { paddingTop: 8 } }}>
                <ReactECharts option={storeOption} style={{ height: 330 }} notMerge />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title="门店退款率 Top 10" size="small" style={{ ...CARD_STYLE, height: '100%' }}
                styles={{ header: { color: DARK.text, borderColor: DARK.border }, body: { paddingTop: 8 } }}>
                <ReactECharts option={refundOption} style={{ height: 330 }} notMerge />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}
