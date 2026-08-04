import { useEffect, useState } from 'react';
import { Modal, List, Tag, Typography, Empty, Spin } from 'antd';
import client from '../api/client';

const { Text } = Typography;

interface FeedbackItem {
  id: number;
  rating: 'helpful' | 'bad';
  reason?: string | null;
  question?: string | null;
  created_at?: string;
}

/* 我的反馈（对齐原生 showFeedbackHistory → /feedback/history） */
export default function FeedbackHistoryModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    client.get('/feedback/history?limit=20')
      .then((res) => setItems(res.data.records || res.data || []))
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
                    <Tag color={f.rating === 'helpful' ? 'green' : 'red'}>
                      {f.rating === 'helpful' ? '👍 有帮助' : '👎 没有帮助'}
                    </Tag>
                    <Text style={{ fontSize: 11, color: '#94a3b8' }}>
                      {f.created_at ? f.created_at.slice(0, 16) : ''}
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
