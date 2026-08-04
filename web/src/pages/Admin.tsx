import { useCallback, useEffect, useState } from 'react';
import { App as AntApp, Table, Button, Space, Typography, Modal, Form, Input, Select, Switch, Tag, Tabs, Tooltip, Popconfirm } from 'antd';
import {
  UserAddOutlined, ReloadOutlined, DatabaseOutlined,
  EditOutlined, DeleteOutlined, KeyOutlined, EyeOutlined, SearchOutlined,
} from '@ant-design/icons';
import client from '../api/client';
import { DARK } from '../theme';
import { errMsg } from '../lib/format';

const { Text } = Typography;

const ROLE_OPTIONS = [
  { label: '👨‍💼 管理员', value: 'admin' },
  { label: '🌍 大区总监', value: 'regional_director' },
  { label: '🗺️ 区域经理', value: 'regional_manager' },
  { label: '🏪 店长', value: 'store_manager' },
];

const ROLE_COLOR: Record<string, string> = {
  admin: 'purple', regional_director: 'blue', regional_manager: 'geekblue', store_manager: 'green',
};

const SCOPE_OPTIONS = [
  { label: '🌐 全部门店', value: 'all' },
  { label: '🌍 按区域', value: 'region' },
  { label: '🏪 按门店', value: 'store' },
];

interface UserRow {
  id: number;
  username: string;
  display_name?: string;
  is_active: boolean;
  role: string;
  scope_type: string;
  region?: string | null;
  store_count?: number;
  store_ids?: string[];
}

interface StoreItem {
  id: number;
  name?: string;
  store_name?: string;
}

interface AuditLogRow {
  id: number;
  created_at?: string;
  user_id?: number;
  action?: string;
  resource?: string;
  status_code?: number;
  elapsed_ms?: number;
}

interface AlertRule {
  id?: number;
  name?: string;
  metric?: string;
  threshold?: number;
  direction?: string;
  enabled?: boolean;
  notify_channels?: string[];
}

interface FbStats {
  total: number;
  helpful_rate: number;
  breakdown?: Record<string, number>;
}

interface SchemaInfo {
  database_type?: string;
  database_name?: string;
  table_count?: number;
  tables?: { name: string; row_count?: number; column_count?: number }[];
}

export default function AdminPanel() {
  const { message } = AntApp.useApp();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [stores, setStores] = useState<StoreItem[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
  const [schemaInfo, setSchemaInfo] = useState<SchemaInfo | null>(null);
  const [alertRules, setAlertRules] = useState<AlertRule[]>([]);
  const [fbStats, setFbStats] = useState<FbStats | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [impersonating, setImpersonating] = useState<number | null>(null);
  const [editUser, setEditUser] = useState<UserRow | null>(null);
  const [resetUid, setResetUid] = useState<number | null>(null);
  const [resetPw, setResetPw] = useState('');
  const [submitLoading, setSubmitLoading] = useState(false);

  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const createRole = Form.useWatch('role', createForm);
  const editRole = Form.useWatch('role', editForm);
  const editScope = Form.useWatch('scope_type', editForm);

  /* ── 数据加载 ── */
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [uRes, sRes] = await Promise.all([
        client.get('/admin/users', { params: { search: search || undefined, role: roleFilter } }),
        client.get('/admin/stores'),
      ]);
      setUsers(uRes.data.users || []);
      const storeList = sRes.data.stores || [];
      setStores(storeList);
      setRegions(sRes.data.regions || []);
    } catch (e) {
      message.error(errMsg(e, '加载数据失败'));
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter, message]);

  const loadAuditLogs = async () => {
    try {
      const res = await client.get('/admin/audit-logs?days=7&page_size=50');
      setAuditLogs(res.data.records || []);
    } catch { /* 非管理员无权限时静默 */ }
  };

  const discoverSchema = async () => {
    try {
      const res = await client.get('/admin/schema/discover');
      setSchemaInfo(res.data);
      message.success(`发现 ${res.data.table_count} 张表`);
    } catch (e) {
      message.error(errMsg(e, 'Schema 发现失败'));
    }
  };

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { loadAuditLogs(); }, []);

  /* 预警规则 + 反馈统计（后端有、前端此前无 UI） */
  useEffect(() => {
    client.get('/alerts/rules').then((res) => setAlertRules(res.data || [])).catch(() => setAlertRules([]));
    client.get('/feedback/stats').then((res) => setFbStats(res.data)).catch(() => setFbStats(null));
  }, []);

  /* ── 创建用户 ── */
  const handleCreate = async () => {
    const values = await createForm.validateFields();
    setSubmitLoading(true);
    try {
      /* 按角色显式设置 scope_type：后端创建接口默认 'store' 不按角色推断，
         不传会导致 regional_manager/regional_director 创建后无数据范围（RLS 查不到任何门店） */
      const body: Record<string, unknown> = { ...values };
      if (values.role === 'admin' || values.role === 'regional_director') {
        body.scope_type = 'all';
        delete body.region;
        delete body.store_ids;
      } else if (values.role === 'regional_manager') {
        body.scope_type = 'region';
        delete body.store_ids;
      } else {
        body.scope_type = 'store';
        delete body.region;
      }
      await client.post('/admin/users', body);
      message.success('用户创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      loadData();
    } catch (e) {
      message.error(errMsg(e, '创建失败，请检查输入'));
    } finally {
      setSubmitLoading(false);
    }
  };

  /* ── 编辑用户 ── */
  const openEdit = (u: UserRow) => {
    setEditUser(u);
    editForm.setFieldsValue({
      username: u.username, display_name: u.display_name, is_active: u.is_active,
      role: u.role || 'store_manager',
      scope_type: u.scope_type || 'store',
      region: u.region || undefined,
      store_ids: u.store_ids || [],
    });
  };

  const handleEdit = async () => {
    if (!editUser) return;
    const values = await editForm.validateFields();
    setSubmitLoading(true);
    try {
      const body: Record<string, unknown> = {
        display_name: values.display_name,
        is_active: values.is_active,
        role: values.role,
      };
      if (values.role !== 'admin') {
        body.scope_type = values.scope_type;
        if (values.scope_type === 'region') body.region = values.region;
        else if (values.scope_type === 'store') body.store_ids = values.store_ids;
      }
      await client.put(`/admin/users/${editUser.id}`, body);
      message.success('保存成功');
      setEditUser(null);
      loadData();
    } catch (e) {
      message.error(errMsg(e, '保存失败，请检查输入'));
    } finally {
      setSubmitLoading(false);
    }
  };

  /* ── 删除用户 ── */
  const handleDelete = async (u: UserRow) => {
    try {
      await client.delete(`/admin/users/${u.id}`);
      message.success('已删除');
      loadData();
    } catch (e) {
      message.error(errMsg(e, '删除失败'));
    }
  };

  /* ── 重置密码 ── */
  const handleResetPw = async () => {
    if (!resetUid || resetPw.length < 6) return;
    setSubmitLoading(true);
    try {
      await client.post(`/admin/users/${resetUid}/reset-password`, { new_password: resetPw });
      message.success('密码已重置');
      setResetUid(null);
      setResetPw('');
    } catch (e) {
      message.error(errMsg(e, '重置失败'));
    } finally {
      setSubmitLoading(false);
    }
  };

  /* ── 模拟用户视角（触发一次完整 LLM 分析，30-60s；带按钮 loading 防重复点击） ── */
  const handleImpersonate = async (u: UserRow) => {
    if (impersonating) return;
    setImpersonating(u.id);
    try {
      const res = await client.post(`/admin/impersonate/${u.id}`, { question: '查询我可以访问的门店列表' });
      const d = res.data;
      const storeCount = d.store_count === '全部' ? '全部门店' : `${d.store_count} 家门店`;
      Modal.info({
        title: `👤 ${d.target_user} 的数据范围`,
        content: (
          <div>
            <Text strong>{storeCount}</Text>
            <pre style={{ marginTop: 12, padding: 12, background: DARK.bg, borderRadius: 8, maxHeight: 320, overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {d.report || '无报告'}
            </pre>
          </div>
        ),
        width: 560,
      });
    } catch (e) {
      message.error(errMsg(e, '模拟失败'));
    } finally {
      setImpersonating(null);
    }
  };

  /* ── 数据范围展示 ── */
  const scopeLabel = (u: UserRow) => {
    if (u.scope_type === 'all') return '🌐 全部门店';
    if (u.scope_type === 'region') return `🌍 ${u.region || '区域'}`;
    const storeNames = stores
      .filter((s) => u.store_ids?.includes(String(s.id)))
      .map((s) => s.name || s.store_name || '#' + s.id);
    if (storeNames.length > 3) return `🏪 ${storeNames.length} 家门店`;
    return storeNames.length ? `🏪 ${storeNames.join('、')}` : '🏪 无门店';
  };

  const storeOptions = stores.map((s) => ({ label: s.name || s.store_name || '门店' + s.id, value: String(s.id) }));

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 55 },
    { title: '用户名', dataIndex: 'username', render: (v: string, u: UserRow) => <Text style={{ fontWeight: 600 }}>{v}{u.display_name ? <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>{u.display_name}</Text> : null}</Text> },
    { title: '角色', dataIndex: 'role', width: 100, render: (v: string) => <Tag color={ROLE_COLOR[v] || 'default'}>{v === 'admin' ? '管理员' : v === 'regional_director' ? '大区总监' : v === 'regional_manager' ? '区域经理' : v === 'store_manager' ? '店长' : v}</Tag> },
    { title: '数据范围', dataIndex: 'scope_type', width: 150, render: (_: string, u: UserRow) => scopeLabel(u) },
    { title: '状态', dataIndex: 'is_active', width: 75, render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag color="red">禁用</Tag>) },
    {
      title: '操作', width: 230, render: (_: string, u: UserRow) => (
        <Space size={2}>
          <Tooltip title="编辑"><Button size="small" type="text" aria-label="编辑" icon={<EditOutlined />} onClick={() => openEdit(u)} /></Tooltip>
          <Tooltip title="模拟用户视角">
            <Button size="small" type="text" aria-label="模拟用户视角" icon={<EyeOutlined />} loading={impersonating === u.id} onClick={() => handleImpersonate(u)} />
          </Tooltip>
          <Tooltip title="重置密码"><Button size="small" type="text" aria-label="重置密码" icon={<KeyOutlined />} onClick={() => setResetUid(u.id)} /></Tooltip>
          <Popconfirm title={`确定删除用户 ${u.username} 吗？此操作不可撤销。`} onConfirm={() => handleDelete(u)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}>
            <Tooltip title="删除"><Button size="small" type="text" aria-label="删除" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  /* ── 角色相关字段：仅非 admin 显示数据范围 ── */
  const ScopeFields = ({ role }: { role?: string }) => {
    if (role === 'admin') return null;
    return (
      <>
        <Form.Item name="scope_type" label="数据范围" initialValue="store" style={{ marginTop: 16 }}>
          <Select options={SCOPE_OPTIONS} />
        </Form.Item>
        {editScope === 'region' && (
          <Form.Item name="region" label="所属区域" rules={[{ required: true, message: '请选择区域' }]}>
            <Select options={regions.sort().map((r) => ({ label: r, value: r }))} placeholder="选择区域" />
          </Form.Item>
        )}
        {editScope === 'store' && (
          <Form.Item name="store_ids" label="分配门店" rules={[{ required: true, message: '请至少选择一家门店' }]}>
            <Select mode="multiple" options={storeOptions} placeholder="选择门店（可多选）" maxTagCount={8} optionFilterProp="label" />
          </Form.Item>
        )}
      </>
    );
  };

  const activeCount = users.filter((u) => u.is_active).length;
  const adminCount = users.filter((u) => u.role === 'admin').length;
  const storeManagerCount = users.filter((u) => u.role === 'store_manager').length;

  return (
    <>
      {/* ── 页面头（整页布局，对齐 Monitor/Dashboard 风格） ── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 22 }}>⚙️</span>
          <h1 style={{ fontSize: 19, fontWeight: 700, color: DARK.text, margin: 0 }}>系统管理</h1>
          <Tag color="purple">管理员</Tag>
        </div>
        <p style={{ fontSize: 12, color: DARK.muted, marginTop: 6, marginBottom: 0 }}>
          用户与权限管理、审计日志、预警规则、反馈统计与数据源配置
        </p>
      </div>

      {/* ── 指标卡片行 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        {[
          { icon: '👥', label: '用户总数', value: users.length, color: DARK.text },
          { icon: '✅', label: '启用用户', value: activeCount, color: DARK.up },
          { icon: '🚫', label: '禁用用户', value: users.length - activeCount, color: DARK.down },
          { icon: '👨‍💼', label: '管理员', value: adminCount, color: '#a78bfa' },
          { icon: '🏪', label: '店长', value: storeManagerCount, color: '#34d399' },
          { icon: '🚨', label: '预警规则', value: alertRules.length, color: '#f59e0b' },
        ].map((c) => (
          <div key={c.label} style={{
            flex: 1, minWidth: 130, background: DARK.cardBg, border: `1px solid ${DARK.border}`,
            borderRadius: 12, padding: '14px 18px',
          }}>
            <div style={{ fontSize: 11, color: DARK.muted }}>{c.icon} {c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color, marginTop: 6 }}>{c.value}</div>
          </div>
        ))}
      </div>

      <Tabs
          defaultActiveKey="users"
          size="large"
          items={[
            /* ── 用户管理 ── */
            {
              key: 'users', label: '用户管理',
              children: (
                <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20 }}>
                  <Space style={{ marginBottom: 16 }} wrap>
                    <Button type="primary" icon={<UserAddOutlined />} onClick={() => setCreateOpen(true)}>新增用户</Button>
                    <Button icon={<ReloadOutlined />} onClick={() => loadData()}>刷新</Button>
                    <Input
                      placeholder="搜索用户名/显示名" prefix={<SearchOutlined />} allowClear
                      style={{ width: 220 }} value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                    <Select
                      placeholder="角色筛选" allowClear style={{ width: 150 }} value={roleFilter}
                      onChange={setRoleFilter}
                      options={ROLE_OPTIONS}
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>共 {users.length} 个用户</Text>
                  </Space>
                  <Table
                    dataSource={users} columns={columns} rowKey="id" size="middle" loading={loading}
                    pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                    scroll={{ x: 900 }}
                  />
                </div>
              ),
            },
            /* ── 审计日志 ── */
            {
              key: 'audit', label: '审计日志',
              children: (
                <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20 }}>
                  <div style={{ marginBottom: 12, fontSize: 12, color: DARK.muted }}>
                    近 7 天敏感操作记录（登录、数据导出、权限变更等），用于安全审计与合规追溯
                  </div>
                  <Table
                    dataSource={auditLogs}
                    columns={[
                      { title: '时间', dataIndex: 'created_at', width: 180, render: (v: string) => v?.slice(0, 19) },
                      { title: '用户ID', dataIndex: 'user_id', width: 70 },
                      { title: '操作', dataIndex: 'action', width: 90 },
                      { title: '资源', dataIndex: 'resource', ellipsis: true },
                      { title: '状态码', dataIndex: 'status_code', width: 75 },
                      { title: '耗时ms', dataIndex: 'elapsed_ms', width: 80 },
                    ]}
                    rowKey="id" size="middle" pagination={{ pageSize: 20 }} scroll={{ x: 800 }}
                  />
                </div>
              ),
            },
            /* ── 预警中心 ── */
            {
              key: 'alerts', label: '🚨 预警中心',
              children: (
                <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20 }}>
                  <div style={{ marginBottom: 12 }}>
                    <Text style={{ color: DARK.muted, fontSize: 12 }}>
                      预警规则由 n8n 定时检查（每日自动执行），异常时推送飞书/钉钉/企微通知。
                    </Text>
                  </div>
                  <Table
                    dataSource={alertRules}
                    rowKey="id" size="middle" pagination={false}
                    columns={[
                      { title: '规则名称', dataIndex: 'name' },
                      {
                        title: '监控指标', dataIndex: 'metric', width: 130,
                        render: (v: string) => ({ refund_rate: '退款率', sales_growth: '销售增长率', member_churn: '会员流失率' }[v] || v),
                      },
                      { title: '阈值', dataIndex: 'threshold', width: 80, render: (v: number) => `${v}%` },
                      { title: '方向', dataIndex: 'direction', width: 80, render: (v: string) => (v === 'above' ? '高于' : '低于') },
                      { title: '状态', dataIndex: 'enabled', width: 70, render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>) },
                      {
                        title: '通知渠道', dataIndex: 'notify_channels', render: (v: string[]) => (v || []).map((c) => (
                          <Tag key={c} style={{ marginRight: 4 }}>{({ feishu: '飞书', dingtalk: '钉钉', wecom: '企微', email: '邮件' } as Record<string, string>)[c] || c}</Tag>
                        )),
                      },
                    ]}
                  />
                </div>
              ),
            },
            /* ── 反馈统计 ── */
            {
              key: 'fbstats', label: '📊 反馈统计',
              children: fbStats ? (
                <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20 }}>
                  <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
                    <div style={{ flex: 1, background: DARK.bg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20, textAlign: 'center' }}>
                      <div style={{ fontSize: 28, fontWeight: 700, color: DARK.text }}>{fbStats.total}</div>
                      <div style={{ fontSize: 12, color: DARK.muted, marginTop: 4 }}>总反馈数</div>
                    </div>
                    <div style={{ flex: 1, background: DARK.bg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20, textAlign: 'center' }}>
                      <div style={{ fontSize: 28, fontWeight: 700, color: DARK.up }}>{(fbStats.helpful_rate * 100).toFixed(1)}%</div>
                      <div style={{ fontSize: 12, color: DARK.muted, marginTop: 4 }}>好评率</div>
                    </div>
                  </div>
                  <Table
                    dataSource={Object.entries(fbStats.breakdown || {}).map(([k, v]) => ({ category: k, count: v }))}
                    rowKey="category" size="middle" pagination={false}
                    columns={[
                      { title: '反馈分类', dataIndex: 'category' },
                      { title: '数量', dataIndex: 'count' },
                    ]}
                  />
                </div>
              ) : (
                <Text type="secondary">反馈统计功能未开启</Text>
              ),
            },
            /* ── 数据源配置 ── */
            {
              key: 'schema', label: '数据源配置',
              children: (
                <div style={{ background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 12, padding: 20 }}>
                  <Space style={{ marginBottom: 16 }}>
                    <Button icon={<DatabaseOutlined />} onClick={discoverSchema}>自动发现 Schema</Button>
                  </Space>
                  {schemaInfo ? (
                    <div style={{ color: DARK.text }}>
                      <p>数据库: {schemaInfo.database_type} / {schemaInfo.database_name}</p>
                      <p>发现 {schemaInfo.table_count} 张表</p>
                      {schemaInfo.tables?.slice(0, 15).map((t) => (
                        <p key={t.name} style={{ marginBottom: 4 }}>📋 {t.name} ({t.row_count} 行, {t.column_count} 列)</p>
                      ))}
                    </div>
                  ) : (
                    <Text type="secondary">点击「自动发现 Schema」扫描客户数据库结构并生成 customer_schema.yaml</Text>
                  )}
                </div>
              ),
            },
          ]}
        />

        {/* ── 新增用户 ── */}
        <Modal title="新增用户" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)} confirmLoading={submitLoading} okText="创建" cancelText="取消">
          <Form form={createForm} layout="vertical">
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: '用户名至少 2 个字符', min: 2 }]}>
              <Input placeholder="如 zhangsan" />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '密码至少 6 位', min: 6 }]}>
              <Input.Password placeholder="至少 6 位" />
            </Form.Item>
            <Form.Item name="display_name" label="显示名"><Input placeholder="选填" /></Form.Item>
            <Form.Item name="role" label="角色" initialValue="store_manager" rules={[{ required: true }]}>
              <Select options={ROLE_OPTIONS} />
            </Form.Item>
            {createRole !== 'admin' && (
              <>
                {createRole === 'store_manager' && (
                  <Form.Item name="store_ids" label="分配门店" rules={[{ required: true, message: '请至少选择一家门店' }]}>
                    <Select mode="multiple" options={storeOptions} placeholder="选择门店（可多选）" maxTagCount={8} optionFilterProp="label" />
                  </Form.Item>
                )}
                {createRole === 'regional_manager' && (
                  <Form.Item name="region" label="所属区域" rules={[{ required: true, message: '请选择区域' }]}>
                    <Select options={regions.sort().map((r) => ({ label: r, value: r }))} placeholder="选择区域" />
                  </Form.Item>
                )}
              </>
            )}
          </Form>
        </Modal>

        {/* ── 编辑用户 ── */}
        <Modal title={`编辑用户：${editUser?.username || ''}`} open={!!editUser} onOk={handleEdit} onCancel={() => setEditUser(null)} confirmLoading={submitLoading} okText="保存" cancelText="取消">
          <Form form={editForm} layout="vertical">
            <Form.Item name="username" label="用户名"><Input disabled /></Form.Item>
            <Form.Item name="display_name" label="显示名"><Input /></Form.Item>
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="禁用" />
            </Form.Item>
            <Form.Item name="role" label="角色" rules={[{ required: true }]}>
              <Select options={ROLE_OPTIONS} />
            </Form.Item>
            <ScopeFields role={editRole} />
          </Form>
        </Modal>

        {/* ── 重置密码 ── */}
        <Modal
          title="重置密码" open={!!resetUid} onOk={handleResetPw} onCancel={() => { setResetUid(null); setResetPw(''); }}
          confirmLoading={submitLoading} okText="重置" cancelText="取消"
        >
          <Input.Password
            value={resetPw} onChange={(e) => setResetPw(e.target.value)}
            placeholder="输入新密码（至少 6 位）" prefix={<KeyOutlined />}
          />
        </Modal>
    </>
  );
}
