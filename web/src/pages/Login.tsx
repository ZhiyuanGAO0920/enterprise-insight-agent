import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntApp, Card, Form, Input, Button, Typography } from 'antd';
import { UserOutlined, LockOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useAuth } from '../hooks/useAuth';
import { errMsg } from '../lib/format';

const { Title, Text } = Typography;

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  /* antd v5 推荐用 App.useApp() 获取 message（静态 message 有 context 告警） */
  const { message } = AntApp.useApp();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(values.username, values.password);
      message.success('登录成功');
      /* 登录后固定进经营看板：仅靠 token 状态切换路由时，若登录页 URL 非 /（深层链接/401 刷新），
         会错误停留在原路径而不是默认看板（对齐原生登录后默认 tab=dashboard） */
      navigate('/dashboard', { replace: true });
    } catch (err) {
      message.error(errMsg(err, '登录失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' }}>
      <Card style={{ width: 400, borderRadius: 12 }} bordered={false}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <ThunderboltOutlined style={{ fontSize: 48, color: '#6366f1' }} />
          <Title level={3} style={{ marginTop: 12, color: '#e0e0e0' }}>企业智能分析平台 V4</Title>
          <Text type="secondary">自然语言驱动的经营决策助手</Text>
        </div>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoFocus />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
