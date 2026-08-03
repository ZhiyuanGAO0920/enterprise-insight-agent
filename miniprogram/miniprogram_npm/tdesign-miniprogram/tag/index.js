// 标签组件
Component({
  properties: {
    theme: {
      type: String,
      value: 'default',
    },
    variant: {
      type: String,
      value: 'dark',
    },
    size: {
      type: String,
      value: 'medium',
    },
  },
  data: {
    classPrefix: 't-tag',
  },
});
