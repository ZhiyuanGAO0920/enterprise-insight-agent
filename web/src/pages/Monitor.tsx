import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout, Card, Row, Col, Statistic, Typography, Button, Space, Table, Radio, Spin, message, Tag } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import client from '../api/client';

const { Title } = Typography;

interface AgentMetric {
  agent: string;
  total_runs: number;
  error_count: number;
  error_rate: number;
  avg_ms: number;
  max_ms: number;
}

interface DailyTrend {
  date: string;
  count: number;
}

interface HealthStatus {
  reflection: string;
  latency: string;
  feedback: string;
}

interface OverviewData {
  period_days: number;
  total_analyses: number;
  reflection_pass_rate: number;
  feedback_helpful_rate: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  estimated_daily_cost: number;
  estimated_monthly_cost: number;
  agents: AgentMetric[];
  daily_trend: DailyTrend[];
  health: HealthStatus;
  reflection_issue_dist: Record<string, number>;
}

interface ErrorRecord {
  time: string;
  agent: string;
  error: string;
  elapsed_ms: number;
  session: string;
}

interface ErrorsData {
  period_days: number;
  total_errors: number;
  by_agent: Record<string, number>;
  errors: ErrorRecord[];
}

const AGENT_LABELS: Record<string, string> = {
  sales: '销售 Agent',
  crm: 'CRM Agent',
  finance: '财务 Agent',
  inventory: '库存 Agent',
  supply_chain: '供应链 Agent',
  supervisor: '任务规划 Agent',
  aggregator: '聚合 Agent',
  chart_advisor: '图表顾问 Agent',
  report: '报告生成 Agent',
  reflection: '质量审核 Agent',
};

const HEALTH_MAP: Record<string, { icon: React.ReactNode; color: string }> = {
  '✅': { icon: <CheckCircleOutlined />, color: '#52c41a' },
  '⚠️': { icon: <WarningOutlined />, color: '#faad14' },
};

const ECHARTS_THEME = {
  backgroundColor: 'transparent',
  textStyle: { color: '#e0e0e0' },
  grid: { borderColor: '#333' },
  xAxis: { axisLine: { lineStyle: { color: '#555' } }, axisLabel: { color: '#aaa' } },
  yAxis: { axisLine: { lineStyle: { color: '#555' } }, axisLabel: { color: '#aaa' } },
};

export default function MonitorPage() {
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [errorsData, setErrorsData] = useState<ErrorsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const [overviewRes, errorsRes] = await Promise.all([
        client.get(`/monitor/overview?days=${d}`),
        client.get('/monitor/errors?days=7&limit=50'),
      ]);
      setOverview(overviewRes.data);
      setErrorsData(errorsRes.data);
    } catch (e: any) {
      message.error('加载监控数据失败: ' + (e.response?.data?.detail || e.message));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData(days);
  }, [days, fetchData]);

  const handleDaysChange = (e: any) => {
    setDays(e.target.value);
  };

  const overviewData = overview;
  const healthIcon = (key: keyof HealthStatus) => {
    const h = overviewData?.health?.[key];
    if (!h) return null;
    const info = HEALTH_MAP[h];
    return info ? <span style={{ color: info.color }}>{info.icon}</span> : null;
  };

  // ECharts option for daily trend
  const trendOption = {
    ...ECHARTS_THEME,
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: overviewData?.daily_trend?.map((d) => d.date.slice(5)) || [],
      axisLabel: { color: '#aaa', fontSize: 11 },
    },
    yAxis: {
      type: 'value' as const,
      minInterval: 1,
      axisLabel: { color: '#aaa' },
    },
    series: [
      {
        name: '分析次数',
        type: 'line',
        data: overviewData?.daily_trend?.map((d) => d.count) || [],
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#7c3aed', width: 2 },
        itemStyle: { color: '#7c3aed' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(124, 58, 237, 0.3)' },
              { offset: 1, color: 'rgba(124, 58, 237, 0.02)' },
            ],
          },
        },
      },
    ],
    grid: { top: 20, bottom: 30, left: 50, right: 20 },
  };

  // Columns for agent error table
  const agentColumns = [
    { title: 'Agent', dataIndex: 'agent', key: 'agent', render: (v: string) => AGENT_LABELS[v] || v },
    { title: '运行次数', dataIndex: 'total_runs', key: 'total_runs', width: 100 },
    { title: '错误次数', dataIndex: 'error_count', key: 'error_count', width: 100 },
    {
      title: '错误率', dataIndex: 'error_rate', key: 'error_rate', width: 100,
      render: (v: number) => {
        const color = v > 5 ? '#ff4d4f' : v > 2 ? '#faad14' : '#52c41a';
        return <span style={{ color, fontWeight: 'bold' }}>{v}%</span>;
      },
    },
    { title: '平均耗时(ms)', dataIndex: 'avg_ms', key: 'avg_ms', width: 120 },
    { title: '最大耗时(ms)', dataIndex: 'max_ms', key: 'max_ms', width: 120 },
  ];

  // Columns for error detail table
  const errorColumns = [
    { title: '时间', dataIndex: 'time', key: 'time', width: 180, render: (v: string) => v?.slice(0, 19) },
    { title: 'Agent', dataIndex: 'agent', key: 'agent', width: 120, render: (v: string) => AGENT_LABELS[v] || v },
    { title: '错误信息', dataIndex: 'error', key: 'error', ellipsis: true },
    { title: '耗时(ms)', dataIndex: 'elapsed_ms', key: 'elapsed_ms', width: 100 },
    { title: '会话ID', dataIndex: 'session', key: 'session', width: 120, ellipsis: true },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#1a1a2e', padding: 24 }}>
      {/* Header */}
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/analysis')}>返回分析</Button>
          <Title level={4} style={{ margin: 0, color: '#e0e0e0' }}>AI 质量监控</Title>
        </Space>
        <Radio.Group value={days} onChange={handleDaysChange} optionType="button" buttonStyle="solid">
          <Radio.Button value={7}>7 天</Radio.Button>
          <Radio.Button value={30}>30 天</Radio.Button>
          <Radio.Button value={90}>90 天</Radio.Button>
        </Radio.Group>
      </Space>

      <Spin spinning={loading} size="large">
        {/* Section 1: 5 Metric Cards */}
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>Reflection 通过率</span>}
                value={overviewData?.reflection_pass_rate ?? '-'}
                suffix={<span style={{ fontSize: 14 }}>% {healthIcon('reflection')}</span>}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>P50 延迟</span>}
                value={overviewData ? `${(overviewData.latency_p50_ms / 1000).toFixed(1)}s` : '-'}
                suffix={healthIcon('latency')}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>用户好评率</span>}
                value={overviewData?.feedback_helpful_rate ?? '-'}
                suffix={<span style={{ fontSize: 14 }}>% {healthIcon('feedback')}</span>}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>日均成本</span>}
                value={overviewData?.estimated_daily_cost && overviewData.estimated_daily_cost > 0 ? overviewData.estimated_daily_cost : '暂无数据'}
                prefix="¥"
                precision={2}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>月均成本</span>}
                value={overviewData?.estimated_monthly_cost && overviewData.estimated_monthly_cost > 0 ? overviewData.estimated_monthly_cost : '暂无数据'}
                prefix="¥"
                precision={2}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Card style={{ background: '#16213e', border: '1px solid #2a2a4a' }}>
              <Statistic
                title={<span style={{ color: '#aaa' }}>分析总量</span>}
                value={overviewData?.total_analyses ?? '-'}
                suffix={<span style={{ fontSize: 14, color: '#888' }}>/ {days}天</span>}
                valueStyle={{ color: '#e0e0e0' }}
              />
            </Card>
          </Col>
        </Row>

        {/* Section 2: Agent Error Rate + Daily Trend */}
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={24} lg={12}>
            <Card
              title={<span style={{ color: '#e0e0e0' }}>Agent 错误率排行</span>}
              style={{ background: '#16213e', border: '1px solid #2a2a4a', color: '#e0e0e0' }}
              headStyle={{ borderBottom: '1px solid #2a2a4a' }}
            >
              <Table
                dataSource={overviewData?.agents || []}
                columns={agentColumns}
                rowKey="agent"
                size="small"
                pagination={false}
                style={{ background: 'transparent' }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card
              title={<span style={{ color: '#e0e0e0' }}>每日分析量趋势</span>}
              style={{ background: '#16213e', border: '1px solid #2a2a4a', color: '#e0e0e0' }}
              headStyle={{ borderBottom: '1px solid #2a2a4a' }}
            >
              {overviewData?.daily_trend && overviewData.daily_trend.length > 0 ? (
                <ReactECharts option={trendOption} style={{ height: 280 }} />
              ) : (
                <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>暂无趋势数据</div>
              )}
            </Card>
          </Col>
        </Row>

        {/* Section 2.5: Reflection Issue Distribution */}
        {overviewData?.reflection_issue_dist && Object.keys(overviewData.reflection_issue_dist).length > 0 && (
          <Card
            title={<span style={{ color: '#e0e0e0' }}>Reflection Fail Distribution</span>}
            style={{ background: '#16213e', border: '1px solid #2a2a4a', color: '#e0e0e0', marginBottom: 24 }}
            headStyle={{ borderBottom: '1px solid #2a2a4a' }}
          >
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              {Object.entries(overviewData.reflection_issue_dist).map(([cat, cnt]) => (
                <div key={cat} style={{ background: '#1a1a2e', borderRadius: 8, padding: '12px 20px', border: '1px solid #2a2a4a', minWidth: 140 }}>
                  <div style={{ fontSize: 11, color: '#aaa', marginBottom: 4 }}>
                    {cat === 'consistency' ? '一致性' : cat === 'logic' ? '逻辑性' : cat === 'actionability' ? '可操作性' : '完整性'}
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: '#e0e0e0' }}>{cnt as number}</div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Section 3: Error Details */}
        <Card
          title={
            <Space>
              <span style={{ color: '#e0e0e0' }}>错误详情</span>
              {errorsData && errorsData.total_errors > 0 && (
                <Tag color="error">{errorsData.total_errors} 条错误</Tag>
              )}
            </Space>
          }
          style={{ background: '#16213e', border: '1px solid #2a2a4a', color: '#e0e0e0' }}
          headStyle={{ borderBottom: '1px solid #2a2a4a' }}
        >
          <Table
            dataSource={errorsData?.errors || []}
            columns={errorColumns}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={{ pageSize: 10, size: 'small' }}
            locale={{ emptyText: '暂无错误记录' }}
            style={{ background: 'transparent' }}
          />
        </Card>
      </Spin>
    </Layout>
  );
}
