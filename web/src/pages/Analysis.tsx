import { useState } from 'react';
import { Layout, Input, Button, Card, Space, Typography, Tag, Drawer } from 'antd';
import { SendOutlined, LogoutOutlined, DashboardOutlined, SettingOutlined, HistoryOutlined } from '@ant-design/icons';
import { useAuth } from '../hooks/useAuth';
import { useSSE } from '../hooks/useSSE';
import { useAppStore } from '../stores/appStore';
import ReactECharts from 'echarts-for-react';

const { Header, Sider, Content } = Layout;
const { Text, Paragraph } = Typography;

const QUICK_QUESTIONS = [
  '各门店销售额排名',
  '近30天销售趋势',
  '退款率最高的门店',
  '会员增长与留存情况',
  '整体经营分析报告',
  '各区域经营对比',
];

// XSS-safe HTML rendering: escape all HTML, then convert newlines to <br/>
function safeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
    .replace(/\n/g, '<br/>');
}

export default function AnalysisPage() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<{ role: string; content: string; charts?: any[] }[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const { logout, username, role } = useAuth();
  const { sessionId, setSession } = useAppStore();
  const { steps, streamText, isStreaming, finalData, analyze } = useSSE();

  const labelMap: Record<string, string> = {
    supervisor: '🧠 规划中', sales_agent: '📊 销售分析', crm_agent: '👥 CRM分析',
    finance_agent: '💰 财务分析', inventory_agent: '📦 库存分析', supply_chain_agent: '🚚 供应链分析',
    aggregator: '📋 整合', chart_advisor: '📈 图表', report_agent: '📝 报告',
    reflection_agent: '✅ 质检', save_memory: '💾 保存',
  };

  const handleSend = async () => {
    if (!question.trim() || isStreaming) return;
    const q = question.trim();
    setQuestion('');
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    await analyze(q, sessionId);
  };

  if (finalData && streamText) {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role !== 'assistant') {
      setMessages((prev) => [...prev, { role: 'assistant', content: finalData.report || streamText }]);
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#1a1a2e', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', borderBottom: '1px solid #2d2d44' }}>
        <Space>
          <span style={{ fontSize: 20, fontWeight: 700, color: '#6366f1' }}>⚡ EIA V4</span>
          <Tag color="purple">{role}</Tag>
        </Space>
        <Space>
          <Button type="text" icon={<HistoryOutlined />} onClick={() => setHistoryOpen(true)} />
          <Button type="text" icon={<DashboardOutlined />} onClick={() => window.location.hash = '/dashboard'} />
          <Button type="text" icon={<SettingOutlined />} onClick={() => window.location.hash = '/admin'} />
          <Button type="text" icon={<LogoutOutlined />} onClick={logout} />
          <Text style={{ color: '#94a3b8' }}>{username}</Text>
        </Space>
      </Header>

      <Layout>
        <Content style={{ padding: 24, maxWidth: 900, margin: '0 auto', width: '100%' }}>
          <div style={{ flex: 1, overflow: 'auto', marginBottom: 16, minHeight: 'calc(100vh - 200px)' }}>
            {messages.length === 0 && (
              <Card style={{ textAlign: 'center', marginBottom: 16, background: 'linear-gradient(135deg, #1e1e2e, #262637)' }}>
                <Text style={{ fontSize: 18, color: '#e0e0e0' }}>👋 欢迎使用企业智能分析平台</Text>
                <Paragraph type="secondary" style={{ marginTop: 8 }}>输入经营分析问题，AI Agent 将为您分钟级生成分析报告</Paragraph>
                <Space wrap style={{ marginTop: 16 }}>
                  {QUICK_QUESTIONS.map((q) => (
                    <Button key={q} size="small" onClick={() => { setQuestion(q); }}>{q}</Button>
                  ))}
                </Space>
              </Card>
            )}
            {messages.map((msg, i) => (
              <Card key={i} size="small" style={{ marginBottom: 12, background: msg.role === 'user' ? '#2d2d44' : '#1e1e2e' }}>
                <div dangerouslySetInnerHTML={{ __html: safeHtml(msg.content) }} />
                {msg.role === 'assistant' && finalData?.data_sources && (
                  <Text type="secondary" style={{ fontSize: 11 }}>📊 {finalData.data_sources.length} 条数据来源可追溯</Text>
                )}
              </Card>
            ))}
            {isStreaming && streamText && (
              <Card size="small" style={{ marginBottom: 12, background: '#1e1e2e', borderLeft: '3px solid #6366f1' }}>
                <div dangerouslySetInnerHTML={{ __html: safeHtml(streamText) }} />
              </Card>
            )}
          </div>

          <Card size="small" style={{ position: 'sticky', bottom: 0, background: '#1a1a2e' }}>
            {isStreaming && Object.keys(steps).length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {Object.entries(steps).map(([k, v]) => (
                  <Tag key={k} color={v === 'done' ? 'green' : 'processing'} style={{ marginBottom: 4 }}>
                    {labelMap[k] || k} {v === 'done' ? '✓' : '...'}
                  </Tag>
                ))}
              </div>
            )}
            <Space.Compact style={{ width: '100%' }}>
              <Input.TextArea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onPressEnter={(e) => { e.preventDefault(); handleSend(); }}
                placeholder="输入经营分析问题，如「华东区销售为什么下降」..."
                autoSize={{ minRows: 1, maxRows: 4 }}
                disabled={isStreaming}
              />
              <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={isStreaming} />
            </Space.Compact>
          </Card>
        </Content>
      </Layout>

      <Drawer title="分析历史" open={historyOpen} onClose={() => setHistoryOpen(false)}>
        <Text type="secondary">历史分析记录加载中...</Text>
      </Drawer>
    </Layout>
  );
}
