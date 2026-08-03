// pages/bind/bind.js
const config = require('../../utils/config.js');

Page({
  data: {
    username: '',
    password: '',
    loading: false,
    errorMsg: '',
  },

  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value, errorMsg: '' });
  },

  async handleBind() {
    const { username, password } = this.data;
    if (!username || !password) {
      this.setData({ errorMsg: '请填写账号和密码' });
      return;
    }

    this.setData({ loading: true, errorMsg: '' });

    try {
      // 获取微信 code
      const loginRes = await new Promise((resolve, reject) => {
        wx.login({
          success: resolve,
          fail: reject
        });
      });
      const code = loginRes.code;
      console.log('[bind] wx.login code:', code);

      const url = config.baseUrl + config.endpoints.wechatBind;
      console.log('[bind] 请求 URL:', url);

      const resp = await new Promise((resolve, reject) => {
        wx.request({
          url: url,
          method: 'POST',
          data: { code, username, password },
          header: { 'Content-Type': 'application/json' },
          success: (r) => {
            console.log('[bind] 响应:', r.statusCode, r.data);
            if (r.statusCode === 200) resolve(r.data);
            else reject(r);
          },
          fail: (err) => {
            console.error('[bind] 请求失败:', err);
            reject(err);
          },
        });
      });

      if (resp.access_token) {
        wx.setStorageSync('token', resp.access_token);
        wx.setStorageSync('userInfo', JSON.stringify({
          user_id: resp.user_id,
          username: resp.username,
        }));

        wx.showToast({ title: '绑定成功', icon: 'success' });
        setTimeout(() => {
          wx.switchTab({ url: '/pages/home/home' });
        }, 500);
      }
    } catch (err) {
      const msg = (err.data && err.data.detail) || '绑定失败，请检查账号密码';
      this.setData({ errorMsg: msg, loading: false });
    }
  },
});
