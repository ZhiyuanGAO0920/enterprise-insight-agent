// 轻量图标组件
// 使用 emoji 作为占位图标，后续可替换为 TDesign 图标字体
Component({
  properties: {
    name: {
      type: String,
      value: '',
    },
    size: {
      type: String,
      value: '32rpx',
    },
    color: {
      type: String,
      value: '#1D1D1F',
    },
  },

  data: {
    iconMap: {
      home: '🏠',
      chat: '💬',
      user: '👤',
      search: '🔍',
      arrow: '→',
      back: '←',
      close: '✕',
      check: '✓',
      warning: '⚠️',
      info: 'ℹ️',
      star: '⭐',
      chart: '📊',
      money: '💰',
      box: '📦',
      link: '🔗',
      report: '📋',
      share: '📤',
      copy: '📋',
      stop: '⏹',
      play: '▶',
      refresh: '🔄',
      bell: '🔔',
      calendar: '📅',
      trend: '📈',
      down: '📉',
      location: '📍',
      time: '⏰',
      settings: '⚙️',
      logout: '🚪',
      feedback: '💭',
      about: 'ℹ️',
      history: '🕐',
      favorite: '⭐',
    },
  },

  lifetimes: {
    attached() {
      this.setData({
        displayIcon: this.data.iconMap[this.data.name] || '📄',
      });
    },
  },
});
