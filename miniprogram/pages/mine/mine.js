// pages/mine/mine.js
const config = require('../../utils/config.js');
const { get, post } = require('../../utils/request.js');

Page({
  data: {
    userInfo: null,
    statReports: 0,
    menuItems: [
      { id: 'history', icon: '📋', title: '历史报告', desc: '查看过往分析记录' },
      { id: 'feedback', icon: '💭', title: '意见反馈', desc: '帮助我们变得更好' },
      { id: 'about', icon: 'ℹ️', title: '关于应用', desc: 'V1.0 Demo' },
    ],
  },

  onLoad() {
    const userInfo = wx.getStorageSync('userInfo');
    if (userInfo) {
      this.setData({ userInfo: JSON.parse(userInfo) });
    }
    this.loadStat();
  },

  onShow() {
    const userInfo = wx.getStorageSync('userInfo');
    if (userInfo) {
      this.setData({ userInfo: JSON.parse(userInfo) });
    }
    this.loadStat();
  },

  // 分析报告数接入后端真实数据（/analysis/history total）
  async loadStat() {
    try {
      const resp = await get(config.endpoints.history, { page: 1, page_size: 1 });
      this.setData({ statReports: resp.total || 0 });
    } catch (e) {
      // 统计失败静默，不阻塞页面
    }
  },

  handleMenu(e) {
    const id = e.currentTarget.dataset.id;
    switch (id) {
      case 'history':
        // 跳转 AI 助手页并自动展开历史抽屉
        getApp().globalData.openHistoryDrawer = true;
        wx.switchTab({ url: '/pages/chat/chat' });
        break;
      case 'feedback':
        this._submitFeedback();
        break;
      case 'about':
        this._showAbout();
        break;
      default:
        wx.showToast({ title: '功能开发中', icon: 'none' });
    }
  },

  async _submitFeedback() {
    wx.showModal({
      title: '意见反馈',
      editable: true,
      placeholderText: '请输入您的反馈内容...',
      success: async (res) => {
        if (res.confirm && res.content) {
          try {
            await post(config.endpoints.contactFeedback, {
              content: res.content,
            });
            wx.showToast({ title: '感谢反馈！', icon: 'success' });
          } catch (e) {
            wx.showToast({ title: '反馈提交失败', icon: 'none' });
          }
        }
      },
    });
  },

  _showAbout() {
    wx.showModal({
      title: '关于',
      content: '企业经营助手 V1.0\n\nAI 驱动的连锁零售经营分析平台\n\nDemo 版本，数据仅供演示',
      showCancel: false,
    });
  },

  handleLogout() {
    wx.showModal({
      title: '确认退出',
      content: '确定要退出登录吗？',
      success: (res) => {
        if (res.confirm) {
          const app = getApp();
          app.clearToken();
          wx.reLaunch({ url: '/pages/login/login' });
        }
      },
    });
  },
});
