/* Enterprise Insight Agent V4 — 工具函数 */
var BASE = '/api/v1';
var _reportCharts = [];

/* ── 格式化 ── */
function formatCurrency(v){
  if(v===undefined||v===null||v==='-')return'-';
  var n=Number(v);
  if(isNaN(n))return v;
  if(n>=10000)return'¥'+(n/10000).toFixed(1)+'万';
  return'¥'+n.toLocaleString('zh-CN')
}
function formatPercent(v){
  if(v===undefined||v===null||v==='-')return'-';
  return Number(v).toFixed(1)+'%'
}

/* ── 转义 ── */
function escapeHtml(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML}
function htmlEscape(text){
  var map={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  return text.replace(/[&<>"']/g,function(m){return map[m]})
}
function jsEscape(s){
  return String(s||'').replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/'/g,"\\'").replace(/\n/g,'\\n').replace(/\r/g,'\\r').replace(/<\/script>/gi,'<\\/script>')
}
function tmplEscape(s){return jsEscape(String(s||'')).replace(/\${/g,'\\${')}
/* ── Supervisor 推理过程面板 ── */
function buildSupervisorPlan(sp){
  if(!sp)return'';
  try{
    var plan=typeof sp==='string'?JSON.parse(sp):sp;
    if(!plan||!plan.activated_agents)return'';
    var agentLabels={
      sales:'📊 销售分析',
      crm:'👥 会员分析',
      finance:'💰 财务分析',
      inventory:'📦 库存分析',
      supply_chain:'🚚 供应链分析'
    };
    var agents=plan.activated_agents.map(function(a){return'<span style="display:inline-block;font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(99,102,241,.12);color:var(--accent-hover);margin:2px 4px 2px 0">'+(agentLabels[a]||a)+'</span>'}).join('');
    var reasoning=plan.reasoning||'';
    var analysisPlan=plan.analysis_plan||'';
    return '<details class="sup-panel" style="margin-bottom:12px;font-size:12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:0">'+
      '<summary style="padding:10px 14px;cursor:pointer;color:var(--accent);font-weight:600;font-size:12px">🧠 分析规划 <span style="color:var(--muted);font-weight:400">· 激活 '+plan.activated_agents.length+' 个 Agent</span></summary>'+
      '<div style="padding:4px 14px 14px">'+
      (reasoning?'<div style="margin-bottom:8px"><span style="color:var(--muted);font-size:11px">推理</span><p style="margin:4px 0;color:var(--text);line-height:1.6">'+esc(reasoning)+'</p></div>':'')+
      (analysisPlan?'<div style="margin-bottom:8px"><span style="color:var(--muted);font-size:11px">分析计划</span><p style="margin:4px 0;color:var(--text);line-height:1.6">'+esc(analysisPlan)+'</p></div>':'')+
      '<div><span style="color:var(--muted);font-size:11px">激活的 Agent</span><div style="margin-top:4px">'+agents+'</div></div>'+
      '</div></details>'
  }catch(e){return ''}
}

/* ── KPI 数字递增动画 ── */
function animateKPI(el, target, suffix, duration){
  if(!el)return;
  var start=0, startTime=null;
  var dur=duration||400;
  function step(ts){
    if(!startTime)startTime=ts;
    var progress=Math.min((ts-startTime)/dur,1);
    // easeOutCubic 缓出
    var eased=1-Math.pow(1-progress,3);
    var current=Math.round(start+(target-start)*eased);
    el.textContent=formatCurrency(current)+suffix;
    if(progress<1)requestAnimationFrame(step);
  }
  requestAnimationFrame(step)
}

function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

/* ── HTML 净化（防御 XSS）：DOMPurify 封装，不可用时 DOM 兜底 ── */
function sanitizeHtml(html){
  try{
    if(typeof DOMPurify!=='undefined'&&DOMPurify.sanitize)return DOMPurify.sanitize(html);
  }catch(e){}
  /* 兜底：用浏览器 DOM 解析器移除危险元素和属性，
     保留合法 HTML（表格/图表容器等）不破坏报告渲染 */
  var div=document.createElement('div');
  div.innerHTML=html;
  // 移除危险标签
  div.querySelectorAll('script,iframe,object,embed,link,meta,base').forEach(function(el){el.remove();});
  // 移除所有 on* 事件属性
  div.querySelectorAll('*').forEach(function(el){
    for(var i=el.attributes.length-1;i>=0;i--){
      if(el.attributes[i].name.substr(0,2)==='on')el.removeAttribute(el.attributes[i].name);
    }
  });
  // 移除 javascript: / vbscript: / data: URL
  div.querySelectorAll('a[href],[src]').forEach(function(el){
    var h=el.getAttribute('href')||'',s=el.getAttribute('src')||'';
    if(/^(javascript|vbscript|data):/i.test(h))el.removeAttribute('href');
    if(/^data:/i.test(s)&&!/^data:image\//i.test(s))el.removeAttribute('src');
  });
  return div.innerHTML;
}

/* ── UI 反馈 ── */
function toast(msg,type){
  var el=document.createElement('div');el.className='toast'+(type==='error'?' toast-error':type==='success'?' toast-success':'');el.textContent=msg;
  document.body.appendChild(el);
  var duration=type==='error'?5000:type==='success'?3000:2500;
  setTimeout(function(){el.remove()},duration)
}
function copyToClipboard(text){
  navigator.clipboard.writeText(text).then(function(){toast('已复制到剪贴板')}).catch(function(){toast('复制失败')})
}
function downloadMD(report,q){
  var r=report||_lastReportText||'';
  var t=q||_lastQuestionText||'report';
  var fn=t.replace(/[<>:"\/\\|?*]/g,'_').substring(0,40)+'.md';
  var blob=new Blob([r],{type:'text/markdown;charset=utf-8'});
  var url=URL.createObjectURL(blob);
  var a=document.createElement('a');a.href=url;a.download=fn;a.click();
  URL.revokeObjectURL(url);toast('报告已下载')
}

/* ── Steps 常量 ── */
var STEPS = [
  'supervisor','sales_agent','crm_agent','finance_agent','inventory_agent','supply_chain_agent',
  'aggregator','chart_advisor','report_agent','reflection_agent','save_memory'
];
var LABELS = ['规划中','销售分析','CRM分析','财务分析','库存分析','供应链分析','整合结果','图表推荐','生成报告','质量审核','保存记录'];

/* ── 快速提问 ── */
var QUICK_QUESTIONS = {
  admin:[
    {icon:'📋',text:'整体经营分析报告'},{icon:'🌍',text:'各区域经营对比'},
    {icon:'🚚',text:'供应商准时交货率排名'},{icon:'📊',text:'各门店销售额排名'},
    {icon:'🔄',text:'退款率异常分析'},{icon:'👥',text:'会员增长趋势'}
  ],
  regional_manager:[
    {icon:'📋',text:'我负责区域的销售趋势'},{icon:'📊',text:'区域内门店排名'},
    {icon:'👥',text:'区域会员活跃度分析'},{icon:'🔄',text:'区域退款率分析'},
    {icon:'📦',text:'区域库存预警'},{icon:'📈',text:'近30天区域销售对比'}
  ],
  store_manager:[
    {icon:'📋',text:'我们店昨日经营概况'},{icon:'📈',text:'本周销售趋势'},
    {icon:'👥',text:'本店会员消费排行'},{icon:'📦',text:'本店滞销商品预警'},
    {icon:'🔄',text:'本店退款订单分析'},{icon:'💰',text:'本店客单价分析'}
  ],
  default:[
    {icon:'📊',text:'各门店销售额排名'},{icon:'📈',text:'近30天销售趋势'},
    {icon:'🔄',text:'退款率最高的门店'},{icon:'👥',text:'会员增长与留存情况'},
    {icon:'📋',text:'整体经营分析报告'},{icon:'🌍',text:'各区域经营对比'}
  ]
};
function getQuickQuestions(role){
  return QUICK_QUESTIONS[role||'']||QUICK_QUESTIONS.default;
}

/* ── 纯文本表格 → Markdown 管道表格（兜底）── */
function convertTextTables(text){
  /* 处理 LLM 偶尔生成的 tab 分隔或逐行排列的纯文本表格，
     在 marked.parse 前转为 markdown 管道符表格。 */
  var lines=text.split('\n');
  var out=[];
  var i=0;
  while(i<lines.length){
    var line=lines[i];
    var tabCount=(line.match(/\t/g)||[]).length;
    // Tab 分隔表格：一行至少 2 个 tab
    if(tabCount>=2){
      var rows=[];
      while(i<lines.length && (lines[i].match(/\t/g)||[]).length>=2){
        rows.push(lines[i].split('\t'));
        i++;
      }
      if(rows.length>=2){
        // 计算最大列数
        var colCount=0;
        rows.forEach(function(r){if(r.length>colCount)colCount=r.length});
        // 生成表头分隔行
        var sep='|'+new Array(colCount).fill(':---:').join('|')+'|';
        // 首行 = 表头，其余 = 数据行，separator 在中间
        out.push('|'+rows[0].join('|')+'|');
        out.push(sep);
        for(var ri=1;ri<rows.length;ri++){
          out.push('|'+rows[ri].join('|')+'|');
        }
        continue;
      }
    }
    out.push(line);
    i++;
  }
  return out.join('\n');
}

/* ── [CHART:...] 标签展开（括号计数法，支持嵌套 []） ── */
function expandChartTags(text){
  /* 将报告中的 [CHART:type|url_encoded_json] 标记转换为
     <div class="chart-container" data-chart='...'> 元素，
     以便 marked.parse() 保留为原始 HTML，再由 renderCharts() 渲染为 ECharts。
     V4.4: 解析 | 后的内容时排除末尾 ]，避免 JSON.parse 失败。 */
  var result=[], i=0;
  while(i<text.length){
    var pos=text.indexOf('[CHART:', i);
    if(pos===-1){result.push(text.slice(i));break}
    result.push(text.slice(i, pos));
    // 括号计数找到匹配的 ]
    var depth=0, end=-1;
    for(var j=pos;j<text.length;j++){
      if(text[j]==='[')depth++;
      else if(text[j]===']'){depth--;if(depth===0){end=j;break}}
    }
    if(end===-1||end>pos+5000){result.push(text.slice(pos));break}
    var marker=text.slice(pos, end+1);
    // 提取 | 后的内容
    var bar=marker.indexOf('|');
    if(bar===-1||bar>100){result.push(marker);i=end+1;continue}
    try{
      var encoded=marker.slice(bar+1, -1);  // 去掉末尾的 ]，只取 URL-encoded JSON
      var params=JSON.parse(decodeURIComponent(encoded));
      var safe=JSON.stringify(params).replace(/'/g,'&#39;');
      result.push('<div class="chart-container" data-chart=\''+safe+'\' style="height:'+(params.height||400)+'px;width:100%"></div>')
    }catch(e){result.push("")}
    i=end+1
  }
  return result.join('')
}

/* ── ECharts 统一暗色主题 ── */
function echartsTheme(){
  return {
    color:['#6366f1','#22c55e','#f59e0b','#ef4444','#3b82f6','#8b5cf6','#06b6d4','#f97316','#84cc16','#ec4899'],
    backgroundColor:'transparent',
    tooltip:{
      trigger:'axis',
      backgroundColor:'rgba(30,41,59,0.95)',
      borderColor:'#334155',
      textStyle:{color:'#f1f5f9',fontSize:12}
    },
    grid:{left:50,right:20,bottom:30,top:10,containLabel:false},
    xAxis:{
      axisLabel:{color:'#94a3b8',fontSize:10},
      axisLine:{lineStyle:{color:'#334155'}},
      axisTick:{show:false},
      splitLine:{show:false}
    },
    yAxis:{
      axisLabel:{color:'#94a3b8',fontSize:10},
      splitLine:{lineStyle:{color:'rgba(51,65,85,0.5)'}}
    },
    legend:{textStyle:{color:'#94a3b8',fontSize:11}},
    series:[]
  };
}
function formatAxisValue(v){
  return v>=10000?(v/10000).toFixed(0)+'万':v
}

/* ── ECharts 懒加载：echarts.min.js 在页面底部最后加载，此队列在加载完成后统一初始化图表 ── */
var _echartsCbs=[],_echartsTimer=null;
function onEChartsReady(cb){
  if(window.echarts){cb(window.echarts);return}
  _echartsCbs.push(cb);
  if(!_echartsTimer)_echartsTimer=setInterval(function(){
    if(!window.echarts)return;
    clearInterval(_echartsTimer);_echartsTimer=null;
    _echartsCbs.splice(0).forEach(function(fn){fn(window.echarts)});
  },100);
}
setTimeout(function(){if(_echartsTimer){clearInterval(_echartsTimer);_echartsTimer=null;_echartsCbs=[]}},15000);

/* ── 图表 ── */
function parseChartParams(encoded){
  try{
    var params=JSON.parse(decodeURIComponent(encoded));
    var dt=params.series?params.series[0]&&params.series[0].data?params.series:null:null;
    return{type:params.type,title:params.title||'',xData:params.x_data||[],series:params.series||[],height:params.height||400,note:params.note||''}
  }catch(e){return null}
}
function buildEChartsOption(type,config){
  var th=echartsTheme();
  var opt={
    backgroundColor:'transparent',
    tooltip:{...th.tooltip,trigger:type==='pie'?'item':'axis'},
    grid:{...th.grid,containLabel:true},
    xAxis:{...th.xAxis,data:config.xData,axisLabel:{...th.xAxis.axisLabel,rotate:config.xData&&config.xData.length>8?35:0}},
    yAxis:{...th.yAxis,axisLabel:{...th.yAxis.axisLabel,formatter:formatAxisValue}}
  };
  if(type==='bar'){
    opt.series=config.series.map(function(s,i){return{name:s.name,type:'bar',data:s.data,itemStyle:{color:th.color[i%th.color.length]},barMaxWidth:40}})
  }else if(type==='line'){
    opt.xAxis.axisLabel.rotate=0;
    opt.series=config.series.map(function(s,i){return{name:s.name,type:'line',data:s.data,smooth:true,symbol:'circle',symbolSize:6,lineStyle:{width:2},itemStyle:{color:th.color[i%th.color.length]}}})
  }else if(type==='pie'){
    opt.xAxis=undefined;opt.yAxis=undefined;opt.grid=undefined;
    opt.series=[{type:'pie',radius:['30%','55%'],center:['50%','50%'],data:config.xData.map(function(name,i){return{name:name,value:config.series[0]&&config.series[0].data?config.series[0].data[i]:1}}),label:{color:'#f1f5f9',fontSize:11},itemStyle:{borderColor:'transparent',borderWidth:2},color:th.color}]
  }
  if(config.note){opt.graphic={type:'text',left:'center',bottom:0,style:{text:config.note,fill:'#94a3b8',fontSize:10}}}
  return opt
}
/* ── 图表容器生成（不初始化 ECharts，只生成 div）── */
function renderCharts(html){
  /* 返回 HTML + chart-container div，ECharts 在 DOM 挂载后再初始化 */
  return html
}

/* ── DOM 挂载后初始化图表（修复：在 detached 元素上 init 导致黑框）── */
function initChartsInBubble(bubbleEl){
  var containers=bubbleEl.querySelectorAll('.chart-container');
  if(!containers.length)return;
  containers.forEach(function(container){
    var raw=container.getAttribute('data-chart');
    if(!raw){container.style.display='none';return}
    try{
      var params=JSON.parse(raw);
      // 已有图表的容器不再重复初始化（历史报告回溯时不会销毁之前的气泡）
      if(container._chart){container._chart.resize();return}
      var opt=buildEChartsOption(params.type,params);
      var chart=echarts.init(container);
      chart.setOption(opt);
      container._chart=chart
    }catch(e){console.warn('chart init failed:',e);container.style.display='none'}
  });
  // 初始化失败的图表容器自动隐藏（避免出现看不懂的空框）
  containers.forEach(function(c){
    if(c.style.display==='none' || !c.querySelector('canvas')){
      c.style.display='none'
    }
  })
}

/* ── 数据溯源面板 ── */
function buildTracePanel(ds){
  if(!ds||!ds.length)return'';
  var html='<details class="trace-panel"><summary>📋 数据来源（'+ds.length+' 条 SQL）</summary>';
  ds.forEach(function(d,i){
    html+='<div class="trace-item"><div class="trace-claim">'+
      esc(d.agent||'Agent')+' — 第 '+d.id+' 步：'+
      (d.claim||'')+' <span style="color:var(--muted);font-weight:400">'+
      '（耗时 '+d.execution_time_ms+'ms，返回 '+d.row_count+' 行）</span></div>'+
      '<div class="trace-sql">'+escapeHtml(d.sql||'')+'</div></div>'
  });
  html+='</details>';
  return html
}

/* ── 追问按钮 ── */
function buildFollowupButtons(qs){
  if(!qs||!qs.length)return'';
  return'<div class="followup-btns">'+qs.map(function(q){return'<button class="followup-btn" data-action="ask-followup" data-question="'+jsEscape(q)+'">'+esc(q)+'</button>'}).join('')+'</div>'
}

/* ── 杂项 ── */
function _fmtDate(d){
  var dt=new Date(d);
  if(isNaN(dt.getTime()))return d;
  var pad=function(n){return n<10?'0'+n:n};
  return dt.getFullYear()+'-'+pad(dt.getMonth()+1)+'-'+pad(dt.getDate())+' '+pad(dt.getHours())+':'+pad(dt.getMinutes())
}
function _calcDateRange(preset){
  var n=new Date();
  switch(preset){
    case'7':return 7;
    case'30':return 30;
    case'month':return n.getDate();
    case'prevMonth':return new Date(n.getFullYear(),n.getMonth(),0).getDate();
    default:return 30
  }
}

/* 全局 resize：统一处理报告 + 看板内嵌图表 + 监控面板图表 */
window.addEventListener('resize',function(){
  document.querySelectorAll('.chart-container').forEach(function(el){
    if(el._chart)el._chart.resize()
  });
  Object.values(window._dashCharts||{}).forEach(function(c){c&&c.resize()});
  if(window._monitorChart)window._monitorChart.resize()
});
