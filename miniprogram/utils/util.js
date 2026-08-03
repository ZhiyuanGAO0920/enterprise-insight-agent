// utils/util.js — 通用工具函数
function formatTime(date) {
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = date.getHours();
  const minute = date.getMinutes();
  const second = date.getSeconds();
  return `${[year, month, day].map(formatNumber).join('/')} ${[hour, minute, second].map(formatNumber).join(':')}`;
}

function formatNumber(n) {
  n = n.toString();
  return n[1] ? n : `0${n}`;
}

function formatMoney(val) {
  if (val == null) return '0';
  if (val >= 10000) return (val / 10000).toFixed(1) + '万';
  return Number(val).toLocaleString('zh-CN');
}

function formatPercent(val) {
  if (val == null) return '0%';
  return (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
}

function debounce(fn, delay = 300) {
  let timer = null;
  return function (...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      fn.apply(this, args);
    }, delay);
  };
}

function throttle(fn, delay = 300) {
  let lastTime = 0;
  return function (...args) {
    const now = Date.now();
    if (now - lastTime >= delay) {
      fn.apply(this, args);
      lastTime = now;
    }
  };
}

function safeGet(obj, path, defaultVal) {
  const keys = path.split('.');
  let current = obj;
  for (const key of keys) {
    if (current == null) return defaultVal;
    current = current[key];
  }
  return current == null ? defaultVal : current;
}

module.exports = {
  formatTime,
  formatNumber,
  formatMoney,
  formatPercent,
  debounce,
  throttle,
  safeGet,
};
