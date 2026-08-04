import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Typography, Input, Button, Space, Spin, Empty, Tag } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import client from '../api/client';
import { DARK } from '../theme';
import { formatShortTime } from '../lib/format';

const { Title, Text } = Typography;

interface HistoryRecord {
  id: number;
  question?: string;
  created_at?: string;
  reflection_passed?: boolean;
}

/* 历史记录页（对齐原生 historyView：搜索 + 计数 + 分页） */
export default function HistoryPage() {
  const navigate = useNavigate();
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const PAGE_SIZE = 20;

  const load = useCallback(async (pageNum: number, keyword: string) => {
    setLoading(true);
    try {
      const res = await client.get('/analysis/history', {
        params: { page: pageNum, page_size: PAGE_SIZE, ...(keyword ? { search: keyword } : {}) },
      });
      setRecords((prev) => (pageNum === 1 ? res.data.records : [...prev, ...res.data.records]));
      setTotal(res.data.total || 0);
    } catch { /* noop */ }
    finally { setLoading(false); }
  }, []);

  /* 搜索输入防抖 300ms，避免每敲一个字符发一次请求 */
  useEffect(() => {
    const t = setTimeout(() => load(1, search.trim()), 300);
    return () => clearTimeout(t);
  }, [search, load]);

  const openRecord = (id: number) => navigate('/analysis', { state: { recordId: id } });

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      {/* 页头：标题 + 计数 + 搜索（对齐原生 hv-header） */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
        <Space align="center" size={8}>
          <Title level={4} style={{ margin: 0, color: DARK.text }}>📝 历史记录</Title>
          <Tag color="default">{total} 条</Tag>
        </Space>
        <Input
          placeholder="搜索历史问题..." prefix={<SearchOutlined />} allowClear
          style={{ width: 240, background: DARK.cardBg, borderColor: DARK.border }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* 列表 */}
      <Spin spinning={loading}>
        {!records.length && !loading ? (
          <div style={{ padding: 60 }}>
            <Empty description={search ? '无匹配结果' : '暂无记录'} />
          </div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {records.map((r) => (
              <div key={r.id}
                onClick={() => openRecord(r.id)}
                style={{
                  background: DARK.cardBg, border: `1px solid ${DARK.border}`, borderRadius: 10,
                  padding: '12px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center',
                  gap: 12, justifyContent: 'space-between',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: DARK.text, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.question}
                  </div>
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>#{r.id} · {formatShortTime(r.created_at)}</Text>
                    {r.reflection_passed !== undefined && (
                      <Tag style={{ marginLeft: 8, fontSize: 10 }} color={r.reflection_passed ? 'green' : 'orange'}>
                        {r.reflection_passed ? '质检通过' : '质检未过'}
                      </Tag>
                    )}
                  </div>
                </div>
                <span style={{ color: DARK.muted, fontSize: 12 }}>查看 →</span>
              </div>
            ))}
            {records.length < total && (
              <Button block onClick={() => load(Math.floor(records.length / PAGE_SIZE) + 1, search.trim())} loading={loading}>
                加载更多（{records.length}/{total}）
              </Button>
            )}
          </Space>
        )}
      </Spin>
    </div>
  );
}
