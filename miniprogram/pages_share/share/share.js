// pages_share/share/share.js
const config = require('../../utils/config.js');
const { cleanReport } = require('../../utils/report.js');

Page({
  data: {
    loading: true,
    error: null,
    shareToken: '',
    shareData: null,
    isExpired: false,
    conclusion: '',
    generatedAt: '',
    reflectionPassed: null,
    shareQuestion: '',
    isLoggedIn: false,
    expanded: false,
  },

  toggleExpand() {
    this.setData({ expanded: !this.data.expanded });
  },

  onLoad(options) {
    const token = options.token || '';
    this.setData({
      shareToken: token,
      isLoggedIn: !!wx.getStorageSync('token'),
    });
    this.loadShare(token);
  },

  async loadShare(token) {
    this.setData({ loading: true, error: null });

    try {
      const resp = await new Promise((resolve, reject) => {
        wx.request({
          url: config.baseUrl + config.endpoints.share + '/' + token,
          method: 'GET',
          header: {
            'Authorization': `Bearer ${wx.getStorageSync('token')}`,
          },
          success: (r) => {
            if (r.statusCode === 200) resolve(r.data);
            else if (r.statusCode === 404 || r.statusCode === 410) {
              this.setData({ isExpired: true });
              reject({ expired: true });
            } else reject(r);
          },
          fail: reject,
        });
      });

      this.setData({
        loading: false,
        shareData: resp,
        // 后端 /share/{token} 只返回 {id, question, report, reflection_passed, create_time}
        // 没有 conclusion/key_findings/recommendations 字段，直接用 report（清洗 markdown 噪声）
        conclusion: cleanReport(resp.report || ''),
        generatedAt: resp.create_time ? this._formatDate(resp.create_time) : '',
        reflectionPassed: resp.reflection_passed,
        shareQuestion: resp.question || '',
      });
    } catch (err) {
      this.setData({ loading: false, error: true });
    }
  },

  goLogin() {
    wx.navigateTo({ url: '/pages/login/login' });
  },

  goChat() {
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  _formatDate(isoDate) {
    try {
      const d = new Date(isoDate);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    } catch (e) {
      return '';
    }
  },
});
