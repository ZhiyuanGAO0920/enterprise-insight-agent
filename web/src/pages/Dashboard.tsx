import { useEffect, useState } from 'react';
import { Layout, Card, Row, Col, Statistic, Typography, Button, Space } from 'antd';
import { ArrowLeftOutlined, ShopOutlined, DollarOutlined, TeamOutlined, WarningOutlined } from '@ant-design/icons';
import client from '../api/client';

const { Title } = Typography;

export default function DashboardPage() {
  const [data, setData] = useState<any>({});

  useEffect(() => {
    client.get('/dashboard/today-summary').then((res) => setData(res.data)).catch(console.error);
  }, []);

  return (
    <Layout style={{ minHeight: '100vh', background: '#1a1a2e', padding: 24 }}>
      <Space style={{ marginBottom: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => window.location.hash = '/'}>返回分析</Button>
        <Title level={4} style={{ margin: 0, color: '#e0e0e0' }}>📊 今日经营快报</Title>
      </Space>
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={8}><Card><Statistic title="昨日销售额" value={data.yesterday_sales} prefix={<DollarOutlined />} suffix="元" /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="活跃门店" value={data.active_stores} prefix={<ShopOutlined />} /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="会员总数" value={data.total_members} prefix={<TeamOutlined />} /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="近7天退款率" value={data.week_refund_rate} prefix={<WarningOutlined />} suffix="%" precision={1} /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="近24h订单" value={data.recent_orders_24h} /></Card></Col>
      </Row>
    </Layout>
  );
}
