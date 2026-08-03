// pages/login/login.js
const config = require('../../utils/config.js');

Page({
  data: {
    loading: false,
    errorMsg: '',
  },

  onLoad() {
    const token = wx.getStorageSync('token');
    if (token) {
      wx.switchTab({ url: '/pages/home/home' });
    }
  },

  async handleWechatLogin() {
    if (this.data.loading) return;
    this.setData({ loading: true, errorMsg: '' });

    try {
      // wx.login 传回调时不返回 Promise，必须手动包装
      const loginRes = await new Promise((resolve, reject) => {
        wx.login({ success: resolve, fail: reject });
      });
      const code = loginRes.code;

      const resp = await new Promise((resolve, reject) => {
        wx.request({
          url: config.baseUrl + config.endpoints.wechatLogin,
          method: 'POST',
          data: { code },
          header: { 'Content-Type': 'application/json' },
          success: (r) => {
            // 后端约定：未绑定返回 200 + need_bind=true（4021 不是合法 HTTP 状态码，
            // uvicorn/h11 会断开连接导致"空响应"，真机上表现为登录失败）
            if (r.statusCode === 200 && r.data && r.data.need_bind) {
              reject({ code: 4021 });
            } else if (r.statusCode === 200) {
              resolve(r.data);
            } else if (r.statusCode === 4021) {
              // 兼容旧后端
              reject({ code: 4021 });
            } else {
              reject(r);
            }
          },
          fail: reject,
        });
      });

      if (resp.access_token) {
        wx.setStorageSync('token', resp.access_token);
        wx.setStorageSync('userInfo', JSON.stringify({
          user_id: resp.user_id,
          username: resp.username,
        }));

        wx.showToast({ title: '登录成功', icon: 'success' });
        setTimeout(() => {
          wx.switchTab({ url: '/pages/home/home' });
        }, 500);
      }
    } catch (err) {
      if (err.code === 4021) {
        wx.navigateTo({ url: '/pages/bind/bind' });
      } else {
        this.setData({
          errorMsg: '登录失败，请重试',
          loading: false,
        });
        wx.showToast({ title: '登录失败', icon: 'none' });
      }
    }
  },

  goBind() {
    wx.navigateTo({ url: '/pages/bind/bind' });
  },

  showAgreement() {
    wx.showModal({
      title: '用户协议与隐私政策',
      content: '1. 登录后仅可查看您被授权的门店经营数据；\n2. 您的分析记录仅用于改进 AI 分析质量；\n3. 分享报告前请注意脱敏，链接有效期为 30 天。',
      showCancel: false,
      confirmText: '我知道了',
    });
  },
});
