// utils/request.js — 网络请求拦截器
const app = getApp();
const config = require('./config.js');

/**
 * 通用请求封装
 * @param {Object} options
 * @param {string} options.url - 请求路径（相对 baseUrl）
 * @param {string} [options.method='GET'] - 请求方法
 * @param {Object} [options.data] - 请求数据
 * @param {boolean} [options.auth=true] - 是否需要鉴权
 * @param {Object} [options.header] - 额外请求头
 */
function request(options) {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('token');
    const header = {
      'Content-Type': 'application/json',
      ...(options.header || {}),
    };

    if (options.auth !== false && token) {
      header['Authorization'] = `Bearer ${token}`;
    }

    const label = `${options.method || 'GET'} ${options.url}`;
    console.log(`[req] 发送 → ${label}`);

    wx.request({
      url: config.baseUrl + options.url,
      method: options.method || 'GET',
      data: options.data,
      header,
      timeout: options.timeoutMs || 420000, // 默认后端同步分析上限 420s；可单独覆盖（如会话创建 5s）
      success(res) {
        console.log(`[req] 收到 ← ${label} → ${res.statusCode}`);
        if (res.statusCode === 401) {
          wx.removeStorageSync('token');
          wx.removeStorageSync('userInfo');
          wx.reLaunch({ url: '/pages/login/login' });
          reject({ code: 401, message: '登录已过期' });
          return;
        }

        if (res.statusCode === 4021) {
          wx.navigateTo({ url: '/pages/bind/bind' });
          reject({ code: 4021, message: '需要绑定账号' });
          return;
        }

        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          wx.showToast({
            title: (res.data && res.data.detail) || '请求失败',
            icon: 'none',
          });
          reject({ code: res.statusCode, message: (res.data && res.data.detail) || '请求失败' });
        }
      },
      fail(err) {
        console.warn(`[req] 失败 ← ${label}`, err && err.errMsg);
        wx.showToast({
          title: '网络连接失败',
          icon: 'none',
        });
        reject(err);
      },
    });
  });
}

function get(url, data, auth) {
  return request({ url, method: 'GET', data, auth });
}

function post(url, data, auth, timeoutMs) {
  return request({ url, method: 'POST', data, auth, timeoutMs });
}

module.exports = { request, get, post };
