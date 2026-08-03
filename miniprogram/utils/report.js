// utils/report.js — 报告文本轻量清洗（markdown → 可读纯文本）
// V1.0 未引入 towxml 渲染器：报告以纯文本展示，这里做最小清洗：
// 去掉 FOLLOWUP 标记、标题井号、加粗/反引号、表格管道符等 markdown 噪声。
// 追问建议 chips 由后端 done 事件/同步响应的 followup_questions 字段提供，
// 报告正文里的 [FOLLOWUP:[...]] 标记必须剔除。

/**
 * 去掉 [FOLLOWUP:[...]] 标记（后端报告末尾追加的追问建议）
 */
function stripFollowup(text) {
  if (!text) return '';
  return String(text).replace(/\[FOLLOWUP[^\]]*\]\]/g, '').trim();
}

/**
 * 内联语法清洗：**加粗** / `代码` / [文字](链接) → 纯文字
 */
function inline(text) {
  return String(text)
    .replace(/\*\*([^*]+)\*\*/g, '$1') // **bold** → bold
    .replace(/`([^`]+)`/g, '$1') // `code` → code
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1'); // [text](url) → text
}

/**
 * 从报告文本中解析 [CHART:type|url_encoded_json] 图表标记（Web 端同款格式，见
 * app/api/static/utils.js expandChartTags）。返回图表配置数组：
 * [{type, title, x_data, series, height, note}]，解析失败/无标记返回 []。
 * 括号计数法匹配 ]（兼容 JSON 中嵌套的 []）。
 */
function parseCharts(text) {
  if (!text) return [];
  const result = [];
  let i = 0;
  while (i < text.length) {
    const pos = text.indexOf('[CHART:', i);
    if (pos === -1) break;
    // 括号计数找匹配的 ]
    let depth = 0;
    let end = -1;
    for (let j = pos; j < text.length; j++) {
      if (text[j] === '[') depth++;
      else if (text[j] === ']') {
        depth--;
        if (depth === 0) { end = j; break; }
      }
    }
    if (end === -1 || end > pos + 5000) break;
    const marker = text.slice(pos, end + 1);
    const bar = marker.indexOf('|');
    if (bar !== -1 && bar <= 100) {
      try {
        const params = JSON.parse(decodeURIComponent(marker.slice(bar + 1, -1)));
        if (params && params.type) result.push(params);
      } catch (e) { /* 非法标记跳过 */ }
    }
    i = end + 1;
  }
  return result;
}

/**
 * 剔除报告文本中的 [CHART:...] 标记（纯文本预览/复制场景不需要）。
 * 与 parseCharts 同一套括号计数逻辑。
 */
function removeChartMarkers(text) {
  if (!text || text.indexOf('[CHART:') === -1) return text;
  const result = [];
  let i = 0;
  while (i < text.length) {
    const pos = text.indexOf('[CHART:', i);
    if (pos === -1) { result.push(text.slice(i)); break; }
    result.push(text.slice(i, pos));
    let depth = 0;
    let end = -1;
    for (let j = pos; j < text.length; j++) {
      if (text[j] === '[') depth++;
      else if (text[j] === ']') {
        depth--;
        if (depth === 0) { end = j; break; }
      }
    }
    if (end === -1 || end > pos + 5000) { result.push(text.slice(pos)); break; }
    i = end + 1;
  }
  return result.join('');
}

/**
 * markdown 表格行 → 可读文本："| a | b |" → "a | b"
 * 纯分隔行（|:---|）→ 空串（调用方跳过）
 */
function tableRow(line) {
  const cells = line.split('|').map((c) => c.trim()).filter((c) => c.length > 0);
  return cells.join(' | ');
}

function isTableSeparator(line) {
  const cells = line.split('|').map((c) => c.trim()).filter((c) => c.length > 0);
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

/**
 * 整篇报告清洗
 * - 剔除 [FOLLOWUP:[...]] 标记
 * - 剔除 # 标题符、> 引用符、表格分隔行、管道符
 * - 列表符号保留（- 转 •，数字列表保留序号）
 */
function cleanReport(text) {
  if (!text) return '';
  // 先整体剔除 [CHART:...] 图表标记（可能跨行内嵌，逐行处理不可靠）
  const stripped = removeChartMarkers(text);
  const lines = String(stripped).split('\n');
  const out = [];

  for (const raw of lines) {
    let line = raw.trim();
    if (!line) {
      if (out.length > 0 && out[out.length - 1] !== '') out.push('');
      continue;
    }

    // FOLLOWUP 标记：单独一行直接跳过；行尾残留则剔除
    if (line.indexOf('[FOLLOWUP') === 0) continue;
    line = stripFollowup(line);
    if (!line.trim()) continue;

    // 表格分隔行（|:---| 等）跳过
    if (isTableSeparator(line)) continue;

    // 表格数据行
    if (line.startsWith('|') && line.endsWith('|')) {
      line = tableRow(line);
    }

    // 标题 / 引用符号
    line = line.replace(/^#{1,6}\s*/, '');
    line = line.replace(/^>\s*/, '');

    // 列表：- 转 •；* 也转 •；数字列表保留序号
    if (/^[-*]\s+/.test(line)) {
      line = line.replace(/^[-*]\s+/, '• ');
    }

    out.push(inline(line));
  }

  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

module.exports = { cleanReport, stripFollowup, parseCharts, removeChartMarkers };
