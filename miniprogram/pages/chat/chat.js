// pages/chat/chat.js
const config = require('../../utils/config.js');
const { streamRequest } = require('../../utils/sse.js');
const { get, post } = require('../../utils/request.js');
const { cleanReport, parseCharts } = require('../../utils/report.js');

// 面向用户的业务语义进度（5 步），不暴露内部 Agent 架构
const AGENT_STEPS = [
  { key: 'understand', label: '理解问题', icon: '🎯' },
  { key: 'query', label: '查询数据', icon: '📊' },
  { key: 'chart', label: '生成图表', icon: '📈' },
  { key: 'write', label: '撰写报告', icon: '✍️' },
  { key: 'quality', label: '质量检查', icon: '✅' },
];

// 后端节点名 → 业务步骤映射
const NODE_TO_STEP = {
  supervisor: 'understand',
  sales_agent: 'query',
  crm_agent: 'query',
  finance_agent: 'query',
  inventory_agent: 'query',
  supply_chain_agent: 'query',
  aggregator: 'query',
  chart_advisor: 'chart',
  report_agent: 'write',
  reflection_agent: 'quality',
};

Page({
  data: {
    question: '',
    messages: [],
    loading: false,
    progressSteps: AGENT_STEPS,
    currentStepIndex: -1,
    stepStatus: [],
    reportContent: '',
    reportRaw: '', // 原始 markdown（含表格/CHART 标记），供完整报告页结构化渲染
    reportTitle: '',
    reportCharts: [],
    showProgress: false,
    showProgressDetail: false,
    sessionId: null,
    recordId: null,
    followupQuestions: [],
    historySessions: [],
    showHistory: false,
    prefillQuestion: '',
    abortController: null,
    streamEnabled: config.streamEnabled, // 同步模式隐藏"停止生成"按钮（同步请求不支持中断）
    waitSeconds: 0, // 同步模式等待计时（无进度事件时的存活反馈）
  },

  toggleProgressDetail() {
    this.setData({ showProgressDetail: !this.data.showProgressDetail });
  },

  onLoad(options) {
    this.setData({
      stepStatus: AGENT_STEPS.map(() => 'pending'),
    });
    this.loadHistory();
  },

  onShow() {
    const app = getApp();
    // 从 globalData 读取首页告警卡片传递的预填问题
    const prefill = app.globalData.prefillQuestion || this.data.prefillQuestion;
    if (prefill) {
      this.setData({ question: prefill, prefillQuestion: '' });
      app.globalData.prefillQuestion = '';
    }
    // 「我的-历史报告」入口：跳转后自动展开历史抽屉
    if (app.globalData.openHistoryDrawer) {
      app.globalData.openHistoryDrawer = false;
      this.setData({ showHistory: true });
    }
  },

  onUnload() {
    if (this.data.abortController) {
      this.data.abortController.abort();
    }
    this._stopWaitTimer();
  },

  // 同步模式等待计时（每秒 +1）：驱动虚拟 5 步进度 + 秒数显示
  _startWaitTimer() {
    this._stopWaitTimer();
    this.setData({
      waitSeconds: 0,
      currentStepIndex: -1,
      stepStatus: AGENT_STEPS.map(() => 'pending'),
    });
    this._waitTimer = setInterval(() => {
      const sec = this.data.waitSeconds + 1;
      this.setData({ waitSeconds: sec });
      this._advanceSyncProgress(sec);
    }, 1000);
  },

  // 同步模式无后端进度事件：按时间表推进虚拟 5 步（与后端实际耗时分布对齐）
  // 后端耗时：supervisor 2-5s → 领域 Agent 并行查询 10-20s（最长）→ 图表 3-6s
  //          → 报告撰写 5-10s → reflection 质检 3-5s（总 25-40s）
  _advanceSyncProgress(sec) {
    const SCHEDULE = [
      { idx: 0, at: 0 },   // 理解问题
      { idx: 1, at: 4 },   // 查询数据（领域 Agent 并行，耗时最长）
      { idx: 2, at: 18 },  // 生成图表
      { idx: 3, at: 26 },  // 撰写报告
      { idx: 4, at: 34 },  // 质量检查（之后即完成，避免长时间停滞）
    ];
    const target = SCHEDULE.filter((s) => sec >= s.at).pop();
    if (!target || target.idx === this.data.currentStepIndex) return;
    const status = AGENT_STEPS.map(() => 'pending');
    for (let i = 0; i < target.idx; i++) status[i] = 'done';
    status[target.idx] = 'running';
    this.setData({ stepStatus: status, currentStepIndex: target.idx });
  },

  _stopWaitTimer() {
    if (this._waitTimer) {
      clearInterval(this._waitTimer);
      this._waitTimer = null;
    }
  },

  onInputQuestion(e) {
    const question = e.currentTarget.dataset.question || e.detail.value;
    this.setData({ question });
  },

  onSuggestionTap(e) {
    const question = e.currentTarget.dataset.question;
    if (question) {
      this.setData({ question });
      // 自动发送
      setTimeout(() => {
        this.handleAsk();
      }, 100);
    }
  },

  loadHistory() {
    const history = wx.getStorageSync('chatHistory') || [];
    this.setData({ historySessions: history });
  },

  toggleHistory() {
    this.setData({ showHistory: !this.data.showHistory });
  },

  loadSession(e) {
    const idx = e.currentTarget.dataset.index;
    const session = this.data.historySessions[idx];
    if (!session) return;

    this.setData({
      showHistory: false,
      messages: session.messages || [],
      reportContent: session.report || '',
      reportTitle: session.title || '',
      recordId: session.record_id,
      // 恢复会话 ID 以延续多轮上下文；旧历史无 session_id 时下次提问自动新建
      sessionId: session.session_id || null,
    });
  },

  clearHistory() {
    wx.showModal({
      title: '确认清除',
      content: '将清空所有本地历史记录',
      success: (res) => {
        if (res.confirm) {
          wx.removeStorageSync('chatHistory');
          this.setData({ historySessions: [] });
        }
      },
    });
  },

  async handleAsk() {
    const question = this.data.question.trim();
    if (!question || this.data.loading) return;

    const userMsg = {
      role: 'user',
      content: question,
      time: this._formatTime(new Date()),
    };

    this.setData({
      loading: true,
      showProgress: true,
      currentStepIndex: -1,
      stepStatus: AGENT_STEPS.map(() => 'pending'),
      messages: [...this.data.messages, userMsg],
      reportContent: '',
      reportRaw: '',
      reportTitle: '',
      reportCharts: [],
      question: '',
      scrollTarget: 'msg-bottom',
    });

    // 多轮对话：首次提问时创建会话（失败则降级为单次分析，不阻塞提问）
    // ⚠️ 会话创建必须限时 5s：真机热点链路丢包时 wx.request 可能长时间挂起，
    // await 不返回会导致提问请求永远不发出（曾真机卡"正在分析"4 分钟）
    let sessionId = this.data.sessionId;
    if (!sessionId) {
      try {
        const sess = await post(config.endpoints.sessionCreate, undefined, undefined, 5000);
        sessionId = sess.session_id;
        this.setData({ sessionId });
      } catch (e) {
        console.warn('创建会话失败，降级为单次分析', e);
      }
    }

    // V1.0 默认同步模式（enableChunked 流式不稳定，见 config.streamEnabled 注释）
    if (!config.streamEnabled) {
      this._analyzeSync(question, sessionId);
      return;
    }

    const controller = streamRequest({
      url: config.endpoints.analyzeStream,
      // 后端 AnalysisRequest 要求字段名是 question，不是 query
      data: { question: question, session_id: sessionId || undefined },

      onPhase: (payload) => {
        // 后端字段名是 'node'，映射为 5 步业务进度
        const stepKey = NODE_TO_STEP[payload.node || payload.node_name || ''] || '';
        const idx = AGENT_STEPS.findIndex(s => s.key === stepKey);
        if (idx >= 0) {
          const status = [...this.data.stepStatus];
          // 将之前 running 的步骤标记为 done
          for (let i = 0; i < idx; i++) {
            if (status[i] === 'running') status[i] = 'done';
          }
          status[idx] = 'running';
          this.setData({
            stepStatus: status,
            currentStepIndex: idx,
          });
        }
      },

      onStep: (payload) => {
        const stepKey = NODE_TO_STEP[payload.node || payload.node_name || ''] || '';
        const idx = AGENT_STEPS.findIndex(s => s.key === stepKey);
        if (idx >= 0) {
          const status = [...this.data.stepStatus];
          status[idx] = 'done';
          this.setData({ stepStatus: status });
        }
      },

      onDone: (payload) => {
        this._renderReport(payload, question);
      },

      onError: (payload) => {
        // 流式失败 → 自动降级为同步 /analyze（命中 Redis 缓存时秒回，用户几乎无感）
        this._fallbackSyncAnalyze(question, sessionId, (payload && payload.user_message) || '分析失败，请重试');
      },
    });

    this.setData({ abortController: controller });
  },

  // 同步模式主路径：POST /analysis/analyze（与流式同一后端，普通请求机制，可靠）
  async _analyzeSync(question, sessionId) {
    // 同步模式无进度事件：启动计时器给用户"还在运行"的反馈
    this._startWaitTimer();
    try {
      const resp = await post(config.endpoints.analyze, {
        question: question,
        session_id: sessionId || undefined,
      });
      if (resp && resp.report) {
        this._renderReport(resp, question);
        return;
      }
      // 200 但无报告：展示后端给出的用户友好错误（如 LLM 失败）
      this._stopWaitTimer();
      const err = (resp && resp.agent_errors && resp.agent_errors[0] && resp.agent_errors[0].user_message) || '分析失败，请重试';
      this.setData({ loading: false, showProgress: false });
      wx.showToast({ title: err, icon: 'none', duration: 3000 });
    } catch (e) {
      console.warn('同步分析失败', e);
      this._stopWaitTimer();
      this.setData({ loading: false, showProgress: false });
      wx.showToast({ title: (e && e.message) || '网络连接失败', icon: 'none', duration: 3000 });
    }
  },

  // 流式失败兜底：改用同步 /analyze 端点（移动端方案 §3.3 降级策略）
  // 流式请求在服务端已跑完时，分析结果已写入 Redis 缓存，此调用会命中缓存秒回
  async _fallbackSyncAnalyze(question, sessionId, streamError) {
    // 防止用户手动停止后仍触发降级
    if (!this.data.loading) return;
    // 降级期间同样给虚拟进度反馈（未命中缓存时也要等 25-40s）
    this._startWaitTimer();
    try {
      const resp = await post(config.endpoints.analyze, {
        question: question,
        session_id: sessionId || undefined,
      });
      if (resp && resp.report) {
        this._renderReport(resp, question);
        wx.showToast({ title: '流式连接异常，已自动切换普通模式', icon: 'none', duration: 2000 });
        return;
      }
    } catch (e) {
      console.warn('同步降级分析也失败', e);
    }
    // 双路径都失败 → 展示流式原始错误
    this.setData({ loading: false, showProgress: false });
    wx.showToast({ title: streamError, icon: 'none', duration: 3000 });
  },

  // 统一渲染报告（流式 done 事件 / 同步响应共用）
  _renderReport(resp, question) {
    this._stopWaitTimer();
    // 清洗：剔除 [FOLLOWUP] 标记和 markdown 噪声（追问建议由 followup_questions 字段渲染 chips）
    const report = cleanReport(resp.report || '');
    // 后端 done 事件无 title 字段，用问题本身作为报告标题（比"分析报告"更有辨识度）
    const title = question;
    this.setData({
      loading: false,
      showProgress: false,
      reportContent: report,
      reportRaw: resp.report || '',
      reportTitle: title,
      // 后端响应无 charts 字段：图表数据内嵌在报告文本的 [CHART:...] 标记中
      reportCharts: resp.charts || parseCharts(resp.report || ''),
      recordId: resp.record_id || '',
      followupQuestions: resp.followup_questions || [],
      stepStatus: AGENT_STEPS.map(() => 'done'),
    });
    this.setData({
      messages: [...this.data.messages, {
        role: 'assistant',
        content: report,
        time: this._formatTime(new Date()),
        title: title,
      }],
      scrollTarget: 'msg-bottom',
    });
    if (resp.record_id) {
      this._saveToHistory(question, report, title, resp.record_id);
    }
  },

  stopGeneration() {
    if (this.data.abortController) {
      this.data.abortController.abort();
      this.setData({
        loading: false,
        showProgress: false,
        abortController: null,
      });
      wx.showToast({ title: '已停止生成', icon: 'none' });
    }
  },

  viewReport() {
    wx.navigateTo({
      url: '/pages_ai/report-full/report-full',
    });
    // report-full 页 onLoad 通过 getCurrentPages 读取上一页数据（含 recordId）
    const pages = getCurrentPages();
    const currentPage = pages[pages.length - 1];
    if (currentPage) {
      currentPage.setData({
        reportContent: this.data.reportContent,
        reportRaw: this.data.reportRaw,
        reportTitle: this.data.reportTitle,
        reportCharts: this.data.reportCharts,
        recordId: this.data.recordId,
      });
    }
  },

  _saveToHistory(question, report, title, recordId) {
    const history = wx.getStorageSync('chatHistory') || [];
    // 后端 done 事件无 title 字段，直接用问题前 20 字作标题（保证历史记录可辨识）
    history.unshift({
      record_id: recordId,
      session_id: this.data.sessionId,
      title: question.slice(0, 20),
      question,
      report,
      time: this._formatTime(new Date()),
      messages: this.data.messages,
    });
    if (history.length > 20) history.length = 20;
    wx.setStorageSync('chatHistory', history);
    this.loadHistory();
  },

  _formatTime(date) {
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  },

  onShareAppMessage() {
    const question = this.data.messages.filter(m => m.role === 'user').pop();
    return {
      title: question ? question.content.slice(0, 30) : 'AI 经营分析助手',
      path: '/pages/home/home',
    };
  },
});
