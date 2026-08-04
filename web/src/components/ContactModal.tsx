import { useState } from 'react';
import { App as AntApp, Modal, Input, Typography, Rate } from 'antd';
import client from '../api/client';
import { errMsg } from '../lib/format';

const { Text } = Typography;

/* 意见反馈（后端 /feedback/contact，前端此前无入口） */
export default function ContactModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntApp.useApp();
  const [content, setContent] = useState('');
  const [contact, setContact] = useState('');
  const [rating, setRating] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!content.trim()) { message.warning('请填写反馈内容'); return; }
    setSubmitting(true);
    try {
      await client.post('/feedback/contact', {
        content: content.trim(),
        contact: contact.trim() || null,
        rating: rating || null,
      });
      message.success('感谢您的反馈！');
      setContent(''); setContact(''); setRating(0);
      onClose();
    } catch (e) {
      message.error(errMsg(e, '提交失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="📝 意见反馈" open={open} onCancel={onClose} onOk={submit} confirmLoading={submitting} okText="提交反馈" cancelText="取消">
      <div style={{ marginBottom: 12 }}>
        <Text style={{ color: '#94a3b8', fontSize: 12 }}>遇到问题或有好建议？告诉我们，帮助改进平台。</Text>
      </div>
      <div style={{ marginBottom: 12 }}>
        <Text style={{ color: '#94a3b8', fontSize: 12, display: 'block', marginBottom: 6 }}>整体评分（可选）</Text>
        <Rate value={rating} onChange={setRating} />
      </div>
      <Input.TextArea
        value={content} onChange={(e) => setContent(e.target.value)}
        placeholder="请描述你的反馈内容（必填）" autoSize={{ minRows: 3, maxRows: 6 }}
      />
      <Input
        value={contact} onChange={(e) => setContact(e.target.value)}
        placeholder="联系方式（选填：邮箱/手机号）" style={{ marginTop: 10 }}
      />
    </Modal>
  );
}
