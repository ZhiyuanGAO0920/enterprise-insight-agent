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
 * @param {Object} [options.taskRef] - 调用方传入的空对象 {}，wx.request 的 RequestTask 会回填到
 *                                     taskRef.task，供调用方主动 abort（如"停止生成"）
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

    const task = wx.request({
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
        const errMsg = (err && err.errMsg) || '';
        if (errMsg.indexOf('abort') >= 0) {
          // 主动取消（用户点"停止"）：静默失败，不弹"网络连接失败"
          console.warn(`[req] 已取消 ← ${label}`);
          reject({ code: 'aborted', message: '请求已取消' });
          return;
        }
        console.warn(`[req] 失败 ← ${label}`, errMsg);
        wx.showToast({
          title: '网络连接失败',
          icon: 'none',
        });
        reject(err);
      },
    });
    if (options.taskRef) options.taskRef.task = task; // 暴露 RequestTask 供 abort
  });
}

function get(url, data, auth) {
  return request({ url, method: 'GET', data, auth });
}

function post(url, data, auth, timeoutMs, taskRef) {
  return request({ url, method: 'POST', data, auth, timeoutMs, taskRef });
}

module.exports = { request, get, post };
