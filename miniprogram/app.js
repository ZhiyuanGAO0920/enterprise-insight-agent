// app.js — 小程序入口
App({
  globalData: {
    token: '',
    userInfo: null,
    baseUrl: '',
    prefillQuestion: '',
  },

  onLaunch() {
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
    }
    const userInfo = wx.getStorageSync('userInfo');
    if (userInfo) {
      this.globalData.userInfo = JSON.parse(userInfo);
    }
  },

  setToken(token) {
    this.globalData.token = token;
    wx.setStorageSync('token', token);
  },

  clearToken() {
    this.globalData.token = '';
    this.globalData.userInfo = null;
    wx.removeStorageSync('token');
    wx.removeStorageSync('userInfo');
  },

  isLoggedIn() {
    return !!this.globalData.token;
  },
});
