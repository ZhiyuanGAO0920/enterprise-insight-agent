// components/chart-render/chart-render.js
// 轻量图表渲染组件：解析后端简化图表配置（{type, title, x_data, series, height, note}），
// canvas 2d 自绘 bar / line / pie。不引入 ECharts —— 小程序包体积与真机性能考虑。
// 数据格式见 app/agents/chart_advisor_agent.py 的 CHART_ADVISOR_SYSTEM_PROMPT。

const COLORS = ['#1A73E8', '#30D158', '#FF9500', '#FF3B30', '#8B5CF6', '#06B6D4', '#84CC16', '#EC4899'];

Component({
  properties: {
    option: { type: Object, value: null },
  },

  data: {
    heightPx: 300,
  },

  lifetimes: {
    ready() {
      this._ctx = null;
      this._canvas = null;
      this._dpr = 1;
      this._initCanvas();
    },
  },

  observers: {
    option(opt) {
      if (!opt) return;
      this.setData({ heightPx: this._clampHeight(opt.height) });
      // ready 之前（属性先于 ready 赋值）仅存数据，ready 后统一绘制
      if (this._ctx) this._draw(opt);
    },
  },

  methods: {
    _clampHeight(h) {
      const n = parseInt(h, 10);
      if (!n || n < 200) return 300;
      return Math.min(n, 500);
    },

    _initCanvas() {
      this.createSelectorQuery()
        .select('#chartCanvas')
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res || !res[0] || !res[0].node) return;
          const { node, width } = res[0];
          const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
          this._dpr = info.pixelRatio || 2;
          this._canvas = node;
          node.width = width * this._dpr;
          node.height = this.data.heightPx * this._dpr;
          const ctx = node.getContext('2d');
          ctx.scale(this._dpr, this._dpr);
          ctx.textBaseline = 'middle';
          this._ctx = ctx;
          if (this.data.option) this._draw(this.data.option);
        });
    },

    _draw(opt) {
      const ctx = this._ctx;
      if (!ctx) return;
      const width = this._canvas.width / this._dpr;
      const height = this.data.heightPx;
      ctx.clearRect(0, 0, width, height);
      const type = opt.type || 'bar';
      if (type === 'line') this._drawLine(ctx, opt, width, height);
      else if (type === 'pie') this._drawPie(ctx, opt, width, height);
      else this._drawBar(ctx, opt, width, height); // bar 兜底（scatter/radar 等罕见类型）
    },

    // ── 通用 ──
    _fmt(v) {
      const n = Number(v) || 0;
      if (n >= 10000) return (n / 10000).toFixed(1) + '万';
      if (Math.abs(n) >= 100) return String(Math.round(n));
      return String(Math.round(n * 10) / 10);
    },

    _truncate(text, maxPx) {
      const s = String(text || '');
      if (this._ctx.measureText(s).width <= maxPx) return s;
      let out = s;
      while (out.length > 1 && this._ctx.measureText(out + '…').width > maxPx) {
        out = out.slice(0, -1);
      }
      return out + '…';
    },

    _gridLines(ctx, padL, padR, padT, plotW, plotH, max) {
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.06)';
      ctx.fillStyle = '#8E8E93';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'right';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const v = (max / 4) * i;
        const y = padT + plotH - plotH * (v / max);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(padL + plotW, y);
        ctx.stroke();
        ctx.fillText(this._fmt(v), padL - 6, y);
      }
    },

    _title(ctx, opt, padL, padT) {
      if (!opt.title) return;
      ctx.fillStyle = '#1D1D1F';
      ctx.font = 'bold 13px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(opt.title, padL, padT - 8);
    },

    // ── 柱状图 ──
    _drawBar(ctx, opt, w, h) {
      const xData = opt.x_data || [];
      const series = (opt.series && opt.series[0]) || {};
      const data = (series.data || []).map(Number);
      if (data.length === 0) return;
      const padL = 48;
      const padR = 16;
      const padT = 30;
      const padB = 36;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;
      const max = Math.max.apply(null, data.concat([0])) * 1.15 || 1;
      this._gridLines(ctx, padL, padR, padT, plotW, plotH, max);
      this._title(ctx, opt, padL, padT);
      const n = data.length;
      const gap = 8;
      const bw = Math.min((plotW - gap * (n - 1)) / n, 40);
      const step = n > 1 ? (plotW - bw) / (n - 1) : 0;
      for (let i = 0; i < n; i++) {
        const x = padL + (n > 1 ? i * step : 0);
        const v = data[i] || 0;
        const bh = plotH * (v / max);
        ctx.fillStyle = COLORS[i % COLORS.length];
        ctx.fillRect(x, padT + plotH - bh, bw, Math.max(bh, 2));
        // 数值标签（柱顶）
        ctx.fillStyle = '#3C3C43';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(this._fmt(v), x + bw / 2, padT + plotH - bh - 8);
        // X 轴标签（过密时间隔显示）
        ctx.fillStyle = '#8E8E93';
        const showLabel = n > 12 ? i % 2 === 0 : true;
        if (showLabel) {
          ctx.fillText(this._truncate(xData[i], bw + 4), x + bw / 2, h - padB + 16);
        }
      }
    },

    // ── 折线图 ──
    _drawLine(ctx, opt, w, h) {
      const xData = opt.x_data || [];
      const seriesList = opt.series || [];
      if (seriesList.length === 0) return;
      const padL = 48;
      const padR = 16;
      const padT = 30;
      const padB = 36;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;
      const allVals = [];
      seriesList.forEach((s) => (s.data || []).forEach((d) => allVals.push(Number(d))));
      const max = Math.max.apply(null, allVals.concat([0])) * 1.15 || 1;
      const n = Math.max.apply(null, seriesList.map((s) => (s.data || []).length).concat([0]));
      if (n === 0) return;
      this._gridLines(ctx, padL, padR, padT, plotW, plotH, max);
      this._title(ctx, opt, padL, padT);
      // 图例（多 series）
      if (seriesList.length > 1) {
        let lx = padL;
        seriesList.forEach((s, si) => {
          ctx.fillStyle = COLORS[si % COLORS.length];
          ctx.fillRect(lx, padT - 16, 10, 10);
          ctx.fillStyle = '#8E8E93';
          ctx.font = '10px sans-serif';
          ctx.textAlign = 'left';
          ctx.fillText(s.name || '', lx + 14, padT - 11);
          lx += 14 + ctx.measureText(s.name || '').width + 18;
        });
      }
      seriesList.forEach((s, si) => {
        const data = (s.data || []).map(Number);
        const color = COLORS[si % COLORS.length];
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        data.forEach((v, i) => {
          const x = n > 1 ? padL + plotW * (i / (n - 1)) : padL;
          const y = padT + plotH - plotH * (v / max);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        // 数据点 + 数值
        ctx.font = '10px sans-serif';
        ctx.fillStyle = '#3C3C43';
        data.forEach((v, i) => {
          const x = n > 1 ? padL + plotW * (i / (n - 1)) : padL;
          const y = padT + plotH - plotH * (v / max);
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          ctx.fillStyle = '#3C3C43';
          ctx.textAlign = 'center';
          if (n <= 12) ctx.fillText(this._fmt(v), x, y - 10);
        });
      });
      // X 轴标签
      ctx.fillStyle = '#8E8E93';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      xData.forEach((label, i) => {
        const x = n > 1 ? padL + plotW * (i / (n - 1)) : padL;
        if (n > 12 && i % 2 !== 0) return;
        ctx.fillText(this._truncate(label, 48), x, h - padB + 16);
      });
    },

    // ── 饼图 ──
    _drawPie(ctx, opt, w, h) {
      const series = (opt.series && opt.series[0]) || {};
      const xData = opt.x_data || [];
      const items = (series.data || []).map((d, i) => {
        if (d && typeof d === 'object') {
          return { name: d.name || xData[i] || '', value: Number(d.value) || 0 };
        }
        return { name: xData[i] || '', value: Number(d) || 0 };
      });
      const total = items.reduce((s, d) => s + d.value, 0);
      if (total <= 0) return;
      this._title(ctx, opt, 24, 24);
      const cx = w / 2 - 44;
      const cy = h / 2;
      const r = Math.min(w / 2 - 70, h / 2 - 20, 84);
      let angle = -Math.PI / 2;
      items.forEach((d, i) => {
        const a = (d.value / total) * Math.PI * 2;
        ctx.fillStyle = COLORS[i % COLORS.length];
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, r, angle, angle + a);
        ctx.closePath();
        ctx.fill();
        angle += a;
      });
      // 中心显示总数
      ctx.fillStyle = '#1D1D1F';
      ctx.font = 'bold 16px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(this._fmt(total), cx, cy - 4);
      ctx.fillStyle = '#8E8E93';
      ctx.font = '10px sans-serif';
      ctx.fillText('合计', cx, cy + 14);
      // 右侧图例（名称 + 百分比）
      let ly = Math.max(40, cy - r);
      ctx.font = '11px sans-serif';
      items.forEach((d, i) => {
        ctx.fillStyle = COLORS[i % COLORS.length];
        ctx.fillRect(cx + r + 20, ly - 6, 12, 12);
        ctx.fillStyle = '#3C3C43';
        ctx.textAlign = 'left';
        const pct = Math.round((d.value / total) * 100);
        ctx.fillText(this._truncate(d.name, 70) + ' ' + pct + '%', cx + r + 40, ly);
        ly += 24;
      });
    },
  },
});
