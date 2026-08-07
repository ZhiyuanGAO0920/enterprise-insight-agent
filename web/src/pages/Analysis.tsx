import { useCallback, useEffect, useRef, useState } from 'react';
import { App as AntApp, Input, Button, Card, Space, Typography, Tag, Tooltip, Collapse, Modal, Spin } from 'antd';
import {
  SendOutlined, StopOutlined, AudioOutlined, CopyOutlined,
  ShareAltOutlined, PictureOutlined, FilePdfOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import html2canvas from 'html2canvas';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useSSE } from '../hooks/useSSE';
import { useAppStore } from '../stores/appStore';
import client from '../api/client';
import { DARK } from '../theme';
import { formatMoney, fmtSec, errMsg } from '../lib/format';
import {
  processReport, renderMarkdown, convertTextTables, stripFollowupTags,
  buildEChartsOption, type ChartSpec, type DataSource, type SupervisorPlanData,
} from '../lib/report';

const { Text } = Typography;

/* 能力卡片（对齐原生 CAP_CARDS） */
const CAP_CARDS = [
  { icon: '📊', title: '销售分析', desc: '趋势·排名·对比', question: '各门店销售额排名' },
  { icon: '👥', title: '会员洞察', desc: '增长·留存·画像', question: '会员增长与留存情况' },
  { icon: '💰', title: '财务诊断', desc: '成本·利润·应收', question: '整体经营分析报告' },
  { icon: '📦', title: '库存预警', desc: '滞销·周转·缺货', question: '缺货与滞销商品预警' },
  { icon: '🚚', title: '供应链优化', desc: '交期·评级·采购', question: '供应商准时交货率排名' },
];

/* 快捷问题按角色（对齐原生 QUICK_QUESTIONS） */
const ROLE_QUICK_QUESTIONS: Record<string, string[]> = {
  admin: ['整体经营分析报告', '各区域经营对比', '供应商准时交货率排名', '各门店销售额排名', '退款率异常分析', '会员增长趋势'],
  regional_manager: ['我负责区域的销售趋势', '区域内门店排名', '区域会员活跃度分析', '区域退款率分析', '区域库存预警', '近30天区域销售对比'],
  store_manager: ['我们店昨日经营概况', '本周销售趋势', '本店会员消费排行', '本店滞销商品预警', '本店退款订单分析', '本店客单价分析'],
};
const DEFAULT_QUICK_QUESTIONS = ['各门店销售额排名', '近30天销售趋势', '退款率最高的门店', '会员增长与留存情况', '整体经营分析报告', '各区域经营对比'];

/* 信任分级标注（对齐原生 trustFooter） */
function TrustFooter() {
  return (
    <div style={{ marginTop: 14, marginBottom: 6 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: DARK.text, marginBottom: 8 }}>🛡️ 本报告信任分级</div>
      {[
        { badge: '✅', label: '数据层', text: '数据直接来自您的数据库，每条结论可点击 📊 查看SQL 追溯原始查询，可信度极高', color: DARK.up },
        { badge: '⚠️', label: '分析层', text: '趋势判断和原因分析由 AI 基于数据推理生成，建议结合业务经验判断', color: '#f59e0b' },
        { badge: '💡', label: '建议层', text: '经营建议为 AI 参考性输出，执行前请结合实际情况进行人工复核', color: DARK.accent },
      ].map((r) => (
        <div key={r.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 2 }}>
          <span style={{ color: r.color, fontWeight: 600, whiteSpace: 'nowrap', fontSize: 13 }}>{r.badge} {r.label}</span>
          <span style={{ color: DARK.muted, fontSize: 13 }}>{r.text}</span>
        </div>
      ))}
      <div style={{ marginTop: 6, fontSize: 10, color: DARK.muted, textAlign: 'right' }}>
        本报告由 AI 自动生成 · 符合《生成式人工智能服务管理暂行办法》
      </div>
    </div>
  );
}

/* 分析规划面板（对齐原生 buildSupervisorPlan） */
function SupervisorPlan({ plan }: { plan: SupervisorPlanData | string | null | undefined }) {
  let p: SupervisorPlanData | null = typeof plan === 'string' ? null : (plan || null);
  if (typeof plan === 'string') { try { p = JSON.parse(plan); } catch { return null; } }
  if (!p || !p.activated_agents) return null;
  const agentLabels: Record<string, string> = {
    sales: '📊 销售分析', crm: '👥 会员分析', finance: '💰 财务分析',
    inventory: '📦 库存分析', supply_chain: '🚚 供应链分析',
  };
  return (
    <Collapse
      ghost size="small" style={{ marginBottom: 12, background: DARK.bg, borderRadius: 8 }}
      items={[{
        key: 'plan',
        label: <Text style={{ color: DARK.accent, fontSize: 12, fontWeight: 600 }}>🧠 分析规划 · 激活 {p.activated_agents.length} 个 Agent</Text>,
        children: (
          <div style={{ fontSize: 12 }}>
            {p.reasoning && (
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: DARK.muted, fontSize: 11 }}>推理</span>
                <p style={{ margin: '4px 0', color: DARK.text, lineHeight: 1.6 }}>{p.reasoning}</p>
              </div>
            )}
            {p.analysis_plan && (
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: DARK.muted, fontSize: 11 }}>分析计划</span>
                <p style={{ margin: '4px 0', color: DARK.text, lineHeight: 1.6 }}>{p.analysis_plan}</p>
              </div>
            )}
            <div>
              <span style={{ color: DARK.muted, fontSize: 11 }}>激活的 Agent</span>
              <div style={{ marginTop: 4 }}>
                {p.activated_agents.map((a: string) => (
                  <span key={a} style={{ display: 'inline-block', fontSize: 11, padding: '2px 10px', borderRadius: 10, background: 'rgba(99,102,241,0.12)', color: '#a5b4fc', margin: '2px 4px 2px 0' }}>
                    {agentLabels[a] || a}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ),
      }]}
    />
  );
}

const LABEL_MAP: Record<string, string> = {
  supervisor: '🧠 规划中', sales_agent: '📊 销售分析', crm_agent: '👥 CRM分析',
  finance_agent: '💰 财务分析', inventory_agent: '📦 库存分析', supply_chain_agent: '🚚 供应链分析',
  aggregator: '📋 整合', chart_advisor: '📈 图表', report_agent: '📝 报告',
  reflection_agent: '✅ 质检', save_memory: '💾 保存',
  /* 后端部分事件使用短节点名 */
  sales: '📊 销售分析', crm: '👥 CRM分析', finance: '💰 财务分析',
  inventory: '📦 库存分析', supply_chain: '🚚 供应链分析', report: '📝 报告',
};

/* 进度步骤固定顺序（对齐原生 STEPS 常量） */
const STEPS_ORDER = [
  'supervisor', 'sales_agent', 'crm_agent', 'finance_agent', 'inventory_agent',
  'supply_chain_agent', 'aggregator', 'chart_advisor', 'report_agent',
  'reflection_agent', 'save_memory',
];

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  /* 消息唯一 id（反馈状态 key；recordId 可能为 null，不能用作 key） */
  uid?: string;
  /* 触发该报告的提问（导出命名用；多轮会话下与消息一一配对） */
  question?: string;
  html?: string;
  rawReport?: string;
  charts?: ChartSpec[];
  dataSources?: DataSource[];
  followups?: string[];
  recordId?: number | null;
  supervisorPlan?: SupervisorPlanData | string | null;
  time?: string;
}

/* 空状态快捷统计（/dashboard/overview 子集） */
interface QuickStats {
  today_sales?: number;
  yesterday_sales?: number;
  week_refund_rate?: number;
  active_stores?: number;
}

/* ══════════════════════════════════════════════════════════
   报告解析管线已抽取至 src/lib/report.ts（Analysis / Share 共用）
   ══════════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════════════
   反馈弹窗（对齐原生版 showFeedback / /feedback/submit）
   ══════════════════════════════════════════════════════════ */
function FeedbackModal({ open, rating, recordId, onClose, onDone }: {
  open: boolean; rating: 'helpful' | 'bad' | null; recordId: number | null;
  onClose: () => void; onDone: (ok: boolean) => void;
}) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    if (!recordId) { onDone(false); return; }
    setSubmitting(true); setError('');
    try {
      await client.post('/feedback/submit', { analysis_history_id: recordId, rating, reason: reason.trim() || null });
      onDone(true);
    } catch (e) {
      setError(errMsg(e, '提交失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open} title="反馈" onCancel={onClose}
      okText="提交反馈" cancelText="取消"
      confirmLoading={submitting} onOk={submit}
    >
      <div style={{ marginBottom: 12 }}>
        {rating === 'helpful' ? <Tag color="green">👍 有帮助</Tag> : <Tag color="red">👎 没有帮助</Tag>}
        <Text style={{ color: DARK.muted, fontSize: 12 }}>反馈有助于改进报告质量（可选填写原因）</Text>
      </div>
      <Input.TextArea
        value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="选填：哪里可以改进？" autoSize={{ minRows: 2, maxRows: 5 }}
      />
      {error && <Text type="danger" style={{ fontSize: 12 }}>{error}</Text>}
    </Modal>
  );
}

/* ══════════════════════════════════════════════════════════
   消息气泡
   ══════════════════════════════════════════════════════════ */
function MessageBubble({ index, msg, feedback, onFeedback, onFollowup, onCopy, onShare, onExportPdf, onExportImage, onDownloadMd, onPrint }: {
  index: number;
  msg: Msg;
  feedback: 'helpful' | 'bad' | null;
  onFeedback: (r: 'helpful' | 'bad') => void;
  onFollowup: (q: string) => void;
  onCopy: (html: string) => void;
  onShare: (recordId: number | null) => void;
  onExportPdf: (msg: Msg) => void;
  onExportImage: (msg: Msg, index: number) => void;
  onDownloadMd: (msg: Msg) => void;
  onPrint: (msg: Msg) => void;
}) {
  const isUser = msg.role === 'user';

  return (
    <Card size="small" className="msg-card" data-role={msg.role} data-msg-index={index} style={{
      marginBottom: 12,
      background: isUser ? '#2d2d44' : DARK.cardBg,
      borderColor: DARK.border,
    }}>
      {isUser ? (
        <div style={{ color: DARK.text, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
      ) : (
        <>
          {/* 分析规划（对齐原生 buildSupervisorPlan，展示 Multi-Agent 协作） */}
          <SupervisorPlan plan={msg.supervisorPlan} />
          {/* 报告正文（DOMPurify 净化后的 markdown） */}
          {msg.html && <div className="md-body" dangerouslySetInnerHTML={{ __html: msg.html }} />}
          {!msg.html && msg.content && (
            <div style={{ color: DARK.text, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
          )}

          {/* 图表（从报告提取的 [CHART] 标签） */}
          {!!msg.charts?.length && msg.charts.map((c, i) => (
            <div key={i} style={{ margin: '8px 0' }}>
              <ReactECharts option={buildEChartsOption(c.type, c)} style={{ height: Math.min(c.height || 400, 600) }} notMerge />
            </div>
          ))}

          {/* 数据溯源 */}
          {!!msg.dataSources?.length && (
            <Collapse
              ghost size="small" style={{ marginTop: 8 }}
              items={[{
                key: 'trace',
                label: <Text style={{ fontSize: 12, color: DARK.muted }}>📋 数据来源（{msg.dataSources.length} 条 SQL）</Text>,
                children: msg.dataSources.map((d, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <Text style={{ fontSize: 12, color: DARK.text }}>
                      {d.agent || 'Agent'} — 第 {d.id} 步：{d.claim || ''}{' '}
                      <Text type="secondary" style={{ fontSize: 11 }}>（耗时 {fmtSec(d.execution_time_ms)}，返回 {d.row_count} 行）</Text>
                    </Text>
                    <pre style={{
                      background: '#15152a', border: `1px solid ${DARK.border}`, borderRadius: 6,
                      padding: 8, fontSize: 11, color: '#8fb3ff', overflow: 'auto', margin: '4px 0 0',
                    }}>{d.sql || ''}</pre>
                  </div>
                )),
              }]}
            />
          )}

          {/* 信任分级（对齐原生 trustFooter） */}
          {msg.html && <TrustFooter />}

          {/* 推荐追问（对齐原生 buildFollowupButtons：报告正文下方独立区块，每个问题单独一行） */}
          {!!msg.followups?.length && (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8,
              marginTop: 14, paddingTop: 12, borderTop: `1px solid ${DARK.border}`,
            }}>
              {msg.followups.map((q, i) => (
                <Button key={i} size="small" onClick={() => onFollowup(q)}
                  style={{ background: DARK.bg, borderColor: DARK.accent, color: DARK.accent, fontSize: 12, borderRadius: 16 }}>
                  💬 {q}
                </Button>
              ))}
            </div>
          )}

          {/* 操作条 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            {msg.recordId && <Text style={{ fontSize: 10, color: DARK.muted, marginRight: 'auto' }}>#{msg.recordId}</Text>}
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => onCopy(msg.html || msg.content)}
              style={{ color: DARK.muted }}>复制</Button>
            <Button size="small" type="text" icon={<span>⬇️</span>} onClick={() => onDownloadMd(msg)}
              style={{ color: DARK.muted }}>MD</Button>
            <Button size="small" type="text" icon={<span>🖨️</span>} onClick={() => onPrint(msg)}
              style={{ color: DARK.muted }}>打印</Button>
            <Button size="small" type="text" icon={<PictureOutlined />} onClick={() => onExportImage(msg, index)}
              style={{ color: DARK.muted }}>长图</Button>
            <Button size="small" type="text" icon={<FilePdfOutlined />} onClick={() => onExportPdf(msg)}
              style={{ color: DARK.muted }}>PDF</Button>
            {msg.recordId && (
              <Button size="small" type="text" icon={<ShareAltOutlined />} onClick={() => onShare(msg.recordId ?? null)}
                style={{ color: DARK.muted }}>分享</Button>
            )}
          </div>

          {/* 反馈（对齐原生 feedback-bar：单独一行） */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, paddingTop: 10, borderTop: `1px solid ${DARK.border}`, fontSize: 12, color: DARK.muted, flexWrap: 'wrap' }}>
            <span>有帮助吗？</span>
            <Button size="small" type="text" icon={<span>👍</span>} disabled={!!feedback}
              onClick={() => onFeedback('helpful')}
              style={{ color: feedback === 'helpful' ? DARK.up : DARK.muted }}>有帮助</Button>
            <Button size="small" type="text" icon={<span>👎</span>} disabled={!!feedback}
              onClick={() => onFeedback('bad')}
              style={{ color: feedback === 'bad' ? DARK.down : DARK.muted }}>没有帮助</Button>
            {feedback && <Tag color={feedback === 'helpful' ? 'green' : 'red'} style={{ fontSize: 11 }}>已反馈</Tag>}
          </div>
        </>
      )}
    </Card>
  );
}

/* ══════════════════════════════════════════════════════════
   语音输入（Web Speech API，仅 Chrome/Edge 支持）
   ══════════════════════════════════════════════════════════ */
/* TS DOM 库未内置 webkitSpeechRecognition，用最小结构类型描述所需能力 */
interface SRResultEvent {
  resultIndex: number;
  results: { length: number; [i: number]: { [j: number]: { transcript: string } } };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SRResultEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}
type SRConstructor = new () => SpeechRecognitionLike;

function useVoice(onResult: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);

  const toggle = useCallback(() => {
    if (listening) {
      try { recRef.current?.stop(); } catch { /* noop */ }
      return;
    }
    const w = window as unknown as { SpeechRecognition?: SRConstructor; webkitSpeechRecognition?: SRConstructor };
    const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SR) { return; }
    const rec = new SR();
    rec.lang = 'zh-CN';
    rec.continuous = false;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let t = '';
      for (let i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript;
      onResult(t);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    try { rec.start(); setListening(true); } catch { /* noop */ }
  }, [listening, onResult]);

  return { listening, toggle };
}

/* ══════════════════════════════════════════════════════════
   主页面
   ══════════════════════════════════════════════════════════ */
export default function AnalysisPage() {
  const location = useLocation();
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [quickStats, setQuickStats] = useState<QuickStats | null>(null);
  const [fbState, setFbState] = useState<Record<string, 'helpful' | 'bad' | null>>({});
  const [fbModal, setFbModal] = useState<{ open: boolean; rating: 'helpful' | 'bad'; recordId: number | null; uid: string }>({ open: false, rating: 'helpful', recordId: null, uid: '' });
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastQuestionRef = useRef('');
  const msgUidRef = useRef(0);

  const { role } = useAuth();
  const { sessionId } = useAppStore();
  const { steps, phaseTitle, streamText, isStreaming, finalData, error: streamError, analyze, abort } = useSSE();
  const { message } = AntApp.useApp();

  /* SSE 错误提示（超时/断连/HTTP 错误不再静默） */
  useEffect(() => {
    if (streamError) message.error(streamError);
  }, [streamError, message]);

  /* 离开分析页恢复默认标题 */
  useEffect(() => () => { document.title = '企业智能经营分析平台 V4'; }, []);

  const [shareModal, setShareModal] = useState<{ open: boolean; url: string; recordId: number | null }>({ open: false, url: '', recordId: null });
  const [exporting, setExporting] = useState<'image' | 'pdf' | null>(null);
  const [similar, setSimilar] = useState<{ id: number; question: string }[]>([]);
  /* 相似推荐请求序号：输入变化时递增，旧关键词慢响应到达后直接丢弃（防乱序覆盖） */
  const similarSeqRef = useRef(0);

  const voice = useVoice((text) => setQuestion(text));

  /* 相似历史问题推荐（后端 /analysis/similar 向量搜索） */
  useEffect(() => {
    const q = question.trim();
    /* 每次输入变化都递增请求序号：旧关键词的慢响应一律丢弃 */
    const seq = ++similarSeqRef.current;
    if (!q || q.length < 4 || isStreaming) { setSimilar([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await client.get('/analysis/similar', { params: { query: q, limit: 3 } });
        if (seq !== similarSeqRef.current) return; /* 已有更新的输入，丢弃旧响应 */
        /* 清洗：去掉历史脏数据里 [系统指令] ranking hint（换行后的系统注释），只保留原始问题 */
        const cleanQ = (s: string) => s.split('\n')[0].trim().replace(/\s*\[系统指令\].*$/, '');
        setSimilar(
          (res.data.results || [])
            .map((r: { id: number; question?: string }) => ({ id: r.id, question: cleanQ(r.question || '') }))
            .filter((r: { question: string }) => r.question && r.question !== q)
            .slice(0, 3),
        );
      } catch { if (seq === similarSeqRef.current) setSimilar([]); }
    }, 400);
    return () => clearTimeout(t);
  }, [question, isStreaming]);

  /* 从历史页跳转 → 回溯指定记录 */
  const navigate = useNavigate();
  const recordIdFromState = (location.state as { recordId?: number } | null)?.recordId;
  useEffect(() => {
    if (recordIdFromState) {
      viewHistoryDetail(recordIdFromState);
      /* 用 react-router 的 API 清掉跳转来源 state（原生 replaceState 会破坏 history key） */
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordIdFromState]);

  /* 会话切换（新建会话）→ 重置整个对话区为空白提问界面
     修复：在历史回溯详情页点「新建会话」时 navigate 同路径是 no-op，
     messages 必须由 sessionId 变化主动清空 */
  useEffect(() => {
    setMessages([]);
    setQuickStats(null);
    setFbState({});
    setQuestion('');
  }, [sessionId]);

  /* 空状态快捷统计（对齐原生 renderEmptyStats → /dashboard/overview） */
  useEffect(() => {
    if (messages.length || quickStats) return;
    client.get('/dashboard/overview').then((res) => setQuickStats(res.data)).catch(() => setQuickStats(null));
  }, [messages.length, quickStats]);

  /* 自动滚到底部 */
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [streamText, messages, isStreaming]);

  /* 流式完成 → 组装 assistant 消息 */
  useEffect(() => {
    if (!finalData) return;
    const { report, data_sources, followup_questions, record_id, errors, supervisor_plan } = finalData;
    if (!report && !errors?.length) return;
    const { html, charts } = processReport(report || '');
    const hasError = errors?.length;
    const msg: Msg = {
      role: 'assistant',
      uid: `m${++msgUidRef.current}`,
      content: hasError ? `（质检未通过：${errors.map((e) => e.dimension || '未知维度').join('、')}）\n\n` + (report || '') : (report || ''),
      question: lastQuestionRef.current,
      rawReport: report || '',
      html: hasError ? undefined : html,
      charts,
      dataSources: data_sources || [],
      followups: followup_questions || [],
      recordId: record_id ?? null,
      supervisorPlan: supervisor_plan || undefined,
      time: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, msg]);
    setFbState((prev) => ({ ...prev, [msg.uid!]: null }));
    /* 动态标题（对齐原生） */
    if (report) document.title = `报告 · ${lastQuestionRef.current.slice(0, 20)} - EIA V4`;
  }, [finalData]);

  const handleSend = useCallback(async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || isStreaming) return;
    setQuestion('');
    lastQuestionRef.current = text;
    setMessages((prev) => [...prev, { role: 'user', content: text, time: new Date().toISOString() }]);
    await analyze(text, sessionId);
  }, [question, isStreaming, analyze, sessionId]);

  const handleFollowup = (q: string) => handleSend(q);

  const handleCopy = async (html: string) => {
    try {
      await navigator.clipboard.writeText(html.replace(/<[^>]+>/g, '').replace(/\n{3,}/g, '\n\n'));
      message.success('已复制到剪贴板');
    } catch { /* 剪贴板不可用时忽略 */ }
  };

  /* ── 分享：生成链接 → 系统分享或弹窗（对齐原生版 openShare） ── */
  const handleShare = async (recordId: number | null) => {
    if (!recordId) { message.warning('该报告暂不支持分享'); return; }
    try {
      const res = await client.post('/analysis/share', { record_id: recordId });
      const url = window.location.origin + res.data.url;
      if (navigator.share) {
        try {
          await navigator.share({ title: '经营分析报告', text: 'AI 生成的经营分析报告', url });
          return;
        } catch { /* 用户取消或失败 → 回退到链接弹窗 */ }
      }
      setShareModal({ open: true, url, recordId });
    } catch (e) { message.error(errMsg(e, '生成分享链接失败')); }
  };

  const handleRevokeShare = async () => {
    if (!shareModal.recordId) return;
    try {
      await client.delete(`/analysis/share?record_id=${shareModal.recordId}`);
      setShareModal((s) => ({ ...s, url: '已取消分享，原链接已失效' }));
      message.success('已取消分享');
    } catch (e) { message.error(errMsg(e, '取消失败')); }
  };

  /* ── 长图导出（html2canvas，对齐原生版 exportLongImage） ──
     按 data-msg-index 定位点击的报告卡片：多轮对话时导出的是对应那条报告，
     不再错误地抓取"最后一张 assistant 卡片" */
  const handleExportImage = async (msg: Msg, index: number) => {
    const card = document.querySelector(`.msg-card[data-msg-index="${index}"]`) as HTMLElement | null;
    if (!card) { message.warning('暂无可导出的报告'); return; }
    setExporting('image');
    try {
      const canvas = await html2canvas(card, { scale: 2, backgroundColor: '#ffffff', useCORS: true, logging: false });
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/png'));
      if (!blob) throw new Error('toBlob failed');
      const name = (msg.question || '经营分析报告').slice(0, 20).replace(/[\\/:*?"<>|]/g, '');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `报告_${name || '经营分析报告'}.png`; a.click();
      URL.revokeObjectURL(url);
      message.success('长图已导出');
    } catch (e) { console.warn(e); message.error('长图导出失败'); }
    finally { setExporting(null); }
  };

  /* ── PDF 导出（复用周报导出接口，对齐原生版 exportPDF） ── */
  const handleExportPdf = async (msg: Msg) => {
    if (!msg.rawReport) { message.warning('无报告内容'); return; }
    const question = msg.question || '经营分析报告';
    setExporting('pdf');
    try {
      const res = await client.post('/weekly/export', { report: msg.rawReport, title: question.slice(0, 40) }, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'report.pdf'; a.click();
      URL.revokeObjectURL(url);
      message.success('PDF 已下载');
    } catch (e) {
      message.error(errMsg(e, 'PDF 导出失败'));
    } finally { setExporting(null); }
  };

  const submitFeedback = (rating: 'helpful' | 'bad', recordId: number | null, uid: string) => {
    setFbModal({ open: true, rating, recordId, uid });
  };
  const onFeedbackDone = (ok: boolean) => {
    setFbModal((s) => ({ ...s, open: false }));
    if (ok && fbModal.recordId && fbModal.uid) {
      setFbState((prev) => ({ ...prev, [fbModal.uid]: fbModal.rating }));
    }
  };

  /* ── 历史回溯（从 /history 页跳转，对齐原生 viewHistoryDetail） ── */
  const viewHistoryDetail = useCallback(async (id: number) => {
    try {
      const res = await client.get(`/analysis/history/${id}`);
      const d = res.data;
      const { html, charts } = processReport(d.report || '');
      setMessages([
        { role: 'user', content: d.question || '', time: d.created_at },
        {
          role: 'assistant', uid: `m${++msgUidRef.current}`, content: d.report || '', question: d.question || '', rawReport: d.report || '', html,
          charts, dataSources: d.data_sources || [], followups: d.followup_questions || [],
          recordId: d.id ?? null, supervisorPlan: d.supervisor_plan || undefined, time: d.created_at,
        },
      ]);
    } catch (e) { console.error(e); message.error(errMsg(e, '加载历史记录失败')); }
  }, [message]);

  /* ── MD 下载（对齐原生 downloadMD） ── */
  const handleDownloadMd = (msg: Msg) => {
    const content = msg.rawReport || msg.content;
    if (!content) return;
    const q = msg.question || 'report';
    const fn = q.replace(/[<>:"/\\|?*]/g, '_').slice(0, 40) + '.md';
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fn; a.click();
    URL.revokeObjectURL(url);
    message.success('报告已下载');
  };

  /* ── 打印报告（对齐原生 window.print） ── */
  const handlePrint = (msg: Msg) => {
    const content = msg.rawReport || msg.content;
    if (!content) return;
    const win = window.open('', '_blank');
    if (!win) { message.warning('浏览器阻止了弹窗'); return; }
    const mdHtml = renderMarkdown(convertTextTables(stripFollowupTags(content)));
    win.document.write(`<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>经营分析报告</title>
      <style>body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:820px;margin:24px auto;padding:0 20px;color:#1e293b;line-height:1.75}
      h1{font-size:20px}h2{font-size:17px;border-left:3px solid #4f46e5;padding-left:8px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #e2e8f0;padding:6px 10px;text-align:left}th{background:#f8fafc}</style></head>
      <body>${mdHtml}<hr style="margin-top:32px"><p style="font-size:11px;color:#94a3b8">本报告由企业洞察 Agent 基于多 Agent 协作自动生成，仅供经营决策参考，数据与结论以实际业务为准。</p></body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); }, 300);
  };

  /* ── 流式进度气泡（对齐原生 #pM：spinner + 阶段文案 + 固定顺序步骤胶囊） ── */
  const renderProgress = () => {
    if (!steps) return null;
    return (
      <Card size="small" style={{ marginBottom: 12, background: DARK.cardBg, borderColor: DARK.border }}>
        {/* spinner + 当前阶段文案（phase 事件 message） */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <Spin size="small" />
          <span style={{ fontSize: 13, color: DARK.muted }}>{phaseTitle || '🧠 规划中...'}</span>
        </div>
        {/* 固定顺序步骤：pending 半透明 / active 高亮 / done 绿 ✓ */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {STEPS_ORDER.map((k) => {
            const st = steps[k];
            const done = st === 'done';
            const active = st === 'active';
            return (
              <span key={k} style={{
                fontSize: 12, padding: '4px 12px', borderRadius: 20,
                display: 'inline-flex', alignItems: 'center', gap: 4,
                border: `1px solid ${done ? DARK.up : active ? DARK.accent : DARK.border}`,
                color: done ? DARK.up : active ? '#a5b4fc' : DARK.muted,
                background: active ? 'rgba(99,102,241,0.1)' : 'transparent',
                opacity: active || done ? 1 : 0.5,
                transition: 'all .3s ease',
              }}>
                {LABEL_MAP[k] || k}{done && ' ✓'}
              </span>
            );
          })}
        </div>
      </Card>
    );
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <div ref={scrollRef} style={{ overflow: 'auto', marginBottom: 16, minHeight: 'calc(100vh - 220px)', maxHeight: 'calc(100vh - 220px)' }}>
          {messages.length === 0 && !isStreaming && (
            <div style={{ textAlign: 'center', paddingTop: 30 }}>
              {/* 🤖 欢迎语（对齐原生 empty-state） */}
              <div style={{ fontSize: 44 }}>🤖</div>
              <div style={{ fontSize: 17, color: DARK.text, margin: '12px 0 4px' }}>有什么经营问题需要分析？</div>
              <div style={{ fontSize: 13, color: DARK.muted, marginBottom: 24 }}>
                5 个 AI Agent 并行分析销售、会员、财务、库存、供应链数据
              </div>

              {/* 能力卡片（对齐原生 cap-cards） */}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 24 }}>
                {CAP_CARDS.map((c) => (
                  <div key={c.title} onClick={() => setQuestion(c.question)} style={{
                    width: 140, padding: '14px 10px', borderRadius: 12, cursor: 'pointer',
                    background: DARK.cardBg, border: `1px solid ${DARK.border}`,
                  }}>
                    <div style={{ fontSize: 22, marginBottom: 6 }}>{c.icon}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: DARK.text }}>{c.title}</div>
                    <div style={{ fontSize: 11, color: DARK.muted, marginTop: 2 }}>{c.desc}</div>
                  </div>
                ))}
              </div>

              {/* 快捷统计（对齐原生 quick-stats，数据来自看板） */}
              {quickStats && (
                <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 24 }}>
                  {[
                    { label: '今日销售额', value: formatMoney(quickStats.today_sales || 0) },
                    { label: '昨日销售额', value: formatMoney(quickStats.yesterday_sales || 0) },
                    { label: '退款率（7天）', value: (quickStats.week_refund_rate ?? 0).toFixed(1) + '%' },
                    { label: '活跃门店', value: String(quickStats.active_stores || 0) },
                  ].map((s) => (
                    <div key={s.label} style={{
                      minWidth: 110, padding: '10px 14px', borderRadius: 10, textAlign: 'center',
                      background: DARK.bg, border: `1px solid ${DARK.border}`,
                    }}>
                      <div style={{ fontSize: 15, fontWeight: 700, color: DARK.text }}>{s.value}</div>
                      <div style={{ fontSize: 11, color: DARK.muted, marginTop: 2 }}>{s.label}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* 快捷问题网格（对齐原生 quick-grid，按角色 + 点击直接提问） */}
              <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
                {(ROLE_QUICK_QUESTIONS[role || ''] || DEFAULT_QUICK_QUESTIONS).map((q) => (
                  <Button key={q} size="small" onClick={() => handleSend(q)}
                    style={{ background: DARK.cardBg, borderColor: DARK.border, color: DARK.text }}>{q}</Button>
                ))}
              </div>
              <p style={{ fontSize: 12, color: DARK.muted, marginTop: 18 }}>
                💡 支持文字或 🎤 语音输入，AI 将在 60 秒内生成诊断报告
              </p>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              index={i}
              msg={msg}
              feedback={fbState[msg.uid ?? ''] ?? null}
              onFeedback={(r) => submitFeedback(r, msg.recordId ?? null, msg.uid ?? '')}
              onFollowup={handleFollowup}
              onCopy={handleCopy}
              onShare={handleShare}
              onExportPdf={handleExportPdf}
              onExportImage={handleExportImage}
              onDownloadMd={handleDownloadMd}
              onPrint={handlePrint}
            />
          ))}

          {/* 流式进度气泡（对齐原生：对话流内展示，报告出来后消失） */}
          {isStreaming && renderProgress()}

          {isStreaming && streamText && (
            <Card size="small" style={{ marginBottom: 12, background: DARK.cardBg, borderLeft: `3px solid ${DARK.accent}` }}>
              {/* 去掉 [FOLLOWUP...] 标签：追问在报告完成后以按钮形式展示在报告下方，不在流式正文中出现 */}
              <div style={{ color: DARK.text, whiteSpace: 'pre-wrap' }}>{stripFollowupTags(streamText)}</div>
            </Card>
          )}
        </div>

        <Card size="small" style={{ position: 'sticky', bottom: 0, background: DARK.bg, borderColor: DARK.border }}>
          {/* 相似历史问题推荐 */}
          {similar.length > 0 && (
            <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, color: DARK.muted }}>🔍 相似历史问题：</span>
              {similar.map((s) => (
                <Button key={s.id} size="small" type="link" onClick={() => setQuestion(s.question)}
                  style={{ fontSize: 12, padding: '0 6px', color: DARK.accent }}>{s.question}</Button>
              ))}
            </div>
          )}
          <Space.Compact style={{ width: '100%' }}>
            <Input.TextArea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onPressEnter={(e) => {
                /* Shift+Enter 换行 / 中文输入法组词中不触发发送 */
                if (e.shiftKey || (e.nativeEvent as KeyboardEvent).isComposing) return;
                e.preventDefault(); handleSend();
              }}
              placeholder="输入经营问题，例如：分析华东区最近一周的销售趋势..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={isStreaming}
              style={{ background: DARK.cardBg, borderColor: DARK.border, color: DARK.text }}
            />
            <Tooltip title={voice.listening ? '停止语音' : '语音输入（Chrome/Edge）'}>
              <Button
                aria-label={voice.listening ? '停止语音' : '语音输入'}
                icon={voice.listening ? <StopOutlined /> : <AudioOutlined />}
                onClick={voice.toggle}
                style={{ background: DARK.cardBg, borderColor: DARK.border, color: voice.listening ? DARK.down : DARK.text }}
              />
            </Tooltip>
            {/* 停止按钮（对齐原生 stopBtn，流式时显示） */}
            {isStreaming ? (
              <Button danger icon={<StopOutlined />} onClick={abort}>停止</Button>
            ) : (
              <Button type="primary" icon={<SendOutlined />} onClick={() => handleSend()}>提问</Button>
            )}
          </Space.Compact>
        </Card>

      {/* ── 反馈弹窗 ── */}
      <FeedbackModal
        open={fbModal.open} rating={fbModal.rating} recordId={fbModal.recordId}
        onClose={() => setFbModal((s) => ({ ...s, open: false }))}
        onDone={onFeedbackDone}
      />

      {/* ── 分享弹窗 ── */}
      <Modal
        title="分享报告" open={shareModal.open}
        onCancel={() => setShareModal((s) => ({ ...s, open: false }))}
        footer={null} width={480}
      >
        <Text style={{ color: DARK.muted, fontSize: 12 }}>分享链接 30 天内有效，任何持有链接的人可查看该报告</Text>
        <Space.Compact style={{ width: '100%', marginTop: 12 }}>
          <Input readOnly value={shareModal.url} onFocus={(e) => e.target.select()} />
          <Button type="primary" onClick={() => { navigator.clipboard.writeText(shareModal.url).then(() => message.success('链接已复制')); }}
            disabled={shareModal.url.startsWith('已取消')}>复制链接</Button>
        </Space.Compact>
        <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Button danger size="small" onClick={handleRevokeShare} disabled={shareModal.url.startsWith('已取消')}>
            取消分享
          </Button>
        </div>
      </Modal>

      {/* 导出中提示 */}
      {exporting && <div style={{ position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 2000 }}>
        <Tag color="processing">{exporting === 'image' ? '🖼️ 正在生成长图，请稍候...' : '📄 正在生成 PDF...'}</Tag>
      </div>}
    </div>
  );
}
