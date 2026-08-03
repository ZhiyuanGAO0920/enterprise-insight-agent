// pages_ai/report-full/report-full.js
const config = require('../../utils/config.js');
const { get, post } = require('../../utils/request.js');
const { cleanReport, parseCharts, removeChartMarkers } = require('../../utils/report.js');

Page({
  data: {
    reportTitle: '分析报告',
    reportContent: '',
    reportCharts: [],
    recordId: null,
    reportSections: [],
    scrollTop: 0,
    feedbackSubmitted: false,
    feedbackRating: 0,
    feedbackReason: '',
    showFeedback: false,
    shareToken: '',
  },

  onLoad(options) {
    const pages = getCurrentPages();
    const prevPage = pages[pages.length - 2];

    if (prevPage && prevPage.data) {
      const { reportContent, reportTitle, reportCharts, recordId, reportRaw } = prevPage.data;
      // 优先用原始 markdown 解析（保留标题/表格结构）；老数据无 reportRaw 时回退清洗文本
      const raw = reportRaw || '';
      const text = raw || cleanReport(reportContent || '');
      const charts = raw ? parseCharts(raw) : (reportCharts || []);
      this.setData({
        reportContent: text,
        reportTitle: reportTitle || '分析报告',
        reportCharts: charts,
        recordId: recordId || null,
      });
      this._parseReport(text);
    }

    if (options.session_id) {
      this._loadBySession(options.session_id);
    }

    // 预取分享 token（onShareAppMessage 是同步的，必须提前拿到）
    this._prepareShareToken();
  },

  // 调用 /analysis/share 生成分享 token，供右上角菜单分享使用
  async _prepareShareToken() {
    const recordId = this.data.recordId;
    if (!recordId) return;
    try {
      const resp = await post(config.endpoints.share, { record_id: parseInt(recordId) });
      this.setData({ shareToken: (resp && resp.token) || '' });
    } catch (e) {
      console.warn('分享 token 生成失败', e);
    }
  },

  onShareAppMessage() {
    const token = this.data.shareToken;
    return {
      title: `${this.data.reportTitle} - 企业经营助手`,
      path: token ? `/pages_share/share/share?token=${token}` : '/pages/home/home',
    };
  },

  async _loadBySession(recordId) {
    try {
      // 后端端点是 /analysis/history/{id}，不是 /analysis/session/{id}
      const resp = await get(config.endpoints.history + '/' + recordId);
      if (resp) {
        // 后端返回原始 markdown（含 [CHART] 标记）→ 解析图表 + 结构化渲染
        const raw = resp.report || '';
        this.setData({
          reportContent: raw,
          reportTitle: resp.title || this.data.reportTitle,
          reportCharts: parseCharts(raw),
          recordId: recordId,
        });
        this._parseReport(raw);
      }
    } catch (e) {
      console.warn('Failed to load session', e);
    }
  },

  // 解析 markdown 为结构化 sections：h1/h2/h3 / 段落 / 列表 / 引用 / 表格
  // 表格兼容两种格式：原始 "| a | b |" 与已清洗 "a | b"；连续 ≥2 行含管道符即识别，
  // 分隔行（|---|）跳过，第一行作表头。[CHART:...] 标记先剔除（图表单独渲染）。
  _parseReport(reportText) {
    if (!reportText) return;

    const text = removeChartMarkers(reportText);
    const sections = [];
    const lines = text.split('\n');
    let currentSection = null;
    let inList = false;
    let listItems = [];
    let inTable = false;
    let tableRows = [];

    const flushList = () => {
      if (inList && listItems.length > 0) {
        sections.push({ type: 'list', items: listItems, id: Math.random() });
        listItems = [];
        inList = false;
      }
    };

    const isSeparatorRow = (cells) =>
      cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));

    const flushTable = () => {
      if (!inTable) return;
      inTable = false;
      // 去掉纯分隔行（|--|--|）；剩余 ≥2 行才成表
      const rows = tableRows.filter((r) => !isSeparatorRow(r));
      tableRows = [];
      if (rows.length >= 2) {
        const header = rows[0];
        const body = rows.slice(1);
        // 清 cell 内粗体/反引号噪声
        const cleanCell = (c) => String(c).replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1').trim();
        sections.push({
          type: 'table',
          header: header.map(cleanCell),
          rows: body.map((r) => r.map(cleanCell)),
          id: Math.random(),
        });
      } else if (rows.length === 1) {
        sections.push({ type: 'paragraph', text: rows[0].join(' | '), id: Math.random() });
      }
    };

    for (const line of lines) {
      const trimmed = line.trim();

      if (!trimmed) {
        flushList();
        flushTable();
        if (currentSection) {
          sections.push(currentSection);
          currentSection = null;
        }
        continue;
      }

      if (trimmed.startsWith('# ')) {
        flushList();
        flushTable();
        if (currentSection) sections.push(currentSection);
        currentSection = { type: 'h1', text: trimmed.slice(2), id: Math.random() };
      } else if (trimmed.startsWith('## ')) {
        flushList();
        flushTable();
        if (currentSection) sections.push(currentSection);
        currentSection = { type: 'h2', text: trimmed.slice(3), id: Math.random() };
      } else if (trimmed.startsWith('### ')) {
        flushList();
        flushTable();
        if (currentSection) sections.push(currentSection);
        currentSection = { type: 'h3', text: trimmed.slice(4), id: Math.random() };
      } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        flushTable();
        if (!inList) flushList();
        inList = true;
        listItems.push(trimmed.slice(2));
      } else if (/^\d+\.\s/.test(trimmed)) {
        flushTable();
        if (!inList) flushList();
        inList = true;
        listItems.push(trimmed.replace(/^\d+\.\s/, ''));
      } else if (trimmed.startsWith('> ')) {
        flushList();
        flushTable();
        if (currentSection) sections.push(currentSection);
        currentSection = { type: 'quote', text: trimmed.slice(2), id: Math.random() };
      } else if (trimmed.indexOf('|') >= 0) {
        // 表格行："| a | b |" 或 "a | b"
        flushList();
        if (!inTable) flushTable();
        inTable = true;
        tableRows.push(
          trimmed
            .replace(/^\|/, '')
            .replace(/\|$/, '')
            .split('|')
            .map((c) => c.trim())
        );
      } else {
        flushList();
        flushTable();
        if (currentSection) sections.push(currentSection);
        currentSection = { type: 'paragraph', text: trimmed, id: Math.random() };
      }
    }

    flushList();
    flushTable();
    if (currentSection) sections.push(currentSection);

    this.setData({ reportSections: sections });
  },

  handleCopy() {
    // 复制时剔除 CHART 标记，只复制可读文本
    const plain = removeChartMarkers(this.data.reportContent);
    wx.setClipboardData({
      data: plain,
      success: () => {
        wx.showToast({ title: '已复制', icon: 'success' });
      },
    });
  },

  handleShare() {
    const content = removeChartMarkers(this.data.reportContent);
    wx.setClipboardData({
      data: content,
      success: () => {
        wx.showModal({
          title: '分享报告',
          content: '报告内容已复制到剪贴板，可粘贴到微信/钉钉分享',
          showCancel: false,
          confirmText: '知道了',
        });
      },
    });
  },

  openFeedback() {
    this.setData({ showFeedback: true });
  },

  closeFeedback() {
    this.setData({ showFeedback: false });
  },

  setRating(e) {
    this.setData({ feedbackRating: e.currentTarget.dataset.rating });
  },

  setFeedbackReason(e) {
    const reason = e.currentTarget.dataset.reason;
    // 再次点击同一项取消选择
    this.setData({ feedbackReason: this.data.feedbackReason === reason ? '' : reason });
  },

  async submitFeedback() {
    if (this.data.feedbackRating === 0) {
      wx.showToast({ title: '请选择评分', icon: 'none' });
      return;
    }

    // 后端要求 rating 枚举：helpful / inaccurate / not_relevant
    // 5 星制映射：5/4 星=有帮助，3 星=不相关（中性），2/1 星=不准确
    const ratingMap = { 1: 'inaccurate', 2: 'inaccurate', 3: 'not_relevant', 4: 'helpful', 5: 'helpful' };
    const rating = ratingMap[this.data.feedbackRating];
    if (!rating) {
      wx.showToast({ title: '请选择评分', icon: 'none' });
      return;
    }

    try {
      await post(config.endpoints.feedback, {
        analysis_history_id: parseInt(this.data.recordId) || 0,
        rating: rating,
        reason: this.data.feedbackReason,
      });
      this.setData({
        showFeedback: false,
        feedbackSubmitted: true,
      });
      wx.showToast({ title: '感谢反馈！', icon: 'success' });
    } catch (e) {
      this.setData({ showFeedback: false });
      wx.showToast({ title: '反馈提交失败', icon: 'none' });
    }
  },
});
