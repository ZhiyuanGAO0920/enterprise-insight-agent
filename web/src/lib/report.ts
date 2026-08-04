/* ══════════════════════════════════════════════════════════
   报告解析管线（Analysis 与 Share 共用）
   convertTextTables → extractCharts → marked → DOMPurify
   ══════════════════════════════════════════════════════════ */
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { THEME_COLORS } from '../theme';

export interface ChartSpec {
  type: string;
  height: number;
  xData?: string[];
  series?: { name: string; data: number[] }[];
  note?: string;
  [k: string]: unknown;
}

/* 报告数据溯源条目（data_sources / SSE done 事件） */
export interface DataSource {
  agent?: string;
  id?: number;
  claim?: string;
  execution_time_ms?: number;
  row_count?: number;
  sql?: string;
}

/* 分析规划（supervisor_plan，LLM 输出 JSON） */
export interface SupervisorPlanData {
  activated_agents?: string[];
  reasoning?: string;
  analysis_plan?: string;
}

/* 去掉 [FOLLOWUP...] 标签（提问放报告尾部由追问按钮承载） */
export function stripFollowupTags(text: string): string {
  return text.replace(/\[FOLLOWUP[^\]]*\]\]/g, '');
}

/* LLM 偶尔生成的 tab 分隔文本表格 → markdown 管道符表格 */
export function convertTextTables(text: string): string {
  const lines = text.split('\n');
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const tabCount = (line.match(/\t/g) || []).length;
    if (tabCount >= 2) {
      const rows: string[][] = [];
      while (i < lines.length && (lines[i].match(/\t/g) || []).length >= 2) {
        rows.push(lines[i].split('\t'));
        i++;
      }
      if (rows.length >= 2) {
        const colCount = rows.reduce((m, r) => Math.max(m, r.length), 0);
        const sep = '|' + new Array(colCount).fill(':---:').join('|') + '|';
        out.push('|' + rows[0].join('|') + '|');
        out.push(sep);
        for (let ri = 1; ri < rows.length; ri++) out.push('|' + rows[ri].join('|') + '|');
        continue;
      }
    }
    out.push(line);
    i++;
  }
  return out.join('\n');
}

/* 提取 [CHART:type|urlencoded_json] 标签，返回纯文本 + 图表配置（括号计数法） */
export function extractCharts(text: string): { text: string; charts: ChartSpec[] } {
  const charts: ChartSpec[] = [];
  let out = '';
  let i = 0;
  while (i < text.length) {
    const pos = text.indexOf('[CHART:', i);
    if (pos === -1) { out += text.slice(i); break; }
    out += text.slice(i, pos);
    let depth = 0, end = -1;
    for (let j = pos; j < text.length; j++) {
      if (text[j] === '[') depth++;
      else if (text[j] === ']') { depth--; if (depth === 0) { end = j; break; } }
    }
    if (end === -1 || end > pos + 5000) { out += text.slice(pos); break; }
    const marker = text.slice(pos, end + 1);
    const bar = marker.indexOf('|');
    if (bar === -1 || bar > 100) { out += marker; i = end + 1; continue; }
    try {
      const encoded = marker.slice(bar + 1, -1);
      const params = JSON.parse(decodeURIComponent(encoded));
      /* 对齐原生版 utils.js：后端契约字段为 x_data（下划线），统一转为 xData（驼峰）。
         不转换会导致 config.xData 为 undefined → pie 的 data 映射空数组，
         ECharts 渲染灰色无数据占位环（圆环空白）。 */
      charts.push({ type: params.type || 'bar', height: params.height || 400, ...params, xData: params.xData ?? params.x_data ?? [] });
    } catch { /* 解析失败的标签丢弃 */ }
    i = end + 1;
  }
  return { text: out, charts };
}

/* 对齐原生版 buildEChartsOption */
export function buildEChartsOption(type: string, config: ChartSpec): Record<string, unknown> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- ECharts option 为动态结构，迁移官方 EChartsOption 类型需整体改造
  const opt: any = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: type === 'pie' ? 'item' : 'axis',
      backgroundColor: 'rgba(30,41,59,0.95)',
      borderColor: '#334155',
      textStyle: { color: '#f1f5f9', fontSize: 12 },
    },
    grid: { left: 50, right: 20, bottom: 30, top: 10, containLabel: true },
    xAxis: {
      type: 'category', data: config.xData,
      axisLabel: { color: '#94a3b8', fontSize: 10, rotate: (config.xData?.length ?? 0) > 8 ? 35 : 0 },
      axisLine: { lineStyle: { color: '#334155' } }, axisTick: { show: false }, splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(1)}万` : v },
      splitLine: { lineStyle: { color: 'rgba(51,65,85,0.5)' } },
    },
  };
  const series = config.series || [];
  if (type === 'bar') {
    opt.series = series.map((s, i) => ({ name: s.name, type: 'bar', data: s.data, itemStyle: { color: THEME_COLORS[i % THEME_COLORS.length] }, barMaxWidth: 40 }));
  } else if (type === 'line') {
    opt.xAxis.axisLabel.rotate = 0;
    opt.series = series.map((s, i) => ({ name: s.name, type: 'line', data: s.data, smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2 }, itemStyle: { color: THEME_COLORS[i % THEME_COLORS.length] } }));
  } else if (type === 'pie') {
    delete opt.xAxis; delete opt.yAxis; delete opt.grid;
    opt.series = [{ type: 'pie', radius: ['30%', '55%'], center: ['50%', '50%'],
      data: (config.xData || []).map((name, i) => ({ name, value: series[0]?.data?.[i] ?? 1 })),
      label: { color: '#f1f5f9', fontSize: 11 }, itemStyle: { borderColor: 'transparent', borderWidth: 2 }, color: THEME_COLORS }];
  }
  if (config.note) opt.graphic = { type: 'text', left: 'center', bottom: 0, style: { text: config.note, fill: '#94a3b8', fontSize: 10 } };
  return opt;
}

/* marked + DOMPurify：唯一的 HTML 注入点，内容已净化 */
export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: true }) as string);
}

export function processReport(raw: string): { html: string; charts: ChartSpec[] } {
  const cleaned = stripFollowupTags(raw);
  const { text, charts } = extractCharts(cleaned);
  return { html: renderMarkdown(convertTextTables(text)), charts };
}
