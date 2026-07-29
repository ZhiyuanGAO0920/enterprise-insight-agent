import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout, Table, Button, Space, Typography, Modal, Form, Input, Select, message, Tabs } from 'antd';
import { ArrowLeftOutlined, UserAddOutlined, ReloadOutlined, DatabaseOutlined } from '@ant-design/icons';
import client from '../api/client';

const { Title } = Typography;

export default function AdminPage() {
  const navigate = useNavigate();
  const [users, setUsers] = useState<any[]>([]);
  const [stores, setStores] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [schemaInfo, setSchemaInfo] = useState<any>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [uRes, sRes] = await Promise.all([
        client.get('/admin/users'),
        client.get('/admin/stores'),
      ]);
      setUsers(uRes.data.users || []);
      setStores(sRes.data.stores || []);
    } catch (e) {
      message.error('加载数据失败');
    }
    setLoading(false);
  };

  const loadAuditLogs = async () => {
    try {
      const res = await client.get('/admin/audit-logs?days=7&page_size=50');
      setAuditLogs(res.data.records || []);
    } catch {}
  };

  const discoverSchema = async () => {
    try {
      const res = await client.get('/admin/schema/discover');
      setSchemaInfo(res.data);
      message.success(`发现 ${res.data.table_count} 张表`);
    } catch (e: any) {
      message.error(e.response?.data?.detail || 'Schema 发现失败');
    }
  };

  useEffect(() => { loadData(); loadAuditLogs(); }, []);

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      await client.post('/admin/users', values);
      message.success('用户创建成功');
      setCreateOpen(false);
      form.resetFields();
      loadData();
    } catch (e: any) {
      message.error(e.response?.data?.detail || '创建失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username' },
    { title: '显示名', dataIndex: 'display_name' },
    { title: '角色', dataIndex: 'role' },
    { title: '状态', dataIndex: 'is_active', render: (v: boolean) => v ? '✅' : '❌' },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#1a1a2e', padding: 24 }}>
      <Space style={{ marginBottom: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/analysis')}>返回分析</Button>
        <Title level={4} style={{ margin: 0, color: '#e0e0e0' }}>⚙️ 系统管理</Title>
      </Space>

      <Tabs defaultActiveKey="users" items={[
        {
          key: 'users', label: '用户管理',
          children: (
            <>
              <Space style={{ marginBottom: 16 }}>
                <Button type="primary" icon={<UserAddOutlined />} onClick={() => setCreateOpen(true)}>新增用户</Button>
                <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
              </Space>
              <Table dataSource={users} columns={columns} rowKey="id" size="small" loading={loading} />
            </>
          ),
        },
        {
          key: 'audit', label: '审计日志',
          children: (
            <Table
              dataSource={auditLogs}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 180, render: (v: string) => v?.slice(0, 19) },
                { title: '用户', dataIndex: 'user_id', width: 60 },
                { title: '操作', dataIndex: 'action', width: 70 },
                { title: '资源', dataIndex: 'resource' },
                { title: '状态码', dataIndex: 'status_code', width: 70 },
                { title: '耗时ms', dataIndex: 'elapsed_ms', width: 80 },
              ]}
              rowKey="id" size="small"
            />
          ),
        },
        {
          key: 'schema', label: '数据源配置',
          children: (
            <>
              <Space style={{ marginBottom: 16 }}>
                <Button icon={<DatabaseOutlined />} onClick={discoverSchema}>自动发现 Schema</Button>
              </Space>
              {schemaInfo && (
                <div>
                  <p>数据库: {schemaInfo.database_type} / {schemaInfo.database_name}</p>
                  <p>发现 {schemaInfo.table_count} 张表</p>
                  {schemaInfo.tables?.slice(0, 10).map((t: any) => (
                    <p key={t.name}>📋 {t.name} ({t.row_count} 行, {t.column_count} 列)</p>
                  ))}
                </div>
              )}
            </>
          ),
        },
      ]} />

      <Modal title="新增用户" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
          <Form.Item name="display_name" label="显示名"><Input /></Form.Item>
          <Form.Item name="role" label="角色" initialValue="store_manager">
            <Select options={[
              { label: '管理员', value: 'admin' }, { label: '大区总监', value: 'regional_director' },
              { label: '区域经理', value: 'regional_manager' }, { label: '店长', value: 'store_manager' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}
