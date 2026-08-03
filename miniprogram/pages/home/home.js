// pages/home/home.js
const config = require('../../utils/config.js');
const { get } = require('../../utils/request.js');

Page({
  data: {
    loading: true,
    viewType: 'summary',
    greeting: '',
    username: '',
    currentDate: '',
    todaySales: 0,
    yesterdaySales: 0,
    salesChange: 0,
    salesChangeDir: 'up',
    ordersToday: 0,
    membersTotal: 0,
    activeStores: 0,
    refundRate: 0,
    trendDates: [],
    trendValues: [],
    trendMax: 1,
    peakLabel: '', // 趋势峰值日（MM-DD）
    peakValue: 0, // 趋势峰值金额
    topStores: [],
    topStoreValues: [],
    regions: [],
    regionValues: [],
    topRefundStores: [],
    topRefundValues: [],
    alertItems: [],
    updatedAt: '', // 数据更新时间（HH:MM）
    regionCount: 0, // 看板：覆盖区域数
    alertStoreCount: 0, // 看板：退款率>5% 的预警门店数
  },

  onLoad() {
    this._setDate();
    this.loadData();
  },

  onShow() {
    if (!this.data.loading) {
      this.loadData();
    }
  },

  onPullDownRefresh() {
    this.loadData().then(() => wx.stopPullDownRefresh());
  },

  switchView(e) {
    const view = e.currentTarget.dataset.view;
    this.setData({ viewType: view });
    if (view === 'overview' && !this.data.regions.length) {
      this.loadOverview();
    }
  },

  async loadData() {
    this.setData({ loading: true });
    try {
      const data = await get(config.endpoints.todaySummary);
      // 趋势只取最近 7 天，柱高相对最大值归一（避免某天暴涨时其他柱变细线）
      const trend = this._buildTrend(data.trend_dates, data.trend_values);
      this.setData({
        loading: false,
        greeting: data.greeting || '',
        username: data.username || '',
        todaySales: data.today_sales || 0,
        yesterdaySales: data.yesterday_sales || 0,
        salesChange: this._calcChange(data.today_sales, data.yesterday_sales),
        salesChangeDir: data.today_sales >= data.yesterday_sales ? 'up' : 'down',
        activeStores: data.active_stores || 0,
        membersTotal: data.total_members || 0,
        trendDates: trend.dates,
        trendValues: trend.values,
        trendMax: trend.max,
        peakLabel: trend.peakLabel,
        peakValue: trend.peakValue,
        topStores: data.top_stores || [],
        topStoreValues: data.top_store_values || [],
        alertItems: this._buildAlerts(data.top_refund_stores, data.top_refund_values),
        updatedAt: this._formatTime(new Date()),
      });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败，下拉刷新重试', icon: 'none' });
    }
  },

  async loadOverview() {
    try {
      const data = await get(config.endpoints.overview);
      // 看板预警门店数：退款率 > 5% 的门店（与快报预警卡同一阈值）
      const refundVals = data.top_refund_values || [];
      const alertStoreCount = (data.top_refund_stores || []).filter((_, i) => (refundVals[i] || 0) > 5).length;
      this.setData({
        regions: data.regions || [],
        regionValues: data.region_values || [],
        topRefundStores: data.top_refund_stores || [],
        topRefundValues: data.top_refund_values || [],
        todaySales: data.today_sales || 0,
        yesterdaySales: data.yesterday_sales || 0,
        salesChange: this._calcChange(data.today_sales, data.yesterday_sales),
        salesChangeDir: data.today_sales >= data.yesterday_sales ? 'up' : 'down',
        activeStores: data.active_stores || 0,
        membersTotal: data.total_members || 0,
        refundRate: data.week_refund_rate || 0,
        regionCount: (data.regions || []).length,
        alertStoreCount: alertStoreCount,
        updatedAt: this._formatTime(new Date()),
      });
    } catch (err) {
      wx.showToast({ title: '加载看板失败', icon: 'none' });
    }
  },

  _setDate() {
    const d = new Date();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
    this.setData({ currentDate: `${month}-${day} ${week}` });
  },

  _calcChange(today, yesterday) {
    if (!yesterday) return 0;
    return Math.round(((today - yesterday) / yesterday) * 100);
  },

  // 趋势数据：截取最近 7 天 + 计算最大值（供柱状图归一化）+ 标记峰值日
  _buildTrend(dates, values) {
    const d = (dates || []).slice(-7).map((x) => {
      const s = String(x);
      return s.length > 5 ? s.slice(5) : s; // "2026-07-25" → "07-25"
    });
    const v = (values || []).slice(-7);
    const max = v.reduce((m, x) => Math.max(m, x || 0), 0);
    const peakIndex = v.indexOf(max > 0 ? max : -1);
    return {
      dates: d,
      values: v,
      max: max > 0 ? max : 1,
      peakLabel: peakIndex >= 0 ? d[peakIndex] : '',
      peakValue: peakIndex >= 0 ? v[peakIndex] : 0,
    };
  },

  _buildAlerts(stores, values) {
    if (!stores || stores.length === 0) return [];
    const alerts = [];
    for (let i = 0; i < Math.min(stores.length, 3); i++) {
      if (values[i] > 5) {
        alerts.push({
          id: i,
          title: `${stores[i]} · 退款率 ${values[i]}%`,
          level: values[i] > 10 ? 'high' : 'medium',
          query: `分析${stores[i]}退款率过高的原因`,
        });
      }
    }
    return alerts;
  },

  _formatTime(date) {
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  },

  goChat(e) {
    const query = e.currentTarget.dataset.query;
    // switchTab 的 success 回调时序晚于 chat 页 onShow，用 globalData 传递
    const app = getApp();
    app.globalData.prefillQuestion = query || '';
    wx.switchTab({
      url: '/pages/chat/chat',
    });
  },

  formatMoney(val) {
    if (val >= 10000) return (val / 10000).toFixed(1) + '万';
    return val.toLocaleString();
  },

  onShareAppMessage() {
    return {
      title: '企业经营助手 — AI 驱动的连锁零售分析',
      path: '/pages/home/home',
    };
  },
});
