import { useEffect, useState } from 'react';
import { Modal, List, Tag, Typography, Empty, Spin } from 'antd';
import client from '../api/client';
import { formatShortTime } from '../lib/format';

const { Text } = Typography;

interface FeedbackItem {
  id: number;
  rating: string; /* helpful / bad / contact（意见反馈）/ inaccurate / not_relevant */
  reason?: string | null;
  question?: string | null;
  created_at?: string;
}

const ratingTag = (rating: string) => {
  if (rating === 'helpful') return <Tag color="green">👍 有帮助</Tag>;
  if (rating === 'contact') return <Tag color="blue">💬 意见反馈</Tag>;
  return <Tag color="red">👎 没有帮助</Tag>;
};

/* 我的反馈（对齐原生 showFeedbackHistory → /feedback/history） */
export default function FeedbackHistoryModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    client.get('/feedback/history?limit=20')
      .then((res) => setItems(res.data.entries || res.data.records || res.data || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open]);

  return (
    <Modal title="📝 我的反馈" open={open} onCancel={onClose} footer={null} width={520}>
      <Spin spinning={loading}>
        {!items.length && !loading ? (
          <Empty description="暂无反馈记录" />
        ) : (
          <List
            dataSource={items}
            renderItem={(f) => (
              <List.Item style={{ borderBlockEnd: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ width: '100%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {ratingTag(f.rating)}
                    <Text style={{ fontSize: 11, color: '#94a3b8' }}>
                      {formatShortTime(f.created_at)}
                    </Text>
                  </div>
                  {f.question && <Text style={{ fontSize: 12, color: '#e0e0e0', display: 'block', marginTop: 4 }}>{f.question}</Text>}
                  {f.reason && <Text style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginTop: 2 }}>💬 {f.reason}</Text>}
                </div>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Modal>
  );
}
