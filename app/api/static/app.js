/* Enterprise Insight Agent V4 — Application Logic */
var BASE = '/api/v1';
var token = '';
var sessionId = null;
var lastRecordId = null;
var pendingFeedback = null;
var dismissedIds = new Set();
var _lastReportText = '';
var _lastQuestionText = '';

function _copyReport(){ if(_lastReportText) copyToClipboard(_lastReportText); }
function _shareReport(){ if(_lastReportText) shareReport(_lastReportText, _lastQuestionText); }

var STEPS = [
  'supervisor','sales_agent','crm_agent','finance_agent',
  'aggregator','chart_advisor','report_agent','reflection_agent','save_memory'
];
var LABELS = ['规划中','销售分析','CRM分析','财务分析','整合结果','图表推荐','生成报告','质量审核','保存记录'];

var QUICK_QUESTIONS = {
  admin:[
    {icon:'📋',text:'整体经营分析报告'},
    {icon:'🌍',text:'各区域经营对比'},
    {icon:'🚚',text:'供应商准时交货率排名'},
    {icon:'📊',text:'各门店销售额排名'},
    {icon:'🔄',text:'退款率异常分析'},
    {icon:'👥',text:'会员增长趋势'}
  ],
  regional_manager:[
    {icon:'📋',text:'我负责区域的销售趋势'},
    {icon:'📊',text:'区域内门店排名'},
    {icon:'👥',text:'区域会员活跃度分析'},
    {icon:'🔄',text:'区域退款率分析'},
    {icon:'📦',text:'区域库存预警'},
    {icon:'📈',text:'近30天区域销售对比'}
  ],
  store_manager:[
    {icon:'📋',text:'我们店昨日经营概况'},
    {icon:'📈',text:'本周销售趋势'},
    {icon:'👥',text:'本店会员消费排行'},
    {icon:'📦',text:'本店滞销商品预警'},
    {icon:'🔄',text:'本店退款订单分析'},
    {icon:'💰',text:'本店客单价分析'}
  ],
  default:[
    {icon:'📊',text:'各门店销售额排名'},
    {icon:'📈',text:'近30天销售趋势'},
    {icon:'🔄',text:'退款率最高的门店'},
    {icon:'👥',text:'会员增长与留存情况'},
    {icon:'📋',text:'整体经营分析报告'},
    {icon:'🌍',text:'各区域经营对比'}
  ]
};

function getQuickQuestions(username){
  var roleMap={admin:'admin',zhangsan:'regional_manager',lisi:'store_manager'};
  var role=roleMap[username]||'default';
  return QUICK_QUESTIONS[role]||QUICK_QUESTIONS.default;
}

var voiceListening = false;
var voiceRecognition = null;

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

function escapeHtml(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML}

function toast(msg){
  var el=document.createElement('div');el.className='toast';el.textContent=msg;
  document.body.appendChild(el);setTimeout(function(){el.remove()},2500)
}

function copyToClipboard(text){
  navigator.clipboard.writeText(text).then(function(){toast('已复制到剪贴板')}).catch(function(){toast('复制失败')})
}

function downloadMD(report,q){
  var fn=(q||'report').replace(/[<>:"\/\\|?*]/g,'_').substring(0,40)+'.md';
  var blob=new Blob([report],{type:'text/markdown;charset=utf-8'});
  var url=URL.createObjectURL(blob);
  var a=document.createElement('a');a.href=url;a.download=fn;a.click();
  URL.revokeObjectURL(url);toast('报告已下载')
}

// PDF export — calls backend /api/v1/weekly/export
async function exportPDF(){
  if(!_lastReportText){toast('没有可导出的报告');return}
  var title=(_lastQuestionText||'经营分析报告').substring(0,40);
  try{
    var r=await fetch(BASE+'/weekly/export',{
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
      body:JSON.stringify({report:_lastReportText,title:title,format:'pdf'})
    });
    if(!r.ok){
      // 后端 PDF 不可用（如 weasyprint 未安装），降级为 Markdown 下载
      toast('PDF 服务不可用，已降级为 Markdown 下载');
      downloadMD(_lastReportText,title);
      return;
    }
    var blob=await r.blob();
    var url=URL.createObjectURL(blob);
    var a=document.createElement('a');a.href=url;a.download=title.replace(/[<>:"\/\\|?*]/g,'_')+'.pdf';a.click();
    URL.revokeObjectURL(url);
    toast('PDF 已下载');
  }catch(e){
    toast('PDF 服务不可用，已降级为 Markdown 下载');
    downloadMD(_lastReportText,title);
  }
}

// HTML escape utility
function htmlEscape(text){
  return String(text||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
// JavaScript string escape for safe use in onclick attributes
function jsEscape(s){
  return String(s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/\n/g,'\\n').replace(/\r/g,'');
}
// Escape backtick-template content for onclick binding
function tmplEscape(s){
  return String(s||'').replace(/`/g,'\\`').replace(/\$/g,'\\$').replace(/\\/g,'\\\\');
}

// Markdown parser
var marked={parse:function(md){
  var h=htmlEscape(md);
  h=h.replace(/\[CHART:\w+\|.+?\]/g,'');
  h=h.replace(/\[FOLLOWUP:.*?\]\]/g,'');
  h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/\*(.+?)\*/g,'<em>$1</em>');
  h=h.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  h=h.replace(/^## (.+)$/gm,'<h2>$1</h2>');
  h=h.replace(/^# (.+)$/gm,'<h1>$1</h1>');
  // Ordered lists: "1. item" → <ol-li>, then grouped into <ol>
  h=h.replace(/^\d+\. (.+)$/gm,'<ol-li>$1</ol-li>');
  // Unordered lists: "- item" → <ul-li>, then grouped into <ul>
  h=h.replace(/^- (.+)$/gm,'<ul-li>$1</ul-li>');
  // Group consecutive same-type items
  h=h.replace(/(<ol-li>.*<\/ol-li>\n?)+/g,'<ol>$&</ol>');
  h=h.replace(/(<ul-li>.*<\/ul-li>\n?)+/g,'<ul>$&</ul>');
  // Normalize custom tags back to standard <li>
  h=h.replace(/<\/?ol-li>/g,function(m){return m==='<ol-li>'?'<li>':'</li>'});
  h=h.replace(/<\/?ul-li>/g,function(m){return m==='<ul-li>'?'<li>':'</li>'});
  h=h.replace(/((?:^\|.+\|\n?)+)/gm,function(block){
    var lines=block.trim().split('\n');
    if(lines.length<1)return block;
    var headerCells=lines[0].split('|').filter(function(x){return x.trim()});
    var colCount=headerCells.length;
    if(colCount===0)return block;
    var hasSep=lines.length>1&&lines[1].indexOf('---')!==-1;
    var dataStart=hasSep?2:1;
    var t='<div class="data-table"><table><thead><tr>';
    for(var i=0;i<colCount;i++){t+='<th>'+headerCells[i].trim()+'</th>'}
    t+='</tr></thead><tbody>';
    for(var r=dataStart;r<lines.length;r++){
      if(lines[r].indexOf('---')!==-1)continue;
      var cells=lines[r].split('|');
      if(cells.length&&!cells[0].trim())cells.shift();
      if(cells.length&&!cells[cells.length-1].trim())cells.pop();
      t+='<tr>';
      for(var j=0;j<colCount;j++){t+='<td>'+(j<cells.length?cells[j].trim():'')+'</td>'}
      t+='</tr>'
    }
    t+='</tbody></table></div>';return t
  });
  h=h.replace(/\n\n/g,'</p><p>');h='<p>'+h+'</p>';return h
}};

// Session management
async function newSession(){
  if(!token){toast('请先登录');return}
  try{
    var r=await fetch(BASE+'/session/create',{method:'POST',headers:{'Authorization':'Bearer '+token}});
    if(r.ok){
      var d=await r.json();sessionId=d.session_id;
      document.getElementById('sessionIdDisplay').textContent=sessionId.substring(0,8)+'...';
      document.getElementById('entityBox').style.display='none';
      document.getElementById('entityTags').innerHTML='';
      document.getElementById('chat').innerHTML='<div class="empty-state" id="emptyState">'+
        '<div class="greeting" id="greetingText">👋 欢迎</div>'+
        '<div class="greeting-sub" id="greetingSub">输入经营分析问题开始对话</div>'+
        '<div class="dashboard-card" id="dashboardCard" style="display:none">'+
          '<div class="dash-item"><div class="dash-val" id="dashSales">-</div><div class="dash-label">昨日销售额</div></div>'+
          '<div class="dash-item"><div class="dash-val" id="dashStores">-</div><div class="dash-label">活跃门店</div></div>'+
          '<div class="dash-item"><div class="dash-val" id="dashRefund">-</div><div class="dash-label">近7天退款率</div></div>'+
          '<div class="dash-item"><div class="dash-val" id="dashMembers">-</div><div class="dash-label">会员总数</div></div>'+
          '<div class="dash-item"><div class="dash-val" id="dashOrders">-</div><div class="dash-label">近24h订单</div></div>'+
        '</div>'+
        '<div class="quick-grid" id="quickGrid"></div>'+
        '<p style="font-size:12px;color:var(--muted)">或直接输入问题：</p></div>';
      document.getElementById('quickBar').style.display='none';
      document.getElementById('question').value='';
      renderQuickGrid();
      loadDashboard();
      toast('新会话已创建')
    }
  }catch(e){toast('创建会话失败')}
}

async function loadSessionInfo(){
  if(!sessionId||!token)return;
  try{
    var r=await fetch(BASE+'/session/'+sessionId,{headers:{'Authorization':'Bearer '+token}});
    if(r.ok){
      var d=await r.json();var em=d.entity_memory||{};var keys=Object.keys(em);
      if(keys.length>0){
        document.getElementById('entityBox').style.display='block';
        var tags='';for(var i=0;i<keys.length;i++){tags+='<span class="ent">'+escapeHtml(keys[i])+'</span>'}
        document.getElementById('entityTags').innerHTML=tags
      }
    }
  }catch(e){}
}

// Chart rendering
function parseChartParams(encoded){
  try{
    var decoded=decodeURIComponent(encoded);
    return JSON.parse(decoded)
  }catch(e){
    var c={};var pairs=encoded.split('|');
    for(var i=0;i<pairs.length;i++){
      var idx=pairs[i].indexOf('=');if(idx===-1)continue;
      var key=pairs[i].substring(0,idx);var val=pairs[i].substring(idx+1);
      try{c[key]=JSON.parse(val)}catch(ex){c[key]=val}
    }
    return c
  }
}

function buildEChartsOption(type,config){
  var base={tooltip:{trigger:'axis'},grid:{left:'3%',right:'4%',bottom:'3%',containLabel:true}};
  switch(type){
    case'bar':return Object.assign({},base,{
      title:{text:config.title||'',textStyle:{color:'#f1f5f9',fontSize:14}},
      xAxis:{type:'category',data:config.x_data||[],axisLabel:{color:'#94a3b8',rotate:config.x_data&&config.x_data.length>8?45:0}},
      yAxis:{type:'value',axisLabel:{color:'#94a3b8'}},
      series:(config.series||[]).map(function(s){return Object.assign({},s,{type:'bar',itemStyle:{color:'#6366f1',borderRadius:[4,4,0,0]}})})
    });
    case'line':return Object.assign({},base,{
      title:{text:config.title||'',textStyle:{color:'#f1f5f9',fontSize:14}},
      xAxis:{type:'category',data:config.x_data||[],axisLabel:{color:'#94a3b8'}},
      yAxis:{type:'value',axisLabel:{color:'#94a3b8'}},
      series:(config.series||[]).map(function(s){return Object.assign({},s,{type:'line',smooth:true,lineStyle:{color:'#22c55e'},itemStyle:{color:'#22c55e'}})})
    });
    case'pie':return{
      title:{text:config.title||'',textStyle:{color:'#f1f5f9',fontSize:14}},
      tooltip:{trigger:'item'},
      legend:{orient:'vertical',left:'left',textStyle:{color:'#94a3b8'}},
      series:[{type:'pie',radius:['40%','70%'],data:(config.x_data||[]).map(function(name,i){return{name:name,value:(config.series&&config.series[0]&&config.series[0].data)?config.series[0].data[i]:0}}),label:{color:'#94a3b8'}}]
    };
    case'scatter':return Object.assign({},base,{
      title:{text:config.title||'',textStyle:{color:'#f1f5f9',fontSize:14}},
      xAxis:{type:'value',axisLabel:{color:'#94a3b8'}},
      yAxis:{type:'value',axisLabel:{color:'#94a3b8'}},
      series:(config.series||[]).map(function(s){return Object.assign({},s,{type:'scatter',symbolSize:10})})
    });
    case'radar':return{
      title:{text:config.title||'',textStyle:{color:'#f1f5f9',fontSize:14}},
      tooltip:{},
      radar:{indicator:(config.x_data||[]).map(function(name){return{name:name,max:100}}),axisName:{color:'#94a3b8'}},
      series:[{type:'radar',data:(config.series||[]).map(function(s){return{name:s.name,value:s.data}})}]
    };
    default:return null
  }
}

function renderCharts(html){
  var chartRegex=/\[CHART:(\w+)\|(.+?)\]/g;
  var match;var result=html;var charts=[];
  while((match=chartRegex.exec(html))!==null){
    var chartType=match[1];var paramsStr=match[2];var config=parseChartParams(paramsStr);
    var chartId='chart_'+Math.random().toString(36).substring(2,10);
    charts.push({id:chartId,type:chartType,config:config});
    result=result.replace(match[0],
      '<div id="'+chartId+'" class="chart-container" style="height:'+(config.height||400)+'px"></div>'+
      (config.note?'<div style="font-size:11px;color:var(--muted);margin:-8px 0 8px 0">'+escapeHtml(config.note)+'</div>':'')
    )
  }
  setTimeout(function(){
    if(typeof echarts==='undefined')return;
    for(var i=0;i<charts.length;i++){
      var ch=charts[i];var dom=document.getElementById(ch.id);
      if(!dom)continue;var option=buildEChartsOption(ch.type,ch.config);
      if(!option)continue;
      try{var instance=echarts.init(dom);instance.setOption(option);window.addEventListener('resize',function(){instance.resize()})}
      catch(e){console.error('ECharts error:',e)}
    }
  },100);
  return result
}

function buildTracePanel(ds){
  if(!ds||ds.length===0)return'';
  var h='<details class="trace-panel"><summary>📊 数据溯源（'+ds.length+' 条数据主张）</summary>';
  for(var i=0;i<ds.length;i++){
    h+='<div class="trace-item"><div class="trace-claim">['+ds[i].id+'] '+escapeHtml(ds[i].claim||'数据主张')+'</div>'+
      '<div class="trace-meta"><span>来源：'+escapeHtml(ds[i].agent||'未知')+' Agent</span>'+
      '<span>耗时：'+(ds[i].execution_time_ms||'?')+'ms</span>'+
      '<span>返回：'+(ds[i].row_count||'?')+' 行</span></div>';
    if(ds[i].sql){h+='<div class="trace-sql">'+escapeHtml(ds[i].sql)+'</div>'}
    h+='</div>'
  }
  h+='</details>';return h
}

function buildFollowupButtons(qs){
  if(!qs||qs.length===0)return'';
  var h='<div class="followup-btns"><span style="font-size:12px;color:var(--muted);margin-right:4px">💡 您可能还想问：</span>';
  for(var i=0;i<qs.length;i++){
    h+='<button class="followup-btn" onclick="askFollowup(\''+escapeHtml(qs[i].replace(/'/g,"\\'"))+'\')">'+escapeHtml(qs[i])+'</button>'
  }
  h+='</div>';return h
}

function askFollowup(q){
  document.getElementById('question').value=q;
  document.getElementById('form').dispatchEvent(new Event('submit'))
}

function showFeedback(rating){
  if(!lastRecordId){toast('无法反馈：缺少分析记录');return}
  pendingFeedback={rating:rating,reason:''};
  document.getElementById('feedbackTitle').textContent=rating==='helpful'?'👍 感谢您的认可！':'👎 感谢您的反馈';
  document.getElementById('feedbackModal').style.display='flex';
  document.getElementById('feedbackReason').value=''
}

function closeFeedbackModal(){document.getElementById('feedbackModal').style.display='none';pendingFeedback=null}

async function submitFeedback(){
  if(!pendingFeedback)return;
  pendingFeedback.reason=document.getElementById('feedbackReason').value.trim();
  try{
    var r=await fetch(BASE+'/feedback/submit',{
      method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
      body:JSON.stringify({analysis_history_id:lastRecordId,rating:pendingFeedback.rating,reason:pendingFeedback.reason,agent_issues:{}})
    });
    if(r.ok){toast('✅ 反馈已提交，感谢！')}else{toast('反馈提交失败')}
  }catch(e){toast('网络错误')}
  closeFeedbackModal()
}

// Login
function showLogin(){
  document.getElementById('loginUser').value='';
  document.getElementById('loginPass').value='';
  document.getElementById('loginError').style.display='none';
  document.getElementById('loginOverlay').style.display='flex';
  setTimeout(function(){document.getElementById('loginUser').focus()},100)
}

function togglePassword(){
  var pw=document.getElementById('loginPass');
  var btn=pw.parentNode.querySelector('.pw-toggle');
  if(pw.type==='password'){pw.type='text';btn.textContent='👁‍🗨'}
  else{pw.type='password';btn.textContent='👁'}
}

function fillUser(u){
  document.getElementById('loginUser').value=u;
  document.getElementById('loginPass').focus();
  document.getElementById('loginError').style.display='none'
}

async function doLogin(e){
  e.preventDefault();
  var user=document.getElementById('loginUser').value.trim();
  var pass=document.getElementById('loginPass').value;
  if(!user){document.getElementById('loginError').textContent='请输入用户名';document.getElementById('loginError').style.display='block';return}
  if(!pass){document.getElementById('loginError').textContent='请输入密码';document.getElementById('loginError').style.display='block';return}
  try{
    var r=await fetch(BASE+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass})});
    if(r.ok){
      var d=await r.json();token=d.access_token;
      localStorage.setItem('eia_token',token);
      localStorage.setItem('eia_username',user);
      document.getElementById('loginOverlay').style.display='none';
      document.getElementById('status').textContent='● '+user+' 已连接';
      document.getElementById('logoutBtn').style.display='block';
      var rl={'admin':'总部管理员','zhangsan':'区域经理-华东','lisi':'店长-旗舰店040'};
      var rs={'admin':'全部权限','zhangsan':'分析+历史+周报+预警查看','lisi':'仅分析+查看历史'};
      document.getElementById('roleName').textContent=rl[user]||user;
      document.getElementById('roleScope').textContent=rs[user]||'';
      document.getElementById('roleInfo').style.display='block';
      // 仅管理员显示系统管理按钮
      if(user==='admin') document.getElementById('adminBtn').style.display='block';
      _lastUser=user;
      loadHistory();await newSession();
      document.getElementById('tabBar').style.display='flex';
      switchTab('dashboard');
      loadDashboardOverview();
    }else{
      var err=await r.json();document.getElementById('loginError').textContent=err.detail||'登录失败';document.getElementById('loginError').style.display='block'
    }
  }catch(e){document.getElementById('loginError').textContent='网络无法连接';document.getElementById('loginError').style.display='block'}
}

// Core: Ask question
// 通用报告渲染（缓存命中 + 流式输出共用）
function appendReportBubble(report,question,data){
  var html=marked.parse(report);
  html=renderCharts(html);
  html+='<div style=margin-top:16px;padding:14px 16px;background:var(--bg);border:1px solid var(--border);border-radius:10px;font-size:11px;line-height:1.8>'+
    '<div style=display:flex;align-items:center;gap:6px;margin-bottom:6px><span style=font-size:14px>🛡️</span><span style=font-weight:600;color:var(--text)>本报告信任分级</span></div>'+
    '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--green);font-weight:600;white-space:nowrap>✅ 数据层</span><span style=color:var(--muted)>数据直接来自您的数据库，每条结论可点击 <span style=color:var(--accent)>📊 查看SQL</span> 追溯原始查询，可信度极高</span></div>'+
    '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--amber);font-weight:600;white-space:nowrap>⚠️ 分析层</span><span style=color:var(--muted)>趋势判断和原因分析由 AI 基于数据推理生成，建议结合业务经验判断</span></div>'+
    '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--accent);font-weight:600;white-space:nowrap>💡 建议层</span><span style=color:var(--muted)>经营建议为 AI 参考性输出，执行前请结合实际情况进行人工复核</span></div>'+
    '<div style=margin-top:6px;font-size:10px;color:var(--muted);text-align:right>本报告由 AI 自动生成 · 符合《生成式人工智能服务管理暂行办法》</div></div>';
  // Store report for copy/share (use raw text, not HTML-escaped)
  _lastReportText = report;
  _lastQuestionText = question;
  html+='<div class=\"export-bar\" style=\"display:flex;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);flex-wrap:wrap;align-items:center\">'+
    '<button class=\"export-btn\" style=\"font-size:11px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--muted);cursor:pointer\" onclick=\"_copyReport()\">📋 复制</button>'+
    '<button class=\"share-btn\" onclick=\"_shareReport()\">📤 分享</button>'+
    '<button class=\"export-btn\" style=\"font-size:11px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--muted);cursor:pointer\" onclick=\"exportPDF()\">📄 PDF</button>'+
    '<button class=\"print-btn\" onclick=\"window.print()\">🖨️ 打印</button></div>';
  html+=buildTracePanel(data.data_sources||[]);
  html+=buildFollowupButtons(data.followup_questions||[]);
  if(data.record_id) { lastRecordId=data.record_id; html+='<div class=\"feedback-bar\"><span>有帮助吗？</span><button class=\"feedback-btn\" onclick=\"showFeedback(\'helpful\')\">👍</button><button class=\"feedback-btn\" onclick=\"showFeedback(\'inaccurate\')\">👎</button></div>'; }
  var bubble=document.createElement('div');bubble.className='msg assistant';
  bubble.innerHTML='<div class=bubble>'+html+'</div>';
  document.getElementById('chat').appendChild(bubble);
  document.getElementById('chat').scrollTop=document.getElementById('chat').scrollHeight;
}

var _isAnalyzing = false;
var _abortController = null;  // V4: 取消分析用的 AbortController

function cancelAnalysis(){
  if(_abortController){_abortController.abort();_abortController=null}
  var progress=document.getElementById('progress');if(progress)progress.remove();
  var streamEl=document.getElementById('streamContent');
  if(streamEl){
    var bubble=streamEl.parentNode;
    bubble.innerHTML+='<p style=\"color:var(--amber);font-size:12px;margin-top:8px\">已取消</p>';
  }
  toast('分析已取消');
}

async function ask(e){
  e.preventDefault();
  if(_isAnalyzing){toast('请等待当前分析完成');return}
  var q=document.getElementById('question').value.trim();
  if(!q||!token)return;
  if(!sessionId)await newSession();
  // Auto-switch to chat tab when user asks a question
  if(_currentTab==='dashboard')switchTab('chat');

  _isAnalyzing = true;
  var btn=document.getElementById('btn');btn.disabled=false;btn.textContent='取消';btn.style.background='var(--red)';btn.onclick=cancelAnalysis;
  _abortController = new AbortController();
  var el=document.getElementById('chat');
  var empty=el.querySelector('.empty-state');if(empty)empty.remove();

  // User bubble
  el.innerHTML+='<div class="msg user"><div class="bubble">'+escapeHtml(q)+'</div></div>';

  // Progress panel
  var ph='<div class="progress" id="progress"><h3><div class="spinner"></div><span id="progressTitle">' + '分析进行中...' + '</span></h3>';
  ph+='<div id="progressMsg" style="font-size:12px;color:var(--accent);margin:0 0 10px 0;min-height:18px;transition:color 0.3s"></div>';
  ph+='<div class="steps">';
  for(var i=0;i<STEPS.length;i++){ph+='<div class="step" id="step-'+STEPS[i]+'">'+LABELS[i]+'<span class="check"> ✓</span></div>'}
  ph+='</div></div>';
  el.innerHTML+=ph;el.scrollTop=el.scrollHeight;
  document.getElementById('question').value='';

  try{
    var body={question:q};if(sessionId)body.session_id=sessionId;

    // V4 流式优先：启动 SSE 流（实时进度 + token 逐字输出）
    // 同时并行请求缓存接口，若缓存秒返则取消流式使用缓存
    var streamResp=await fetch(BASE+'/analysis/analyze-stream',{
      method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
      body:JSON.stringify(body),
      signal:_abortController.signal
    });

    if(!streamResp.ok){var errText=await streamResp.text();throw new Error('分析请求失败: '+streamResp.status+' '+errText.slice(0,200))}

    // V4: 并行发起缓存检查（check_cache=true → 仅查 Redis，不触发 LLM）
    var cachePromise=fetch(BASE+'/analysis/analyze?check_cache=true',{
      method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
      body:JSON.stringify(body),
      signal:_abortController.signal
    });

    var reader=streamResp.body.getReader();
    var decoder=new TextDecoder();
    var buffer='';
    var finalReport='',finalErrors=[],finalReflection=false;
    var finalDataSources=[],finalFollowups=[],finalRecordId=null;
    var streamBubble=null,streamContent='',streamChat=document.getElementById('chat');
    var cacheUsed=false;
    var firstTokenReceived=false;

    while(true){
      var result;
      try{result=await reader.read()}catch(e){break}  // reader cancelled → exit loop
      if(result.done)break;
      buffer+=decoder.decode(result.value,{stream:true});
      var lines=buffer.split('\n');buffer=lines.pop()||'';
      for(var i2=0;i2<lines.length;i2++){
        var line=lines[i2];
        if(line.indexOf('data: ')!==0)continue;
        try{
          var evt=JSON.parse(line.substring(6));
          if(evt.type==='step'||evt.type==='phase'){
            var stepEl=document.getElementById('step-'+evt.node);
            if(stepEl){
              if(evt.status==='done'){stepEl.classList.add('done');stepEl.classList.remove('active')}
              else if(evt.status==='start'){stepEl.classList.add('active');stepEl.classList.remove('done')}
            }
            // V4: 更新进度标题和消息
            if(evt.status==='start'){
              var titleEl=document.getElementById('progressTitle');
              if(titleEl)titleEl.textContent=evt.label||'分析进行中...';
              var msgEl=document.getElementById('progressMsg');
              if(msgEl&&evt.message)msgEl.textContent=evt.message;
            }
          }else if(evt.type==='progress'){
            // V4: Agent 节点推送的详细进度消息（如"正在查询销售数据..."）
            var msgEl=document.getElementById('progressMsg');
            if(msgEl&&evt.message)msgEl.textContent=evt.message;
            // 同时更新步骤为 active 状态
            if(evt.node){
              var stepEl=document.getElementById('step-'+evt.node);
              if(stepEl&&!stepEl.classList.contains('done'))stepEl.classList.add('active');
            }
          }else if(evt.type==='token'){
            // V4: 首 token 到达时检查缓存是否已秒返
            // cachePromise 在流式启动时已并行发起，此时大概率已完成（Redis GET < 10ms）
            if(!firstTokenReceived){
              firstTokenReceived=true;
              try{
                var cacheResult=await cachePromise;
                if(cacheResult&&cacheResult.ok){
                  var cacheData=await cacheResult.json();
                  if(cacheData.report){
                    // 缓存秒返，取消流式，使用缓存结果
                    cacheUsed=true;
                    finalReport=cacheData.report;
                    finalRecordId=cacheData.record_id;
                    finalDataSources=cacheData.data_sources||[];
                    finalFollowups=cacheData.followup_questions||[];
                    finalErrors=cacheData.agent_errors||[];
                    finalReflection=cacheData.reflection_passed||false;
                    reader.cancel();
                    break;
                  }
                }
              }catch(e){}
            }
            // Token 流式输出：逐字追加到页面
            if(!streamBubble){
              streamBubble=document.createElement('div');
              streamBubble.className='msg assistant';
              streamBubble.innerHTML='<div class=bubble id=streamContent style=white-space:pre-wrap;font-size:14px;line-height:1.8></div>';
              var pg=document.getElementById('progress');
              if(pg)streamChat.insertBefore(streamBubble,pg);
              else streamChat.appendChild(streamBubble);
            }
            streamContent+=evt.text;
            var el=document.getElementById('streamContent');
            if(el){
              try{el.innerHTML=marked.parse(streamContent)}catch(e){el.textContent=streamContent}
              streamChat.scrollTop=streamChat.scrollHeight;
            }
          }else if(evt.type==='done'){
            finalReport=evt.report||'';finalErrors=evt.errors||[];finalReflection=evt.reflection_passed;
            finalDataSources=evt.data_sources||[];finalFollowups=evt.followup_questions||[];
            finalRecordId=evt.record_id||null
          }
        }catch(e){}
      }
      // V4: 缓存命中后跳出外层的 while 循环
      if(cacheUsed)break;
    }

    // Remove progress panel
    var progress=document.getElementById('progress');if(progress)progress.remove();
    lastRecordId=finalRecordId;

    // Stream 结束后：如果有完整报告，替换流式 bubble；否则保留（取消时显示"已取消"）
    if(finalReport && streamBubble){streamBubble.remove();streamBubble=null}
    // 仅当流式正常结束时，用 streamContent 覆盖 finalReport（缓存路径已设置 finalReport）
    if(!cacheUsed && streamContent) finalReport=streamContent;

    if(finalReport){
      appendReportBubble(finalReport,q,{
        data_sources:finalDataSources,
        followup_questions:finalFollowups,
        record_id:finalRecordId
      });
    } else {
      el.innerHTML+='<div class=\"msg assistant\"><div class=\"bubble\"><p style="color:var(--amber)">未生成报告内容</p>'+
        (finalErrors&&finalErrors.length>0?
          '<div style="margin-top:8px;font-size:12px;color:var(--muted)">'+
            finalErrors.map(function(e){return'<p style="margin:4px 0">'+(e.icon||'⚠️')+' <b>'+escapeHtml(e.agent||'unknown')+'</b>: '+escapeHtml(e.user_message||e.error||'')+'</p>'}).join('')+
          '</div>':'')+
        '</div></div>'
    }
    el.scrollTop=el.scrollHeight;
    document.getElementById('quickBar').style.display='flex';
    loadHistory();loadSessionInfo()
  } catch(err) {
    var progressEl=document.getElementById('progress');if(progressEl)progressEl.remove();
    el.innerHTML+='<div class="msg assistant"><div class="bubble" style="color:var(--red)">请求失败：'+escapeHtml(err.message)+'</div></div>'
  } finally {
    _isAnalyzing=false;_abortController=null;
    var b=document.getElementById('btn');
    b.disabled=false;b.textContent='提问';b.style.background='var(--accent)';b.onclick=null;
    return false
  }
}

// History
function dismissHistory(id, e){
  e.stopPropagation();
  dismissedIds.add(id);
  var item=document.querySelector('.history-item[data-id="'+id+'"]');
  if(item)item.remove();
  var detail=document.getElementById('history-detail-'+id);
  if(detail)detail.remove()
}

function closeHistoryDetail(id){
  var detail=document.getElementById('history-detail-'+id);
  if(detail)detail.remove();
  var items=document.querySelectorAll('.history-item');
  for(var i=0;i<items.length;i++){items[i].classList.remove('active')}
}

async function loadHistory(){
  try{
    var r=await fetch(BASE+'/analysis/history?page=1&page_size=10',{headers:{'Authorization':'Bearer '+token}});
    var d=await r.json();
    var html='';
    var hasItems=false;
    for(var i=0;i<d.records.length;i++){
      (function(h){
        if(dismissedIds.has(h.id))return;
        hasItems=true;
        html+='<div class="history-item" data-id="'+h.id+'" onclick="viewHistoryDetail('+h.id+')">'+
          '<span class="history-dismiss" title="从列表移除" onclick="dismissHistory('+h.id+',event)">&times;</span>'+
          '<div class="q">'+escapeHtml(h.question.substring(0,55))+'</div>'+
          '<div class="t">'+escapeHtml((h.summary||'').substring(0,70))+'</div></div>'
      })(d.records[i])
    }
    if(!hasItems){html='<div style="font-size:11px;color:var(--muted);padding:8px">暂无历史记录</div>'}
    document.getElementById('history').innerHTML=html
  }catch(e){}
}

async function viewHistoryDetail(id){
  var items=document.querySelectorAll('.history-item');
  for(var i=0;i<items.length;i++){
    items[i].classList.remove('active');
    if(items[i].getAttribute('data-id')===String(id)){items[i].classList.add('active')}
  }
  try{
    var r=await fetch(BASE+'/analysis/history/'+id,{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok){toast('历史记录加载失败');return}
    var detail=await r.json();
    var el=document.getElementById('chat');
    var html='<div id="history-detail-'+id+'" class="msg history-msg">'+
      '<div class="history-label">📋 '+escapeHtml(detail.question)+
      '<span class="close-detail" title="关闭详情" onclick="closeHistoryDetail('+id+')">&times;</span></div>'+
      '<div class="msg assistant"><div class="bubble">';
    if(detail.report){
      var parsed=marked.parse(detail.report);
      html+=renderCharts(parsed);
      html+='<div style=margin-top:16px;padding:14px 16px;background:var(--bg);border:1px solid var(--border);border-radius:10px;font-size:11px;line-height:1.8>'+
        '<div style=display:flex;align-items:center;gap:6px;margin-bottom:6px><span style=font-size:14px>🛡️</span><span style=font-weight:600;color:var(--text)>本报告信任分级</span></div>'+
        '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--green);font-weight:600;white-space:nowrap>✅ 数据层</span><span style=color:var(--muted)>数据直接来自您的数据库，每条结论可点击 <span style=color:var(--accent)>📊 查看SQL</span> 追溯原始查询，可信度极高</span></div>'+
        '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--amber);font-weight:600;white-space:nowrap>⚠️ 分析层</span><span style=color:var(--muted)>趋势判断和原因分析由 AI 基于数据推理生成，建议结合业务经验判断</span></div>'+
        '<div style=display:flex;align-items:flex-start;gap:8px><span style=color:var(--accent);font-weight:600;white-space:nowrap>💡 建议层</span><span style=color:var(--muted)>经营建议为 AI 参考性输出，执行前请结合实际情况进行人工复核</span></div>'+
        '<div style=margin-top:6px;font-size:10px;color:var(--muted);text-align:right>本报告由 AI 自动生成 · 符合《生成式人工智能服务管理暂行办法》</div></div>';
    } else {
      html+='<p style="color:var(--muted)">该记录暂无报告内容</p>'
    }
    html+='</div></div>';
    html+='<div class="export-bar" style="display:flex;gap:8px;margin-top:4px;padding-top:4px;border-top:1px solid var(--border);flex-wrap:wrap;align-items:center">'+
      '<span style="font-size:11px;color:var(--muted)">🕐 '+escapeHtml(detail.create_time||'')+'</span>'+
      (detail.reflection_passed?'<span style="color:var(--green);font-size:11px">✅ 质量审核通过</span>':'')+
      (detail.report?'<button class="export-btn" style="font-size:11px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--muted);cursor:pointer" onclick="copyToClipboard(`'+detail.report.replace(/`/g,'\\`').replace(/\$/g,'\\$')+'`)">📋 复制</button>':'')+
      '</div>';
    if(detail.sales_result||detail.crm_result||detail.finance_result){
      html+='<details class="trace-panel" style="margin-top:8px"><summary>🔍 查看各 Agent 分析详情</summary>';
      if(detail.sales_result){html+='<div style="margin-bottom:8px"><strong>📊 销售 Agent：</strong><pre style="font-size:11px;white-space:pre-wrap;color:var(--muted);max-height:200px;overflow-y:auto">'+escapeHtml(detail.sales_result.substring(0,3000))+'</pre></div>'}
      if(detail.crm_result){html+='<div style="margin-bottom:8px"><strong>👥 CRM Agent：</strong><pre style="font-size:11px;white-space:pre-wrap;color:var(--muted);max-height:200px;overflow-y:auto">'+escapeHtml(detail.crm_result.substring(0,3000))+'</pre></div>'}
      if(detail.finance_result){html+='<div style="margin-bottom:8px"><strong>💰 财务 Agent：</strong><pre style="font-size:11px;white-space:pre-wrap;color:var(--muted);max-height:200px;overflow-y:auto">'+escapeHtml(detail.finance_result.substring(0,3000))+'</pre></div>'}
      html+='</details>'
    }
    html+='</div><hr style="border-color:var(--border);margin:12px 0">';
    el.innerHTML+=html;
    el.scrollTop=el.scrollHeight
  }catch(e){toast('加载失败：'+e.message)}
}

// Quick question helper
function renderQuickGrid(){
  var grid=document.getElementById('quickGrid');
  if(!grid)return;
  var html='';
  var qs=getQuickQuestions(typeof _lastUser!=='undefined'?_lastUser:'');
  for(var i=0;i<qs.length;i++){
    html+='<button class=\"quick-btn\" data-q=\"'+escapeHtml(qs[i].text)+'\">'+qs[i].icon+' '+escapeHtml(qs[i].text)+'</button>';
  }
  grid.innerHTML=html;
  // Attach click handlers
  var btns=grid.querySelectorAll('.quick-btn');
  for(var j=0;j<btns.length;j++){
    btns[j].onclick=function(){quickAsk(this.getAttribute('data-q'))};
  }
  return;
}
function quickAsk(q){
  document.getElementById('question').value=q;
  document.getElementById('form').dispatchEvent(new Event('submit'))
}

// Voice input (Web Speech API)
function initVoice(){
  var btn=document.getElementById('voiceBtn');
  if(!btn)return;
  var SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRecognition){btn.style.display='none';return}
}
function toggleVoice(){
  var SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRecognition){toast('此浏览器不支持语音输入');return}
  if(voiceListening){stopVoice();return}
  voiceRecognition=new SpeechRecognition();
  voiceRecognition.lang='zh-CN';
  voiceRecognition.interimResults=false;
  voiceRecognition.maxAlternatives=1;
  voiceRecognition.onstart=function(){
    voiceListening=true;
    document.getElementById('voiceBtn').classList.add('listening');
    document.getElementById('voiceBtn').textContent='🔴';
    var toast=document.getElementById('voiceToast');
    if(toast)toast.classList.add('show')
  };
  voiceRecognition.onresult=function(e){
    var text=e.results[0][0].transcript.trim();
    if(text){
      document.getElementById('question').value=text;
      setTimeout(function(){document.getElementById('form').dispatchEvent(new Event('submit'))},300)
    }
  };
  voiceRecognition.onerror=function(e){
    if(e.error!=='no-speech'&&e.error!=='aborted'){toast('语音识别失败：'+e.error)}
    stopVoice()
  };
  voiceRecognition.onend=function(){stopVoice()};
  voiceRecognition.start()
}
function stopVoice(){
  voiceListening=false;
  var btn=document.getElementById('voiceBtn');
  if(btn){btn.classList.remove('listening');btn.textContent='🎤'}
  var toast=document.getElementById('voiceToast');
  if(toast)toast.classList.remove('show')
}

// ===== V4 Dashboard / 经营看板 =====

var _currentTab='dashboard';
var _lastUser='';

function switchTab(tab){
  _currentTab=tab;
  var dv=document.getElementById('dashboardView');
  var chat=document.getElementById('chat');
  var es=document.getElementById('emptyState');
  var qb=document.getElementById('quickBar');
  var ia=document.querySelector('.input-area');
  var tbChat=document.getElementById('tabChat');
  var tbDash=document.getElementById('tabDashboard');

  if(tab==='dashboard'){
    if(dv)dv.style.display='block';
    if(chat)chat.style.display='none';
    if(es)es.style.display='none';
    if(qb)qb.style.display='none';
    if(ia)ia.style.display='none';
    if(tbDash)tbDash.classList.add('active');
    if(tbChat)tbChat.classList.remove('active');
  } else {
    if(dv)dv.style.display='none';
    if(chat)chat.style.display='';
    if(es)es.style.display='';
    if(qb)qb.style.display='flex';
    if(ia)ia.style.display='';
    if(tbChat)tbChat.classList.add('active');
    if(tbDash)tbDash.classList.remove('active');
  }
}

async function loadDashboardOverview(){
  try{
    var r=await fetch(BASE+'/dashboard/overview',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)return;
    var d=await r.json();

    // KPI row
    var todaySales=d.today_sales||0;
    var yesterdaySales=d.yesterday_sales||0;
    var salesChange=yesterdaySales>0?((todaySales-yesterdaySales)/yesterdaySales*100).toFixed(1):0;
    var kpiHtml='';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">今日销售额</div><div class=\"kpi-val\">'+formatCurrency(todaySales)+'</div><div class=\"kpi-sub '+(salesChange>=0?'kpi-up':'kpi-down')+'\">'+(salesChange>=0?'↑':'↓')+' '+Math.abs(salesChange)+'% vs 昨日</div></div>';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">昨日销售额</div><div class=\"kpi-val\">'+formatCurrency(yesterdaySales)+'</div><div class=\"kpi-sub\" style=color:var(--muted)>基线对比</div></div>';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">近7天退款率</div><div class=\"kpi-val\">'+(d.week_refund_rate||0)+'%</div><div class=\"kpi-sub\" style=color:var(--muted)>'+(d.week_refund_rate>5?'⚠ 偏高':'正常')+'</div></div>';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">活跃门店</div><div class=\"kpi-val\">'+(d.active_stores||0)+'</div><div class=\"kpi-sub\" style=color:var(--muted)>近7天有订单</div></div>';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">会员总数</div><div class=\"kpi-val\">'+((d.total_members||0)).toLocaleString('zh-CN')+'</div><div class=\"kpi-sub\" style=color:var(--muted)>累计注册</div></div>';
    kpiHtml+='<div class=\"dash-kpi\"><div class=\"kpi-label\">区域覆盖</div><div class=\"kpi-val\">'+(d.regions||[]).length+'</div><div class=\"kpi-sub\" style=color:var(--muted)>个区域</div></div>';
    document.getElementById('dashKpiRow').innerHTML=kpiHtml;

    // 30-day trend chart
    if(typeof echarts!=='undefined'&&d.trend_dates&&d.trend_dates.length>0){
      var trendDom=document.getElementById('dashTrendChart');
      var trendChart=echarts.init(trendDom);
      trendChart.setOption({
        title:{text:'近30天销售趋势',textStyle:{color:'#f1f5f9',fontSize:14}},
        tooltip:{trigger:'axis'},
        grid:{left:'3%',right:'4%',bottom:'3%',containLabel:true},
        xAxis:{type:'category',data:d.trend_dates,axisLabel:{color:'#94a3b8',fontSize:10}},
        yAxis:{type:'value',axisLabel:{color:'#94a3b8',formatter:function(v){return v>=10000?(v/10000).toFixed(0)+'万':v}}},
        series:[{type:'line',data:d.trend_values,smooth:true,lineStyle:{color:'#6366f1',width:2},itemStyle:{color:'#6366f1'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(99,102,241,0.25)'},{offset:1,color:'rgba(99,102,241,0.02)'}]}}}]
      });
      window.addEventListener('resize',function(){trendChart.resize()});
    }

    // Regional pie chart
    if(typeof echarts!=='undefined'&&d.regions&&d.regions.length>0){
      var regionDom=document.getElementById('dashRegionChart');
      var regionChart=echarts.init(regionDom);
      var pieData=d.regions.map(function(name,i){return{name:name,value:d.region_values[i]}});
      regionChart.setOption({
        title:{text:'各区域销售占比',textStyle:{color:'#f1f5f9',fontSize:14}},
        tooltip:{trigger:'item',formatter:'{b}: {d}%'},
        legend:{orient:'vertical',right:10,top:'middle',textStyle:{color:'#94a3b8',fontSize:11}},
        series:[{type:'pie',radius:['45%','75%'],center:['40%','55%'],data:pieData,label:{color:'#94a3b8',fontSize:10},itemStyle:{borderColor:'#1e293b',borderWidth:2}}]
      });
      window.addEventListener('resize',function(){regionChart.resize()});
    }

    // Store ranking bar chart
    if(typeof echarts!=='undefined'&&d.top_stores&&d.top_stores.length>0){
      var storeDom=document.getElementById('dashStoreChart');
      var storeChart=echarts.init(storeDom);
      var names=d.top_stores.slice().reverse();
      var vals=d.top_store_values.slice().reverse();
      storeChart.setOption({
        title:{text:'门店销售额 Top 10',textStyle:{color:'#f1f5f9',fontSize:14}},
        tooltip:{trigger:'axis',formatter:function(p){return p[0].name+'<br/>销售额: '+formatCurrency(p[0].value)}},
        grid:{left:'3%',right:'8%',bottom:'3%',containLabel:true},
        xAxis:{type:'value',axisLabel:{color:'#94a3b8',formatter:function(v){return v>=10000?(v/10000).toFixed(0)+'万':v}}},
        yAxis:{type:'category',data:names,axisLabel:{color:'#94a3b8',fontSize:10}},
        series:[{type:'bar',data:vals,itemStyle:{color:{type:'linear',x:0,y:0,x2:1,y2:0,colorStops:[{offset:0,color:'#6366f1'},{offset:1,color:'#818cf8'}]}},barMaxWidth:20}]
      });
      window.addEventListener('resize',function(){storeChart.resize()});

      // Store ranking table
      var tableHtml='<table class=\"dash-store-table\"><thead><tr><th>#</th><th>门店</th><th>销售额</th></tr></thead><tbody>';
      for(var i=0;i<d.top_stores.length;i++){
        var rc=i<3?' rank-'+(i+1):'';
        tableHtml+='<tr><td><span class=\"rank-num'+rc+'\">'+(i+1)+'</span></td><td>'+escapeHtml(d.top_stores[i])+'</td><td>'+formatCurrency(d.top_store_values[i])+'</td></tr>';
      }
      tableHtml+='</tbody></table>';
      document.getElementById('dashStoreTable').innerHTML=tableHtml;
    }
  }catch(e){console.error('Dashboard load error:',e)}
}

// Dashboard snapshot (legacy - kept for greeting update)
async function loadDashboard(){
  if(!token)return;
  try{
    var r=await fetch(BASE+'/dashboard/today-summary',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)return;
    var d=await r.json();
    var gt=document.getElementById('greetingText');
    if(gt&&d.greeting&&d.username){
      gt.textContent='👋 '+d.greeting+'，'+d.username
    }
    var gs=document.getElementById('greetingSub');
    if(gs)gs.textContent='以下是今日经营快报，您也可以自由提问';
    document.getElementById('dashSales').textContent=formatCurrency(d.yesterday_sales);
    document.getElementById('dashStores').textContent=d.active_stores!==undefined?d.active_stores:'-';
    document.getElementById('dashRefund').textContent=formatPercent(d.week_refund_rate);
    document.getElementById('dashMembers').textContent=d.total_members!==undefined?d.total_members.toLocaleString('zh-CN'):'-';
    document.getElementById('dashOrders').textContent=d.recent_orders_24h!==undefined?d.recent_orders_24h:'-';
    var card=document.getElementById('dashboardCard');
    if(card)card.style.display='flex'
  }catch(e){}
}

// Share report
function shareReport(report, question){
  var summary=(report||'').replace(/\[CHART:\w+\|.+?\]/g,'').replace(/\[FOLLOWUP:.*?\]/g,'').replace(/\*\*/g,'').replace(/\*/g,'').substring(0,200).trim()+'...';
  var title=question||'企业智能经营分析报告';
  if(navigator.share){
    navigator.share({title:title,text:summary,url:window.location.href}).catch(function(){})
  }else{
    copyToClipboard(summary);
    toast('报告摘要已复制到剪贴板')
  }
}

// ===== Admin Panel =====
var _allUsers=[],_allStores=[],_allRegions=[];

async function openAdminPanel(){
  document.getElementById('adminPanel').classList.add('show');
  document.getElementById('apBackdrop').classList.add('show');
  await loadAdminData();
}

function closeAdminPanel(){
  document.getElementById('adminPanel').classList.remove('show');
  document.getElementById('apBackdrop').classList.remove('show');
  document.getElementById('apForm').style.display='none';
}

async function loadAdminData(){
  try{
    var [ur,sr]=await Promise.all([
      fetch(BASE+'/admin/users',{headers:{'Authorization':'Bearer '+token}}),
      fetch(BASE+'/admin/stores',{headers:{'Authorization':'Bearer '+token}})
    ]);
    var ud=await ur.json();var sd=await sr.json();
    _allUsers=ud.users;_allStores=sd.stores;_allRegions=sd.regions||[];
    // 确保用户列表表格结构存在（日志页可能销毁了它）
    if(!document.getElementById('apUserList')){
      document.getElementById('apContent').innerHTML='<table class=ap-table><thead><tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>门店范围</th><th>操作</th></tr></thead><tbody id=apUserList></tbody></table>';
    }
    renderUserList();
  }catch(e){console.error(e)}
}

function renderUserList(){
  var search=(document.getElementById('apSearch').value||'').toLowerCase();
  var roleFilter=document.getElementById('apRoleFilter').value;
  var filtered=_allUsers.filter(function(u){
    if(roleFilter&&u.role!==roleFilter)return false;
    if(search&&u.username.toLowerCase().indexOf(search)<0&&(u.display_name||'').toLowerCase().indexOf(search)<0)return false;
    return true;
  });
  var roleNames={admin:'管理员',regional_director:'大区总监',regional_manager:'区域经理',store_manager:'店长'};
  var badgeClass={admin:'admin-badge',regional_director:'region-badge',regional_manager:'region-badge',store_manager:'store-badge'};
  // Build store name lookup
  var storeNames={};
  for(var i=0;i<_allStores.length;i++){storeNames[_allStores[i].id]=_allStores[i].name}
  var html='';
  for(var i=0;i<filtered.length;i++){
    var u=filtered[i];
    var scope=u.scope_type==='all'?'全部':
      (u.scope_type==='region'?u.region||'':
      (u.store_ids&&u.store_ids.length>0?
        u.store_ids.map(function(sid){return '#'+sid+' '+storeNames[sid]}).join('，'):
        u.store_count+'家店'));
    html+='<tr><td>'+u.id+'</td><td>'+esc(u.username)+'</td><td>'+esc(u.display_name||'')+'</td>'+
      '<td><span class=\"badge '+(badgeClass[u.role]||'')+'\">'+(roleNames[u.role]||u.role)+'</span></td>'+
      '<td>'+scope+'</td>'+
      '<td style=white-space:nowrap><a class=\"action-link\" onclick=\"showEditUser('+u.id+')\">编辑</a>'+
      '<a class=\"action-link\" onclick=\"impersonateUser('+u.id+',\''+jsEscape(u.username)+'\')\" title=以该用户视角查询可访问门店>🔍</a>'+
      '<a class=\"action-link danger\" onclick=\"deleteUser('+u.id+',\''+jsEscape(u.username)+'\')\">删除</a></td></tr>';
  }
  document.getElementById('apUserList').innerHTML=html||'<tr><td colspan=6 style=color:var(--muted)>无匹配用户</td></tr>';
}

function openUserEditModal(title,bodyHtml,onSave){
  document.getElementById('userEditTitle').textContent=title;
  document.getElementById('userEditBody').innerHTML=bodyHtml;
  document.getElementById('userEditModal').style.display='flex';
  window._userEditOnSave=onSave;
}
function closeUserEditModal(){document.getElementById('userEditModal').style.display='none';}

function showAddUserForm(){
  var regionOpts=_allRegions.map(function(r){return '<option value=\"'+r+'\">'+r+'</option>'}).join('');
  var html='<div class=admin-form>'+
    '<label>用户名</label><input id=afUser placeholder=登录用户名 maxlength=50 autofocus>'+
    '<label>初始密码</label><input id=afPass type=password placeholder=至少6位 value=store123>'+
    '<label>显示名称</label><input id=afName placeholder=选填>'+
    '<label>角色</label><select id=afRole onchange=toggleScopeFields()>'+
      '<option value=store_manager>店长</option><option value=regional_manager>区域经理</option><option value=regional_director>大区总监</option><option value=admin>管理员</option></select>'+
    '<label>门店范围</label><select id=afScope onchange=toggleScopeFields()>'+
      '<option value=store>指定门店</option><option value=region>按区域</option><option value=all>全部门店</option></select>'+
    '<select id=afRegion style=display:none>'+regionOpts+'</select>'+
    '<div id=afStoreBox>'+buildStoreCheckboxes()+'</div>'+
    '<div style=display:flex;gap:10px;margin-top:12px>'+
      '<button class=ap-btn onclick=closeUserEditModal()>取消</button>'+
      '<button class=\"ap-btn primary\" onclick=doAddUser()>创建用户</button></div></div>';
  openUserEditModal('＋ 新增用户',html,doAddUser);
  toggleScopeFields();
}

function buildStoreCheckboxes(){
  // 按门店 ID 排序
  var sorted=_allStores.slice().sort(function(a,b){return parseInt(a.id)-parseInt(b.id)});
  var h='<div class=form-hint style=margin-bottom:6px>选择门店（可多选，支持搜索）</div>'+
    '<div class=store-dropdown id=storeDropdown>'+
      '<div class=store-dropdown-trigger onclick=toggleStoreDropdown()>'+
        '<span id=storeDropdownLabel>请选择门店...</span>'+
        '<span style=color:var(--muted);font-size:18px>▾</span>'+
      '</div>'+
      '<div class=store-dropdown-menu id=storeDropdownMenu style=display:none>'+
        '<input class=store-dropdown-search placeholder=输入门店名称或区域筛选... oninput=filterStoreOptions()>'+
        '<div class=store-dropdown-list id=storeDropdownList>';
  for(var i=0;i<sorted.length;i++){
    var s=sorted[i];
    h+='<label class=store-option data-search=\"'+esc(s.name)+' '+esc(s.region)+'\" data-id=\"'+s.id+'\">'+
      '<input type=checkbox value=\"'+s.id+'\" onchange=updateStoreSelection()> '+
      '<span class=store-opt-id>#'+s.id+'</span> '+esc(s.name)+' <span style=color:var(--muted);font-size:11px>('+esc(s.region)+')</span></label>';
  }
  h+='</div></div></div>'+
    '<div class=form-hint style=margin-top:4px id=storeCountHint>已选 0 家门店</div>';
  return h;
}

function toggleStoreDropdown(){
  var menu=document.getElementById('storeDropdownMenu');
  menu.style.display=menu.style.display==='none'?'block':'none';
  if(menu.style.display==='block'){
    document.getElementById('storeDropdownList').scrollTop=0;
    setTimeout(function(){var s=document.querySelector('.store-dropdown-search');if(s)s.focus()},100);
  }
}
function filterStoreOptions(){
  var inp=document.querySelector('.store-dropdown-search');var q=(inp?inp.value:'').toLowerCase();
  var opts=document.querySelectorAll('.store-option');
  for(var i=0;i<opts.length;i++){
    opts[i].style.display=!q||opts[i].getAttribute('data-search').indexOf(q)>=0?'flex':'none';
  }
}
function updateStoreSelection(){
  var cbs=document.querySelectorAll('#storeDropdownList input:checked');
  var ids=[];
  for(var i=0;i<cbs.length;i++)ids.push(cbs[i].value);
  var label=document.getElementById('storeDropdownLabel');
  if(ids.length===0)label.textContent='请选择门店...';
  else if(ids.length<=3)label.textContent=ids.join(', ');
  else label.textContent='已选 '+ids.length+' 家门店';
  updateStoreCount();
}

// 点击外部关闭下拉
document.addEventListener('click',function(e){
  var dd=document.getElementById('storeDropdown');
  if(dd&&!dd.contains(e.target)){
    var menu=document.getElementById('storeDropdownMenu');
    if(menu)menu.style.display='none';
  }
});

function toggleScopeFields(){
  var scope=document.getElementById('afScope');if(!scope)return;
  var v=scope.value;
  document.getElementById('afRegion').style.display=v==='region'?'block':'none';
  document.getElementById('afStoreBox').style.display=v==='store'?'block':'none';
}

function updateStoreCount(){
  var c=document.querySelectorAll('#storeDropdownList input:checked').length;
  var el=document.getElementById('storeCountHint');if(el)el.textContent='已选 '+c+' 家门店';
}

function getSelectedStoreIds(){
  var cbs=document.querySelectorAll('#storeDropdownList input:checked');
  var ids=[];
  for(var i=0;i<cbs.length;i++)ids.push(cbs[i].value);
  return ids;
}

async function doAddUser(){
  var username=document.getElementById('afUser').value.trim();
  var password=document.getElementById('afPass').value;
  var display_name=document.getElementById('afName').value.trim();
  var role=document.getElementById('afRole').value;
  var scope_type=document.getElementById('afScope').value;
  var region=scope_type==='region'?document.getElementById('afRegion').value:null;
  var store_ids=[];
  if(scope_type==='store'){store_ids=getSelectedStoreIds();}
  if(!username||!password){alert('用户名和密码不能为空');return}
  try{
    var r=await fetch(BASE+'/admin/users',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({username:username,password:password,display_name:display_name,role:role,scope_type:scope_type,region:region,store_ids:store_ids})});
    if(r.ok){closeUserEditModal();await loadAdminData()}else{var e=await r.json();alert(e.detail||'创建失败')}
  }catch(e){alert('网络错误')}
}

function showEditUser(uid){
  var u=_allUsers.find(function(x){return x.id===uid});if(!u)return;
  var regionOpts=_allRegions.map(function(r){return '<option value=\"'+r+'\"'+(u.region===r?' selected':'')+'>'+r+'</option>'}).join('');
  var html='<div class=admin-form>'+
    '<label>用户名</label><div style=padding:8px;color:var(--muted)>'+esc(u.username)+'</div>'+
    '<label>显示名称</label><input id=efName value=\"'+esc(u.display_name||'')+'\">'+
    '<label>角色</label><select id=efRole>'+
      '<option value=admin'+(u.role==='admin'?' selected':'')+'>管理员</option>'+
      '<option value=regional_director'+(u.role==='regional_director'?' selected':'')+'>大区总监</option>'+
      '<option value=regional_manager'+(u.role==='regional_manager'?' selected':'')+'>区域经理</option>'+
      '<option value=store_manager'+(u.role==='store_manager'?' selected':'')+'>店长</option></select>'+
    '<label>状态</label><select id=efActive><option value=true'+(u.is_active?' selected':'')+'>启用</option><option value=false'+(!u.is_active?' selected':'')+'>禁用</option></select>'+
    '<label>门店范围</label><select id=efScope onchange=toggleEditScope()>'+
      '<option value=store'+(u.scope_type==='store'?' selected':'')+'>指定门店</option>'+
      '<option value=region'+(u.scope_type==='region'?' selected':'')+'>按区域</option>'+
      '<option value=all'+(u.scope_type==='all'?' selected':'')+'>全部门店</option></select>'+
    '<select id=efRegion style=display:'+(u.scope_type==='region'?'block':'none')+'>'+regionOpts+'</select>'+
    '<div id=efStoreBox style=display:'+(u.scope_type==='store'?'block':'none')+'>'+buildStoreCheckboxes()+'</div>'+
    '<div style=display:flex;gap:10px;margin-top:12px>'+
      '<button class=ap-btn onclick=closeUserEditModal()>取消</button>'+
      '<button class=\"ap-btn\" onclick=resetPassword('+uid+')>重置密码</button>'+
      '<button class=\"ap-btn primary\" onclick=doEditUser('+uid+')>保存</button></div></div>';
  openUserEditModal('编辑用户: '+esc(u.username),html);
  // 预选已有的门店
  if(u.scope_type==='store'&&u.store_ids&&u.store_ids.length>0){
    setTimeout(function(){
      u.store_ids.forEach(function(sid){
        var cb=document.querySelector('#storeDropdownList input[value=\"'+sid+'\"]');
        if(cb)cb.checked=true;
      });
      updateStoreSelection();
      updateStoreCount();
    },50);
  }
}

function toggleEditScope(){
  var v=document.getElementById('efScope').value;
  document.getElementById('efRegion').style.display=v==='region'?'block':'none';
  var storeBox=document.getElementById('efStoreBox');
  if(storeBox)storeBox.style.display=v==='store'?'block':'none';
}

async function doEditUser(uid){
  var body={display_name:document.getElementById('efName').value.trim()};
  body.role=document.getElementById('efRole').value;
  body.is_active=document.getElementById('efActive').value==='true';
  body.scope_type=document.getElementById('efScope').value;
  if(body.scope_type==='region')body.region=document.getElementById('efRegion').value;
  if(body.scope_type==='store'){var ids=getSelectedStoreIds();if(ids.length>0)body.store_ids=ids;}
  try{
    var r=await fetch(BASE+'/admin/users/'+uid,{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(body)});
    if(r.ok){closeUserEditModal();await loadAdminData()}else{var e=await r.json();alert(e.detail||'保存失败')}
  }catch(e){alert('网络错误')}
}

async function deleteUser(uid,uname){
  if(!confirm('确定删除用户 '+uname+' 吗？此操作不可撤销。'))return;
  try{
    var r=await fetch(BASE+'/admin/users/'+uid,{method:'DELETE',headers:{'Authorization':'Bearer '+token}});
    if(r.ok){alert('已删除');loadAdminData()}else{var e=await r.json();alert(e.detail||'删除失败')}
  }catch(e){alert('网络错误')}
}

async function resetPassword(uid){
  var np=prompt('输入新密码（至少6位）：','123456');
  if(!np||np.length<6)return;
  try{
    var r=await fetch(BASE+'/admin/users/'+uid+'/reset-password',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({new_password:np})});
    if(r.ok){alert('密码已重置')}else{var e=await r.json();alert(e.detail||'重置失败')}
  }catch(e){alert('网络错误')}
}

function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

async function impersonateUser(uid, uname){
  if(!confirm('将以 '+uname+' 的权限查询"我可以访问的门店列表"，确认？'))return;
  try{
    var r=await fetch(BASE+'/admin/impersonate/'+uid,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({question:'查询我可以访问的门店列表'})});
    var d=await r.json();
    var storeCount=d.store_count==='全部'?'全部门店':d.store_count+' 家门店';
    alert('👤 '+d.target_user+' 的数据范围：'+storeCount+'\n\n'+(d.report||'无报告').slice(0,500));
  }catch(e){alert('模拟失败: '+e)}
}

async function loadErrorLog(){
  try{
    var r=await fetch(BASE+'/monitor/errors?days=7&limit=50',{headers:{'Authorization':'Bearer '+token}});
    var d=await r.json();
    var html='<div style=display:flex;justify-content:space-between;align-items:center;margin-bottom:12px><h3 style=margin:0>📋 Agent 错误日志（近7天）</h3><button class=\"ap-btn\" onclick=loadAdminData()>← 返回用户列表</button></div>';
    html+='<div style=display:flex;gap:16px;margin-bottom:12px>';
    for(var agent in d.by_agent){
      html+='<span style=font-size:12px;color:var(--muted)><b style=color:var(--red)>'+agent+'</b>: '+d.by_agent[agent]+'次</span>';
    }
    html+='</div><table class=ap-table><thead><tr><th>时间</th><th>Agent</th><th>错误信息</th><th>耗时</th></tr></thead><tbody>';
    for(var i=0;i<d.errors.length;i++){
      var e=d.errors[i];
      html+='<tr><td style=white-space:nowrap;font-size:11px>'+e.time.slice(11,19)+'</td>'+
        '<td><span class=\"badge\" style=background:rgba(239,68,68,.15);color:var(--red)>'+esc(e.agent)+'</span></td>'+
        '<td style=font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis>'+esc(e.error)+'</td>'+
        '<td style=font-size:11px>'+e.elapsed_ms+'ms</td></tr>';
    }
    html+='</tbody></table>';
    document.getElementById('apContent').innerHTML=html;
  }catch(e){console.error(e)}
}

// Show admin button if user is admin
async function checkAdmin(){
  try{
    var r=await fetch(BASE+'/admin/users',{headers:{'Authorization':'Bearer '+token}});
    if(r.ok)document.getElementById('adminBtn').style.display='block';
  }catch(e){}
}

// V4: 从 localStorage 恢复会话（页面刷新时跳过登录）
async function restoreSession(username){
  // 先隐藏欢迎页，显示主界面
  var intro=document.getElementById('introOverlay');
  if(intro){intro.style.display='none'}
  document.getElementById('loginOverlay').style.display='none';
  document.getElementById('status').textContent='● '+username+' 已连接';
  document.getElementById('logoutBtn').style.display='block';
  // 用 dashboard API 验证 token 是否仍然有效
  try{
    var r=await fetch(BASE+'/dashboard/today-summary',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)throw new Error('token expired');
  }catch(e){
    // Token 失效，清除并显示欢迎页
    localStorage.removeItem('eia_token');
    localStorage.removeItem('eia_username');
    token='';
    document.getElementById('status').textContent='● 就绪';
    document.getElementById('logoutBtn').style.display='none';
    if(intro){intro.style.display='flex'}
    return;
  }
  // Token 有效：恢复完整会话
  var rl={'admin':'总部管理员','zhangsan':'区域经理-华东','lisi':'店长-旗舰店040'};
  var rs={'admin':'全部权限','zhangsan':'分析+历史+周报+预警查看','lisi':'仅分析+查看历史'};
  document.getElementById('roleName').textContent=rl[username]||username;
  document.getElementById('roleScope').textContent=rs[username]||'';
  document.getElementById('roleInfo').style.display='block';
  if(username==='admin')document.getElementById('adminBtn').style.display='block';
  _lastUser=username;
  renderQuickGrid(username);
  initVoice();
  loadHistory();
  await newSession();
  document.getElementById('tabBar').style.display='flex';
  switchTab('dashboard');
  loadDashboardOverview();
}

// V4: 退出登录
async function logout(){
  try{
    await fetch(BASE+'/auth/logout',{method:'POST',headers:{'Authorization':'Bearer '+token}});
  }catch(e){}
  localStorage.removeItem('eia_token');
  localStorage.removeItem('eia_username');
  token='';
  location.reload();
}

// Init — V4: 欢迎页优先，但已有 token 则自动恢复会话
(async function(){
  var savedToken=localStorage.getItem('eia_token');
  var savedUser=localStorage.getItem('eia_username');
  if(savedToken&&savedUser){
    // 有已存储的 token，跳过欢迎页和登录，直接恢复会话
    token=savedToken;
    await restoreSession(savedUser);
    return;
  }
  // 首次访问：显示欢迎页
  document.getElementById('loginOverlay').style.display = 'none';
  renderQuickGrid();
  initVoice();
  initIntroParticles();
})();

// V4: 欢迎页粒子动画初始化
function initIntroParticles(){
  var container = document.getElementById('introParticles');
  if(!container)return;
  for(var i=0;i<30;i++){
    var p=document.createElement('div');
    p.className='intro-particle';
    p.style.left=Math.random()*100+'%';
    p.style.animationDuration=(8+Math.random()*12)+'s';
    p.style.animationDelay=Math.random()*8+'s';
    container.appendChild(p);
  }
}

// V4: 登录弹窗先出现在欢迎页背后 → 欢迎页淡出
function transitionToLogin(){
  var intro=document.getElementById('introOverlay');
  showLogin();  // 立刻显示登录弹窗（z-index:9999 < intro 的 10000，被遮在背后）
  intro.style.opacity='0';
  intro.style.transition='opacity 0.5s ease';
  setTimeout(function(){
    intro.style.display='none';
  },500);
}
