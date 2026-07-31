/* Enterprise Insight Agent V4 — Frontend */
var token=null;
var _currentTab='dashboard',_lastUser='',_dashCharts={},_currentRole='default';(window._dashCharts=_dashCharts);
var _monitorDays=30,_monitorPreset='30',_monitorStartDate='',_monitorEndDate='';
var _allUsers=[],_allStores=[],_allRegions=[];
var sessionId=null,lastRecordId=null,pendingFeedback=null,_lastReportText='',_lastQuestionText='';
var dismissedIds=(function(){try{return new Set(JSON.parse(localStorage.getItem('eia_dismissed')||'[]'));}catch(e){return new Set();}})();
var hiddenIds=new Set(),_isAnalyzing=false,_abortController=null,_sseParseErrs=0;
var voiceListening=false,voiceRecognition=null;
var SEMOJIS={supervisor:'🧠',sales_agent:'📊',crm_agent:'👥',finance_agent:'💰',inventory_agent:'📦',supply_chain_agent:'🚚',aggregator:'📊',chart_advisor:'📈',report_agent:'📝',reflection_agent:'✅',save_memory:'📥'};

/* ── 前端缓存：内存 + sessionStorage（刷新后秒级恢复看板数据） ── */
var _cache={};
function _cachedFetch(key,url,ttlMs){
  var now=Date.now();
  // 内存缓存
  if(_cache[key]&&now-_cache[key].time<ttlMs)return Promise.resolve(_cache[key].data);
  // sessionStorage 缓存（页面刷新后恢复）
  if(key==='dashboard'&&!_cache[key]){
    try{var ss=sessionStorage.getItem('eia_dash');
      if(ss){var p=JSON.parse(ss);if(now-p.time<60000){_cache[key]=p;return Promise.resolve(p.data)}}
    }catch(e){}
  }
  return fetch(url,{headers:{'Authorization':'Bearer '+token}}).then(function(r){
    if(!r.ok){_cache[key]=null;return null}
    return r.json().then(function(d){
      _cache[key]={data:d,time:now};
      if(key==='dashboard')try{sessionStorage.setItem('eia_dash',JSON.stringify(_cache[key]))}catch(e){}
      return d
    })
  });
}
function _clearCache(key){delete _cache[key]}

function updateNavActive(t){document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(e){e.classList.toggle('active',e.getAttribute('data-tab')===t);});}

function switchTab(tab){
  updateNavActive(tab);
  ['dashboardView','monitorView','historyView','chat','inputArea','quickBar'].forEach(function(id){
    var el=document.getElementById(id);
    if(id==='dashboardView')el.style.display=tab==='dashboard'?'block':'none';
    else if(id==='monitorView')el.style.display=tab==='monitor'?'flex':'none';
    else if(id==='historyView')el.style.display=tab==='history'?'block':'none';
    else if(id==='chat')el.style.display=tab==='analysis'?'flex':'none';
    else if(id==='inputArea')el.style.display=tab==='analysis'?'block':'none';
    else if(id==='quickBar')el.style.display=tab==='analysis'?'flex':'none';
  });
  var es=document.getElementById('emptyState');
  if(es)es.style.display=(tab==='analysis'&&!document.getElementById('chat').querySelector('.msg'))?'block':'none';
  _currentTab=tab;
  if(tab==='dashboard')loadDashboard();
  if(tab==='monitor')loadMonitorOverview();
  if(tab==='history')loadHistoryView();
}

function initIntroParticles(){
  var c=document.getElementById('introParticles');
  if(!c)return;
  for(var i=0;i<20;i++){
    var p=document.createElement('div');
    p.style.cssText='position:absolute;width:'+(2+Math.random()*3)+'px;height:'+(2+Math.random()*3)+'px;background:rgba(99,102,241,'+(.2+Math.random()*.3)+');border-radius:50%;left:'+Math.random()*100+'%;top:'+Math.random()*100+'%;animation:floatUp '+(6+Math.random()*8)+'s linear infinite;animation-delay:'+Math.random()*5+'s';
    c.appendChild(p);
  }
}
function transitionToLogin(){
  var o=document.getElementById('introOverlay'),l=document.getElementById('loginOverlay');
  if(o)o.style.opacity='0';
  setTimeout(function(){if(o)o.style.display='none';if(l)l.style.display='flex';},500);
}
function showLogin(){document.getElementById('introOverlay').style.display='none';document.getElementById('loginOverlay').style.display='flex';}
function togglePassword(){var p=document.getElementById('loginPass');p.type=p.type==='password'?'text':'password';}

async function doLogin(e){
  e.preventDefault();
  var u=document.getElementById('loginUser').value.trim(),p=document.getElementById('loginPass').value;
  if(!u||!p){toast('请输入用户名和密码');return;}
  var btn=document.getElementById('loginBtn');btn.disabled=true;btn.textContent='登录中...';
  try{
    var r=await fetch(BASE+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    var d=await r.json();
    if(d.access_token){
      token=d.access_token;localStorage.setItem('eia_token',token);localStorage.setItem('eia_user',u);
      document.getElementById('loginOverlay').style.display='none';await restoreSession(u);
    }else{
      var errEl=document.getElementById('loginError');
      if(errEl){
        errEl.textContent=d.detail||'用户名或密码错误';
        errEl.style.display='block';
      }else toast('用户名或密码错误');
    }
  }catch(e){toast('网络错误','error');}
  finally{btn.disabled=false;btn.textContent='登录';}
}

async function restoreSession(username){
  var saved=localStorage.getItem('eia_token');
  if(!saved){showLogin();return;}
  token=saved;var u=username||localStorage.getItem('eia_user')||'admin';
  // V4.5: 显示界面，再异步加载角色信息（内联脚本已确认 token 有效）
  document.getElementById('introOverlay').style.display='none';
  document.getElementById('loginOverlay').style.display='none';
  document.getElementById('app').style.display='flex';
  document.getElementById('sidebarNav').style.display='flex';
  document.getElementById('userMenu').style.display='block';
  document.getElementById('userMenuName').textContent=u;
  document.getElementById('userAvatar').textContent=u.charAt(0).toLowerCase();
  document.getElementById('dashUser').textContent=u;_lastUser=u;
  // 异步加载角色信息（复用此 API 结果，替代 checkAdmin 的重复请求）
  fetch(BASE+'/admin/users',{headers:{'Authorization':'Bearer '+token}}).then(function(_r){
    if(_r.status===401){localStorage.removeItem('eia_token');localStorage.removeItem('eia_user');token='';showLogin();return;}
    if(!_r.ok)return;_r.json().then(function(_d){
      var _me=_d.users&&_d.users.find(function(x){return x.username===u;});
      if(!_me)return;
      document.getElementById('dropdownRole').textContent=_me.role==='admin'?'管理员':_me.role==='regional_manager'?'区域经理':'店长';
      document.getElementById('dropdownScope').textContent=_me.scope_type==='all'?'全部门店':_me.region||_me.store_ids?(_me.store_ids||[]).length+'家门店':'—';
      _currentRole=_me.role||'default';
      var mn=document.getElementById('monitorNavBtn');
      if(mn)mn.style.display=_me.role==='admin'?'':'none';
      var an=document.getElementById('adminNavBtn');
      if(an)an.style.display=_me.role==='admin'?'':'none';
    });
  }).catch(function(){});
  try{renderQuickGrid();renderEmptyStats();switchTab('dashboard');loadSessionInfo();
    if(!localStorage.getItem('eia_first_visit')){
      localStorage.setItem('eia_first_visit','1');
      setTimeout(function(){
        toast('💡 尝试输入“各门店销售额排名”或点击快捷按钮开始分析');
      },1500);
    }
  }catch(e){console.warn("Catch:",e);}
}

async function logout(){
  if(token)try{await fetch(BASE+'/auth/logout',{method:'POST',headers:{'Authorization':'Bearer '+token}});}catch(e){}
  token='';localStorage.removeItem('eia_token');localStorage.removeItem('eia_user');
  document.getElementById('app').style.display='none';
  document.getElementById('sidebarNav').style.display='none';
  document.getElementById('userMenu').style.display='none';
  document.getElementById('adminNavBtn').style.display='none';
  document.getElementById('monitorNavBtn').style.display='none';
  document.getElementById('userMenuDropdown').classList.remove('show');
  showLogin();
}

async function checkAdmin(){
  var btn=document.getElementById('adminNavBtn');
  if(!btn)return;
  if(!token){btn.style.display='none';return;}
  try{var r=await fetch(BASE+'/admin/users',{headers:{'Authorization':'Bearer '+token}});btn.style.display=r.ok?'':'none';}catch(e){btn.style.display='none';}
}

function toggleUserMenu(){document.getElementById('userMenuDropdown').classList.toggle('show');}
document.addEventListener('click',function(e){
  var m=document.getElementById('userMenu'),d=document.getElementById('userMenuDropdown');
  if(m&&!m.contains(e.target))d.classList.remove('show');
});

/* 事件委托：替代内联 onclick，配合 CSP */
document.addEventListener('click',function(e){
  var t=e.target;
  // 能力卡片
  var card=t.closest('.cap-card[data-question]');
  if(card){fillQuestion(card.getAttribute('data-question'));return;}
  // 快捷提问按钮
  var qb=t.closest('.quick-btn[data-question]');
  if(qb){quickAsk(qb.getAttribute('data-question'));return;}
  // 追问按钮（LLM 生成内容，需走委托避免 XSS）
  var fb=t.closest('.followup-btn[data-action="ask-followup"]');
  if(fb){askFollowup(fb.getAttribute('data-question'));return;}
  // 管理面板表格操作
  var a=t.closest('[data-action]');
  if(a){
    var tr=a.closest('tr[data-uid]');
    if(tr){
      var uid=parseInt(tr.getAttribute('data-uid')),action=a.getAttribute('data-action');
      if(action==='edit')showEditUser(uid);
      else if(action==='delete')deleteUser(uid,a.getAttribute('data-uname'));
      else if(action==='reset-pw')resetPassword(uid);
      else if(action==='impersonate')impersonateUser(uid,a.getAttribute('data-uname'));
    }
    return;
  }
});

/* Dashboard */
async function loadDashboard(){
  if(!token)return;
  try{
    var d=await _cachedFetch('dashboard', BASE+'/dashboard/overview', 30000);
    if(!d)return;
    document.getElementById('dashGreeting').textContent=d.greeting||'';
    document.getElementById('dashUser').textContent=localStorage.getItem('eia_user')||'';
    // V4.5: 数据时效指示器
    var fi=document.getElementById('dashFreshness');
    if(d.cached_at){
      var t=new Date(d.cached_at*1000);
      var ts=t.getHours().toString().padStart(2,'0')+':'+t.getMinutes().toString().padStart(2,'0');
      if(fi)fi.textContent='数据更新于 '+ts;
      else{
        var el=document.createElement('span');el.id='dashFreshness';el.style.cssText='font-size:11px;color:var(--muted);margin-left:8px';
        el.textContent='数据更新于 '+ts;
        document.getElementById('dashUser').parentNode.appendChild(el);
      }
    }
    var tS=d.today_sales||0,yS=d.yesterday_sales||0;
    var sc=yS>0?((tS-yS)/yS*100).toFixed(1):0,up=sc>=0;
    document.getElementById('dashKpis').innerHTML=
      '<div class="dash-kpi"><div class="kpi-label">今日销售额</div><div class="kpi-val" id="kT">—</div><div class="kpi-sub '+(up?'kpi-up':'kpi-down')+'">'+(up?'↑':'↓')+' '+Math.abs(sc)+'% vs 昨日</div></div>'+
      '<div class="dash-kpi"><div class="kpi-label">昨日销售额</div><div class="kpi-val" id="kY">—</div><div class="kpi-sub" style="color:var(--muted)">基线对比</div></div>'+
      '<div class="dash-kpi"><div class="kpi-label">退款率（近7天）</div><div class="kpi-val" id="kR">—</div><div class="kpi-sub '+(d.week_refund_rate>5?'kpi-down':'kpi-up')+'">'+(d.week_refund_rate>5?'⚠️ 偏高':'✅ 正常')+'</div></div>'+
      '<div class="dash-kpi"><div class="kpi-label">活跃门店</div><div class="kpi-val" id="kA">—</div><div class="kpi-sub" style="color:var(--muted)">近7天有订单</div></div>'+
      '<div class="dash-kpi"><div class="kpi-label">会员总数</div><div class="kpi-val" id="kM">—</div><div class="kpi-sub" style="color:var(--muted)">累计注册</div></div>'+
      '<div class="dash-kpi"><div class="kpi-label">近24小时订单</div><div class="kpi-val" id="kO">—</div><div class="kpi-sub" style="color:var(--muted)">笔</div></div>';
    setTimeout(function(){
      var ka=function(id,t){var e=document.getElementById(id);if(!e)return;var st=null;
        (function fn(ts){if(!st)st=ts;var p=Math.min((ts-st)/350,1),v=Math.round(t*p);
        if(typeof t==='number'&&t>=10000)e.textContent='¥'+(v/10000).toFixed(1)+(v>=10000?'万':'');
        else if(typeof t==='number')e.textContent='¥'+v.toLocaleString();else e.textContent=v;
        if(p<1)requestAnimationFrame(fn);})(performance.now());};
      var kp=function(id,v){var e=document.getElementById(id);if(e)e.textContent=formatPercent(v);};
      var kd=function(id,v){var e=document.getElementById(id);if(e)e.textContent=(v||'—');};
      ka('kT',tS);ka('kY',yS);kp('kR',d.week_refund_rate);kd('kA',d.active_stores);kd('kM',d.total_members.toLocaleString());kd('kO',d.recent_orders_24h);
    },100);
    onEChartsReady(function(echarts){
    var th=echartsTheme();
    if(!_dashCharts.t)_dashCharts.t=echarts.init(document.getElementById('dashTrendChart'));
    _dashCharts.t.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
      grid:{left:50,right:20,bottom:30,top:10},
      xAxis:{type:'category',data:d.trend_dates,axisLabel:{color:'#94a3b8',fontSize:9,rotate:35},axisLine:{lineStyle:{color:'#334155'}},axisTick:{show:false}},
      yAxis:{type:'value',axisLabel:{color:'#94a3b8',fontSize:9,formatter:function(v){return v>=10000?(v/10000).toFixed(0)+'万':v}},splitLine:{lineStyle:{color:'rgba(51,65,85,0.5)'}}},
      series:[{type:'line',data:d.trend_values,smooth:true,symbol:'circle',symbolSize:4,lineStyle:{width:2,color:th.color[0]},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:th.color[0]+'4d'},{offset:1,color:th.color[0]+'00'}]}}}]});
    if(!_dashCharts.s)_dashCharts.s=echarts.init(document.getElementById('dashStoreChart'));
    _dashCharts.s.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis'},
      grid:{left:110,right:20,bottom:20,top:10},
      xAxis:{type:'value',axisLabel:{color:'#94a3b8',fontSize:9,formatter:function(v){return v>=10000?(v/10000).toFixed(0)+'万':v}},splitLine:{lineStyle:{color:'rgba(51,65,85,0.5)'}}},
      yAxis:{type:'category',data:(d.top_stores||[]).slice().reverse(),axisLabel:{color:'#f1f5f9',fontSize:10},axisLine:{lineStyle:{color:'#334155'}},axisTick:{show:false}},
      series:[{type:'bar',data:(d.top_store_values||[]).slice().reverse(),itemStyle:{color:new echarts.graphic.LinearGradient(0,0,1,0,[{offset:0,color:'rgba(99,102,241,0.6)'},{offset:1,color:th.color[0]}])},barMaxWidth:20,label:{show:true,position:'right',formatter:function(p){return formatAxisValue(p.value);},color:'#c7d2fe',fontSize:10}}]});
    var regs=(d.regions||[]).map(function(n,i){return{name:n,value:(d.region_values||[])[i]||0};}),regSel={};
    regs.forEach(function(r){regSel[r.name]=true;});
    var rc=document.getElementById('dashRegionChart');
    function dr(){
      var f=regs.filter(function(r){return regSel[r.name];});
      if(!_dashCharts.r)_dashCharts.r=echarts.init(rc);
      _dashCharts.r.setOption({backgroundColor:'transparent',tooltip:{trigger:'item'},series:[{type:'pie',radius:['35%','60%'],data:f,label:{color:'#f1f5f9',fontSize:11,formatter:'{b}: {d}%'},itemStyle:{borderColor:'transparent',borderWidth:2},color:th.color}]});
    }
    var fb=rc.parentNode.querySelector('.rf');
    if(!fb){
      fb=document.createElement('div');fb.className='rf';fb.style.cssText='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px';
      regs.forEach(function(r){
        var b=document.createElement('button');b.textContent=r.name;
        b.style.cssText='padding:3px 10px;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:11px;cursor:pointer';
        b.onclick=function(){regSel[r.name]=!regSel[r.name];dr();fb.querySelectorAll('button').forEach(function(x){x.style.opacity=regSel[x.textContent]?'1':'0.35';});};
        fb.appendChild(b);
      });
      rc.parentNode.insertBefore(fb,rc);
    }
    dr();
    // V4.5: 退款率 Top 10 图表
    if(d.top_refund_stores&&d.top_refund_stores.length){
      if(!_dashCharts.rf)_dashCharts.rf=echarts.init(document.getElementById('dashRefundChart'));
      var rfData=(d.top_refund_stores||[]).map(function(n,i){return{name:n,value:d.top_refund_values[i]||0};}).sort(function(a,b){return a.value-b.value;});
      _dashCharts.rf.setOption({backgroundColor:'transparent',tooltip:{trigger:'axis',formatter:function(p){return p[0].name+'<br/>退款率: '+p[0].value+'%';}},
        grid:{left:110,right:30,bottom:20,top:10},
        xAxis:{type:'value',axisLabel:{color:'#94a3b8',fontSize:9,formatter:function(v){return v+'%';}},splitLine:{lineStyle:{color:'rgba(51,65,85,0.5)'}}},
        yAxis:{type:'category',data:rfData.map(function(d){return d.name;}),axisLabel:{color:'#f1f5f9',fontSize:10},axisLine:{lineStyle:{color:'#334155'}},axisTick:{show:false}},
        series:[{type:'bar',data:rfData.map(function(d){return d.value;}),itemStyle:{color:new echarts.graphic.LinearGradient(0,0,1,0,[{offset:0,color:'rgba(239,68,68,0.3)'},{offset:1,color:'#ef4444'}])},barMaxWidth:20,label:{show:true,position:'right',formatter:function(p){return p.value+'%';},color:'#fca5a5',fontSize:10,fontWeight:600}}]});
    }
    });
  }catch(e){toast('看板加载失败','error');console.warn(e);}
}

/* Admin */
async function openAdminPanel(){
  document.getElementById('adminPanel').classList.add('show');
  document.getElementById('apBackdrop').classList.add('show');
  await loadAdminData();
}
function closeAdminPanel(){
  document.getElementById('adminPanel').classList.remove('show');
  document.getElementById('apBackdrop').classList.remove('show');
}
async function loadAdminData(force){
  if(!force){
    var cached=_cache['admin'];
    if(cached&&Date.now()-cached.time<300000){
      _allUsers=cached.data.users;
      _allStores=cached.data.stores;
      _allRegions=cached.data.regions;
      renderUserList();return;
    }
  }
  try{
    var [uR,sR]=await Promise.all([
      fetch(BASE+'/admin/users',{headers:{'Authorization':'Bearer '+token}}),
      fetch(BASE+'/admin/stores',{headers:{'Authorization':'Bearer '+token}})
    ]);
    if(!uR.ok)return;
    _allUsers=(await uR.json()).users;
    var stores=[],regions=[];
    if(sR.ok){var d=await sR.json();stores=d.stores||d;regions=d.regions||[];}
    _allStores=stores;_allRegions=regions;
    _cache['admin']={data:{users:_allUsers,stores:_allStores,regions:_allRegions},time:Date.now()};
    renderUserList();
  }catch(e){console.warn("Catch:",e);}
}
function renderUserList(){
  var s=(document.getElementById('apSearch')||{}).value||'',rf=(document.getElementById('apRoleFilter')||{}).value||'';
  var f=_allUsers.filter(function(u){if(rf&&u.role!==rf)return false;return!s||u.username.indexOf(s)>-1||(u.role||'').indexOf(s)>-1||(u.scope_type||'').indexOf(s)>-1;});
  var sm={};(_allStores||[]).forEach(function(s){sm[String(s.id)]=s.name||s.store_name||'';});
  function sn(ids){if(!ids||!ids.length)return '';return ids.map(function(id){return sm[String(id)]||'#'+id;}).filter(Boolean).join('、');}
  var html=f.map(function(u){
    var sids=u.store_ids||u.stores||[],st=u.scope_type==='all'?'全部门店':u.scope_type==='region'?u.region||'区域':sids.length>3?sids.length+'家门店':(sn(sids)||'—');
    return '<tr data-uid="'+u.id+'"><td>'+u.id+'</td><td>'+esc(u.username)+'</td><td>'+(u.role==='admin'?'<span class="badge admin-badge">管理员</span>':u.role==='regional_manager'?'<span class="badge region-badge">区域经理</span>':'<span class="badge store-badge">店长</span>')+'</td><td>'+st+'</td><td>'+(u.is_active===false?'<span class="badge inactive">禁用</span>':'<span class="badge admin-badge">启用</span>')+'</td><td><a class="action-link" data-action="edit">编辑</a><a class="action-link" data-action="impersonate" data-uname="'+jsEscape(u.username)+'">模拟</a><a class="action-link danger" data-action="delete" data-uname="'+jsEscape(u.username)+'">删除</a><a class="action-link" data-action="reset-pw">重置密码</a></td></tr>';
  }).join('');
  document.getElementById('apUserList').innerHTML=html;
}
function showAddUserForm(){
  var h='<div class="admin-form"><label>用户名<input id="nU" class="login-input"></label><label>密码<input id="nP" class="login-input" type="password"></label><label>角色<select id="nR" onchange="ts()"><option value="store_manager">店长</option><option value="regional_manager">区域经理</option><option value="admin">管理员</option></select></label><div id="sf" style="display:none"><div id="ss"><label>门店</label><div id="sc" style="max-height:200px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px"></div></div><div id="rs" style="display:none"><label>区域</label><select id="nRg" class="login-input"></select></div></div></div>';
  openUserEditModal('添加用户',h,'doAddUser');ts();
}
function ts(){
  var r=document.getElementById('nR').value,sf=document.getElementById('sf');
  if(!sf)return;
  sf.style.display=(r==='store_manager'||r==='regional_manager')?'block':'none';
  var ss=document.getElementById('ss');if(ss)ss.style.display=r==='store_manager'?'block':'none';
  var rs2=document.getElementById('rs');if(rs2)rs2.style.display=r==='regional_manager'?'block':'none';
  if(r==='store_manager'){
    var sc=document.getElementById('sc');
    if(sc)sc.innerHTML=(_allStores||[]).map(function(s){return '<label style="display:block;padding:3px 4px;font-size:12px;cursor:pointer"><input type="checkbox" value="'+s.id+'" class="cb"> '+esc(s.name||'门店'+s.id)+'</label>';}).join('');
  }
  if(r==='regional_manager'&&rs2){var sel=rs2.querySelector('select');if(sel&&!sel.options.length)(_allRegions||[]).sort().forEach(function(r){sel.innerHTML+='<option value="'+esc(r)+'">'+esc(r)+'</option>';});}
}
function openUserEditModal(title,body,onSave){
  document.getElementById('userEditModal').style.display='flex';
  document.getElementById('userEditBody').innerHTML=body;
  document.getElementById('userEditTitle').textContent=title;
  // 不关闭弹窗——由 onSave 函数自己控制关闭时机
  document.getElementById('userEditSaveBtn').onclick=function(){window[onSave]();};
}
function closeUserEditModal(){document.getElementById('userEditModal').style.display='none';var ee=document.getElementById('userEditError');if(ee)ee.style.display='none';}
async function doAddUser(){
  var u=document.getElementById('nU').value.trim(),p=document.getElementById('nP').value,r=document.getElementById('nR').value;
  var errEl=document.getElementById('userEditError');
  if(!errEl){
    errEl=document.createElement('div');errEl.id='userEditError';
    errEl.style.cssText='color:var(--semantic-error);font-size:12px;margin-bottom:12px;padding:8px 12px;background:rgba(239,68,68,.08);border-radius:6px;display:none';
    var body=document.getElementById('userEditBody');
    if(body)body.insertBefore(errEl,body.firstChild);
  }
  if(!u||!p){errEl.textContent='用户名和密码不能为空';errEl.style.display='block';return;}
  if(u.length<2){errEl.textContent='用户名至少需要2个字符';errEl.style.display='block';return;}
  if(p.length<6){errEl.textContent='密码至少需要6位';errEl.style.display='block';return;}
  errEl.style.display='none';
  var b={username:u,password:p,role:r};
  if(r==='store_manager'){var ids=Array.from(document.querySelectorAll('.cb:checked')).map(function(c){return c.value;});if(ids.length)b.store_ids=ids;}
  if(r==='regional_manager'){var rg=document.getElementById('nRg');if(rg)b.region=rg.value;}
  try{
    var res=await fetch(BASE+'/admin/users',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(b)});
    if(res.ok){closeUserEditModal();_clearCache("admin");await loadAdminData(true);}
    else{
      var ed=await res.json();
      var msg=typeof ed.detail==='string'?ed.detail:(ed.detail&&ed.detail[0]&&ed.detail[0].msg)||'';
      var cn={'String should have at least 2 characters':'用户名至少需要2个字符','String should have at least 6 characters':'密码至少需要6位','Input should be a valid string':'请输入有效的字符串'};
      errEl.textContent=cn[msg]||msg||'创建失败，请检查输入';
      errEl.style.display='block';
    }
  }catch(e){errEl.textContent='网络错误，请重试';errEl.style.display='block';}
}
function showEditUser(uid){
  var u=_allUsers.find(function(x){return x.id===uid;});if(!u)return;
  window._editUid=uid;
  var st=u.scope_type||'店';
  var h='<div style="padding:4px 0">'+
    // 基本信息
    '<div style="font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border-subtle)">👤 基本信息</div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px">'+
      '<div><label style="display:block;font-size:11px;color:var(--muted);margin-bottom:3px">用户名</label><div style="padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;font-weight:600">'+esc(u.username)+'</div></div>'+
      '<div><label style="display:block;font-size:11px;color:var(--muted);margin-bottom:3px">状态</label><select id="eA" style="width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none"><option value="1"'+(u.is_active!==false?' selected':'')+'>✅ 启用</option><option value="0"'+(u.is_active===false?' selected':'')+'>❌ 禁用</option></select></div>'+
    '</div>'+
    // 角色与权限
    '<div style="font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border-subtle)">🔑 角色与权限</div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px">'+
      '<div><label style="display:block;font-size:11px;color:var(--muted);margin-bottom:3px">角色</label><select id="eR" onchange="es()" style="width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none"><option value="store_manager"'+(u.role==='store_manager'?' selected':'')+'>🏪 店长</option><option value="regional_manager"'+(u.role==='regional_manager'?' selected':'')+'>🌍 区域经理</option><option value="admin"'+(u.role==='admin'?' selected':'')+'>👨‍💼 管理员</option></select></div>'+
      '<div><label style="display:block;font-size:11px;color:var(--muted);margin-bottom:3px">数据范围</label><select id="eSct" onchange="es()" style="width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none"><option value="all"'+(st==='all'?' selected':'')+'>🌐 全部门店</option><option value="region"'+(st==='region'?' selected':'')+'>🌍 按区域</option><option value="store"'+(st==='store'?' selected':'')+'>🏪 按门店</option></select></div>'+
    '</div>'+
    '<div id="eReg"'+(st!=='region'?' style="display:none"':'')+' style="margin-bottom:18px">'+
      '<label style="display:block;font-size:11px;color:var(--muted);margin-bottom:3px">所属区域</label>'+
      '<select id="eRg" style="width:100%;padding:9px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none">'+(_allRegions||[]).sort().map(function(r){return '<option value="'+esc(r)+'"'+(u.region===r?' selected':'')+'>'+esc(r)+'</option>';}).join('')+'</select>'+
    '</div>'+
    '<div id="eStr"'+(st!=='store'?' style="display:none"':'')+' style="margin-bottom:4px">'+
      '<label style="display:block;font-size:11px;color:var(--muted);margin-bottom:6px">分配门店</label>'+
      '<div style="max-height:220px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:6px;display:grid;grid-template-columns:1fr 1fr;gap:2px">'+(_allStores||[]).map(function(s){return '<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;border-radius:6px;font-size:12px;cursor:pointer;transition:background .1s"><input type="checkbox" value="'+s.id+'" class="ecb"'+(u.store_ids&&u.store_ids.indexOf(String(s.id))>=0?' checked':'')+' style="accent-color:var(--accent);width:14px;height:14px"> <span style="color:var(--text)">'+esc(s.name||'门店'+s.id)+'</span></label>';}).join('')+'</div>'+
    '</div></div>';
  openUserEditModal('编辑用户',h,'doEditUser');
  es();
}
function es(){
  var role=document.getElementById('eR').value;
  var scopeSec=document.getElementById('eScope');
  if(!scopeSec)return;
  scopeSec.style.display=role==='admin'?'none':'block';
  if(role==='admin')return;
  var sct=document.getElementById('eSct').value;
  var reg=document.getElementById('eReg');
  var str=document.getElementById('eStr');
  if(reg)reg.style.display=sct==='region'?'block':'none';
  if(str)str.style.display=sct==='store'?'block':'none';
}
async function doEditUser(uid){
  uid=uid||window._editUid;if(!uid)return;
  var errEl=document.getElementById('userEditError');
  if(!errEl){
    errEl=document.createElement('div');errEl.id='userEditError';
    errEl.style.cssText='color:var(--semantic-error);font-size:12px;margin-bottom:12px;padding:8px 12px;background:rgba(239,68,68,.08);border-radius:6px;display:none';
    var body=document.getElementById('userEditBody');
    if(body)body.insertBefore(errEl,body.firstChild);
  }
  errEl.style.display='none';
  var role=document.getElementById('eR').value;
  var body={role:role,is_active:document.getElementById('eA').value==='1'};
  if(role!=='admin'){
    var sct=document.getElementById('eSct').value;
    body.scope_type=sct;
    if(sct==='region')body.region=document.getElementById('eRg').value;
    else if(sct==='store'){
      var ids=Array.from(document.querySelectorAll('.ecb:checked')).map(function(c){return c.value;});
      if(ids.length)body.store_ids=ids;
    }
  }
  try{
    var r=await fetch(BASE+'/admin/users/'+uid,{method:'PUT',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(r.ok){closeUserEditModal();_clearCache("admin");await loadAdminData(true);}
    else{
      var ed=await r.json();
      var msg=typeof ed.detail==='string'?ed.detail:(ed.detail&&ed.detail[0]&&ed.detail[0].msg)||'';
      var cn={'String should have at least 2 characters':'用户名至少需要2个字符','String should have at least 6 characters':'密码至少需要6位'};
      errEl.textContent=cn[msg]||msg||'保存失败，请检查输入';
      errEl.style.display='block';
    }
  }catch(e){errEl.textContent='网络错误，请重试';errEl.style.display='block';}
}
/* V4.5 重构时丢失的管理功能，2026-07-31 恢复（views.js:177-178 事件委托仍引用） */
async function deleteUser(uid,uname){
  if(!confirm('确定删除用户 '+uname+' 吗？此操作不可撤销。'))return;
  try{
    var r=await fetch(BASE+'/admin/users/'+uid,{method:'DELETE',headers:{'Authorization':'Bearer '+token}});
    if(r.ok){toast('已删除');_clearCache("admin");await loadAdminData(true);}
    else{var e=await r.json();toast((typeof e.detail==='string'?e.detail:'删除失败')||'删除失败','error');}
  }catch(e){toast('网络错误','error');}
}
async function resetPassword(uid){
  var np=prompt('输入新密码（至少6位）：','123456');
  if(!np||np.length<6)return;
  try{
    var r=await fetch(BASE+'/admin/users/'+uid+'/reset-password',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({new_password:np})});
    if(r.ok){toast('密码已重置');}
    else{var e=await r.json();toast((typeof e.detail==='string'?e.detail:'重置失败')||'重置失败','error');}
  }catch(e){toast('网络错误','error');}
}
async function impersonateUser(uid,uname){
  if(!confirm('将以 '+uname+' 的权限查询"我可以访问的门店列表"，确认？'))return;
  try{
    var r=await fetch(BASE+'/admin/impersonate/'+uid,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({question:'查询我可以访问的门店列表'})});
    var d=await r.json();
    var storeCount=d.store_count==='全部'?'全部门店':d.store_count+' 家门店';
    alert('👤 '+d.target_user+' 的数据范围：'+storeCount+'\n\n'+(d.report||'无报告').slice(0,500));
  }catch(e){toast('模拟失败: '+e,'error');}
}
function buildMonitorUrl(d,s,e){var u=BASE+'/monitor/overview?days='+Math.min(d,90);if(s)u+='&start_date='+s;if(e)u+='&end_date='+e;return u;}
function loadMonitorOverview(){
  var mKey='monitor_'+_monitorDays+'_'+_monitorStartDate+'_'+_monitorEndDate;
  var cached=_cache[mKey];
  // 有缓存且未过期（30s）→直接渲染，跳过加载状态
  if(cached&&Date.now()-cached.time<30000){
    renderMonitorView(cached.data.ov,cached.data.er);
    return;
  }
  document.getElementById('monitorView').innerHTML='<div class="mq-loading"><div class="mq-loading-inner"><div class="spinner" style="margin:0 auto 14px"></div>加载中...</div></div>';
  !async function(){
    try{
      var [oR,eR]=await Promise.all([
        fetch(buildMonitorUrl(_monitorDays,_monitorStartDate,_monitorEndDate),{headers:{'Authorization':'Bearer '+token}}),
        fetch(BASE+'/monitor/errors?days='+_monitorDays+'&limit=50',{headers:{'Authorization':'Bearer '+token}})
      ]);
      if(!oR.ok||!eR.ok)throw Error('');
      var ov=await oR.json(),er=await eR.json();
      _cache[mKey]={data:{ov:ov,er:er},time:Date.now()};
      renderMonitorView(ov,er);
    }catch(e){document.getElementById('monitorView').innerHTML='<div class="mq-error-state">❌ 加载失败</div>';}
  }();
}
function setMonitorPreset(p){
  if(p==='custom'){
    document.getElementById('monitorView').innerHTML='<div class="mq-loading"><div class="mq-loading-inner" style="background:var(--card);padding:28px 36px;border-radius:14px;border:1px solid var(--border);max-width:420px"><div style="margin-bottom:16px;font-size:15px;font-weight:600;color:var(--text)">📅 选择日期范围</div><div style="display:flex;gap:10px;align-items:center;justify-content:center;flex-wrap:wrap"><input type="date" id="cSD" style="padding:10px 14px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none"><span style="color:var(--muted);font-size:13px">至</span><input type="date" id="cED" style="padding:10px 14px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;outline:none"></div><div style="margin-top:16px;display:flex;gap:8px;justify-content:center"><button onclick="applyCustomDate()" style="padding:9px 28px;background:var(--accent);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500">确认</button><button onclick="loadMonitorOverview()" style="padding:9px 28px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--muted);cursor:pointer;font-size:13px">取消</button></div></div></div>';
    return;
  }
  _monitorDays=_calcDateRange(p);_monitorPreset=p;var n=new Date();
  _monitorStartDate=p==='prevMonth'?new Date(n.getFullYear(),n.getMonth()-1,1).toISOString().slice(0,10):p==='month'?new Date(n.getFullYear(),n.getMonth(),1).toISOString().slice(0,10):'';
  _monitorEndDate=p==='prevMonth'?new Date(n.getFullYear(),n.getMonth(),0).toISOString().slice(0,10):'';
  loadMonitorOverview();
}
function applyCustomDate(){
  var s=document.getElementById('cSD').value,e=document.getElementById('cED').value;
  if(!s){alert('请选择开始日期');return;}
  _monitorDays=Math.max(1,Math.round((e?new Date(e):new Date())-new Date(s))/86400000);_monitorStartDate=s;_monitorEndDate=e;_monitorPreset='custom';loadMonitorOverview();
}

function renderMonitorView(ov,er){
  var lm={sales:'销售',crm:'CRM',finance:'财务',inventory:'库存',supply_chain:'供应链',supervisor:'规划',aggregator:'聚合',chart_advisor:'图表',report:'报告',reflection:'质检'};
  var pr=ov.reflection_pass_rate||0,p50=ov.latency_p50_ms||0,p95=ov.latency_p95_ms||0,fbr=ov.feedback_helpful_rate||0;
  var dc=_monitorDays||1,da=ov.total_analyses?Math.round(ov.total_analyses/dc):0;
  var rr=ov.retry_rate||0,fr=ov.fix_rate||0,dur=ov.p50_duration_ms||0,p90d=ov.p90_duration_ms||0;
  var dcost=ov.estimated_daily_cost||0,mcost=ov.estimated_monthly_cost||0;
  var per=_monitorPreset==='prevMonth'?'上月':_monitorPreset==='month'?'本月':_monitorPreset==='7'?'近7天':_monitorPreset==='30'?'近30天':'近'+_monitorDays+'天';
  var pills='';[['7','7天'],['30','30天'],['month','本月'],['prevMonth','上月'],['custom','自定义']].forEach(function(p){pills+='<button class="mq-pill'+(p[0]===_monitorPreset?' active':'')+'" onclick="setMonitorPreset(\''+p[0]+'\')">'+p[1]+'</button>';});

  var _errCn={'timeout':'超时','connection refused':'连接拒绝','deadline exceeded':'超时','refused':'拒绝','connection reset':'连接重置','closed':'连接关闭','eof':'连接断开','reset':'重置','timed out':'超时'};
  var ah='';(ov.agents||[]).forEach(function(a){var c=a.error_rate>5?'err':a.error_rate>2?'warn':'ok',bp=Math.min(a.error_rate*10,100);ah+='<tr><td><div class="mq-agent-cell"><span class="mq-agent-dot '+c+'"></span>'+esc(lm[a.agent]||a.agent)+'</div></td><td>'+a.total_runs+'</td><td>'+a.error_count+'</td><td><div class="mq-bar-wrap"><div class="mq-bar"><div class="mq-bar-fill '+c+'" style="width:'+bp+'%"></div></div><span class="mq-pct '+c+'">'+a.error_rate+'%</span></div></td><td>'+a.avg_ms+'</td><td>'+a.max_ms+'</td></tr>';});
  if(!ah)ah='<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">暂无数据</td></tr>';
  var ei='';
  if(er.errors&&er.errors.length){
    ei='<div class="mq-error-header"><span class="mq-error-icon"></span><span class="mh-time">时间</span><span class="mh-agent">Agent</span><span class="mh-msg">错误信息</span><span class="mh-dur">耗时</span></div>';
    er.errors.forEach(function(e){
      var icon=e.error&&e.error.match(/timeout|超时|time.?out/i)?'⏱️':e.error&&e.error.match(/SQL|sql|语法|column|table|relation/i)?'🗃️':'⚠️';
      ei+='<div class="mq-error-item"><span class="mq-error-icon">'+icon+'</span><div class="mq-error-body"><span class="mq-error-time">'+((e.time||'').slice(5,16)||'')+'</span><span class="mq-error-agent-tag">'+esc(lm[e.agent]||e.agent)+'</span><span class="mq-error-msg">'+esc((_errCn[e.error])||e.error||'')+'</span><span class="mq-error-dur">'+(e.elapsed_ms||0)+'ms</span></div></div>';
    });
  }else ei='<div class="mq-error-empty">✅ 无错误记录</div>';
  var ch='';
  if(ov.token_trend&&ov.token_trend.length){
    var show=ov.token_trend.slice(-14),dates=[],inS=[],outS=[],costS=[],ti=0,to2=0,tc2=0;
    show.forEach(function(t){dates.push((t.date||'').slice(5));inS.push(t.input_tokens);outS.push(t.output_tokens);costS.push(t.cost?+(t.cost*10000).toFixed(2):0);ti+=t.input_tokens;to2+=t.output_tokens;tc2+=t.cost;});
    ch='<div class="mq-chart-box"><div class="mq-chart" id="mTC" style="height:260px"></div><div class="mq-chart-summary"><div class="mq-chart-stat"><span class="mq-chart-stat-label">累计 Input</span><span class="mq-chart-stat-value">'+(ti>=1000000?(ti/1000000).toFixed(1)+'M':ti>=1000?(ti/1000).toFixed(1)+'K':ti)+'</span></div><div class="mq-chart-stat"><span class="mq-chart-stat-label">累计 Output</span><span class="mq-chart-stat-value">'+(to2>=1000000?(to2/1000000).toFixed(1)+'M':to2>=1000?(to2/1000).toFixed(1)+'K':to2)+'</span></div><div class="mq-chart-stat"><span class="mq-chart-stat-label">总成本</span><span class="mq-chart-stat-value">¥'+tc2.toFixed(4)+'</span></div></div></div>';
    setTimeout(function(){
      var el=document.getElementById('mTC');if(!el)return;
      if(window._monitorChart)window._monitorChart.dispose();window._monitorChart=echarts.init(el);
      window._monitorChart.setOption({tooltip:{trigger:'axis',backgroundColor:'rgba(30,35,55,0.95)',borderColor:'#334155',textStyle:{color:'#e2e8f0',fontSize:12}},
        legend:{data:['Input','Output','Cost(x¥1e4)'],textStyle:{color:'#94a3b8',fontSize:11},top:0,right:0,icon:'circle',itemWidth:8,itemHeight:8},
        grid:{left:50,right:20,top:40,bottom:30},
        xAxis:{type:'category',data:dates,axisLabel:{color:'#94a3b8',fontSize:10},axisLine:{lineStyle:{color:'#334155'}},axisTick:{show:false}},
        yAxis:[{type:'value',name:'Tokens',nameTextStyle:{color:'#94a3b8',fontSize:10},axisLabel:{color:'#94a3b8',fontSize:10,formatter:function(v){return v>=1000000?(v/1000000).toFixed(1)+'M':v>=1000?(v/1000).toFixed(1)+'K':v;}},splitLine:{lineStyle:{color:'#1e293b'}}},{type:'value',name:'Cost',nameTextStyle:{color:'#94a3b8',fontSize:10},axisLabel:{color:'#94a3b8',fontSize:10,formatter:function(v){return '¥'+(v/10000).toFixed(4);}},splitLine:{show:false}}],
        series:[{name:'Input',type:'line',data:inS,smooth:true,symbol:'circle',symbolSize:6,lineStyle:{width:2,color:'#6366f1'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(99,102,241,0.25)'},{offset:1,color:'rgba(99,102,241,0)'}]}}},{name:'Output',type:'line',data:outS,smooth:true,symbol:'circle',symbolSize:6,lineStyle:{width:2,color:'#22c55e'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(34,197,94,0.2)'},{offset:1,color:'rgba(34,197,94,0)'}]}}},{name:'Cost(x¥1e4)',type:'bar',yAxisIndex:1,data:costS,itemStyle:{color:'rgba(245,158,11,0.5)',borderColor:'#f59e0b',borderWidth:1,borderRadius:[2,2,0,0]}}]});
    },100);
  }
  document.getElementById('monitorView').innerHTML=
    '<div class="mq-header"><div class="mq-header-left"><h2>AI 质量监控</h2><span class="mq-header-period">'+per+'</span></div><div class="mq-pills">'+pills+'</div></div>'+
    '<div class="mq-hero"><div class="mq-hero-card accent"><div class="mq-hero-top"><div class="mq-hero-icon">📊</div><span class="mq-hero-status good">日均 '+da+' 次</span></div><div class="mq-hero-value">'+da+'</div><div class="mq-hero-label">日均分析量</div></div>'+
    '<div class="mq-hero-card success"><div class="mq-hero-top"><div class="mq-hero-icon">✅</div><span class="mq-hero-status '+(pr>=90?'good':pr>=75?'warn':'bad')+'">'+(pr>=90?'优秀':pr>=75?'良好':'需关注')+'</span></div><div class="mq-hero-value">'+pr+'%</div><div class="mq-hero-label">Reflection 通过率</div><div class="mq-hero-sub">用户好评率 '+fbr+'%</div></div>'+
    '<div class="mq-hero-card warning"><div class="mq-hero-top"><div class="mq-hero-icon">⚡</div><span class="mq-hero-status '+(p50<500?'good':p50<1000?'warn':'bad')+'">'+(p50<500?'优秀':p50<1000?'良好':'需关注')+'</span></div><div class="mq-hero-value">'+p50+'ms</div><div class="mq-hero-label">P50 响应延迟</div><div class="mq-hero-sub">P95 '+p95+'ms · 完整分析 '+Math.round(dur/1000)+'s</div></div></div>'+
    '<div class="mq-groups"><div class="mq-group"><div class="mq-group-title">🔬 质量指标</div><div class="mq-group-cards">'+
    '<div class="mq-sm-card '+(rr>10?'red':rr>5?'amber':'green')+'"><div class="mq-sm-card-label">重试率</div><div class="mq-sm-card-value">'+rr+'%</div><div class="mq-sm-sub">修复率 '+fr+'%</div></div>'+
    '<div class="mq-sm-card '+(fr>=70?'green':fr>=50?'amber':'red')+'"><div class="mq-sm-card-label">修复率</div><div class="mq-sm-card-value">'+fr+'%</div><div class="mq-sm-sub">重试后通过比例</div></div>'+
    '<div class="mq-sm-card '+(fbr>=85?'green':fbr>=70?'amber':'red')+'"><div class="mq-sm-card-label">用户好评率</div><div class="mq-sm-card-value">'+fbr+'%</div><div class="mq-sm-sub">反馈有帮助比例</div></div>'+
    '<div class="mq-sm-card '+(dur<30000?'green':'amber')+'"><div class="mq-sm-card-label">完整分析 P90</div><div class="mq-sm-card-value">'+Math.round(p90d/1000)+'s</div><div class="mq-sm-sub">90% 在此时间内完成</div></div></div></div>'+
    '<div class="mq-group"><div class="mq-group-title">💰 成本指标</div><div class="mq-group-cards">'+
    '<div class="mq-sm-card '+(dcost>0.05?'amber':'green')+'"><div class="mq-sm-card-label">日均成本</div><div class="mq-sm-card-value">¥'+(ov.total_analyses?dcost.toFixed(4):'—')+'</div><div class="mq-sm-sub">每日 LLM 调用费用</div></div>'+
    '<div class="mq-sm-card '+(mcost>1?'amber':'green')+'"><div class="mq-sm-card-label">月均成本</div><div class="mq-sm-card-value">¥'+(ov.total_analyses?mcost.toFixed(4):'—')+'</div><div class="mq-sm-sub">累计 Token 消耗</div></div></div></div></div>'+
    '<div class="mq-section"><div class="mq-section-header"><div class="mq-section-title">🤖 Agent 健康度</div><div class="mq-section-subtitle">错误率排行 · 性能指标</div></div><div class="mq-table-wrap"><table class="mq-table"><thead><tr><th>Agent</th><th>运行</th><th>错误</th><th>错误率</th><th>平均(ms)</th><th>最大(ms)</th></tr></thead><tbody>'+ah+'</tbody></table></div></div>'+
    '<div class="mq-section"><div class="mq-section-header"><div class="mq-section-title">❌ 最近错误</div><div class="mq-section-subtitle">按时间倒序</div></div>'+ei+'</div>'+
    (ch?'<div class="mq-section"><div class="mq-section-header"><div class="mq-section-title">📊 Token 消耗趋势</div><div class="mq-section-subtitle">近 '+show.length+' 天 · 含 Input/Output/Cost</div></div>'+ch+'</div>':'');
}


/* Sessions & History */
async function newSession(){
  if(!token){toast('请先登录');return;}
  try{
    var r=await fetch(BASE+'/session/create',{method:'POST',headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)return;var d=await r.json();sessionId=d.session_id;
    document.getElementById('sessionIdDisplay').textContent=sessionId.substring(0,8)+'...';
    document.getElementById('entityBox').style.display='none';
    document.getElementById('chat').innerHTML='<div class="empty-state" id="emptyState"><div class="greeting-icon">🤖</div><div class="greeting" id="greetingText">有什么经营问题需要分析？</div><div class="greeting-sub" id="greetingSub">5 个 AI Agent 并行分析销售、会员、财务、库存、供应链数据</div><div class="quick-stats" id="quickStats"></div><div class="quick-grid" id="quickGrid"></div><p style="font-size:12px;color:var(--muted)">或直接输入问题：</p></div>';
    renderQuickGrid();renderEmptyStats();switchTab('analysis');
  }catch(e){console.warn("Catch:",e);}
}
async function loadSessionInfo(){
  if(!sessionId||!token)return;
  try{
    var r=await fetch(BASE+'/session/'+sessionId,{headers:{'Authorization':'Bearer '+token}});
    if(r.ok){var d=await r.json(),em=d.entity_memory||{},keys=Object.keys(em);if(keys.length){var h='';keys.forEach(function(k){h+='<span class="ent">'+(em[k].type==='member'?'👤 ':'🏪 ')+esc(k)+'</span>';});document.getElementById('entityTags').innerHTML=h;document.getElementById('entityBox').style.display='block';}}
  }catch(e){console.warn("Catch:",e);}
}
function dismissHistory(id,e){
  if(e)e.stopPropagation();
  hiddenIds.add(id);var el=document.getElementById('hi-'+id);if(el)el.style.display='none';
  try{var a=JSON.parse(localStorage.getItem('eia_dismissed')||'[]');a.push(id);localStorage.setItem('eia_dismissed',JSON.stringify(a));dismissedIds.add(id);}catch(ex){}
}
function clearAllHistory(){
  if(!confirm('清除所有记录？'))return;
  localStorage.setItem('eia_dismissed','[]');dismissedIds=new Set();hiddenIds=new Set();
  if(_currentTab==='history')loadHistoryView(1);
}
var _hvData=[],_hvFilterTimer=null;
function filterHistory(){
  clearTimeout(_hvFilterTimer);
  _hvFilterTimer=setTimeout(function(){
    var q=(document.getElementById('hvSearch')||{}).value||'';
    renderHistoryList(_hvData,q);
  },200);
}
function renderHistoryList(rec,q){
  if(q)rec=rec.filter(function(r){return(r.question||'').toLowerCase().indexOf(q.toLowerCase())>=0;});
  if(!rec.length){document.getElementById('historyList').innerHTML='<div class="hv-empty"><div class="hv-empty-icon">🔍</div><div class="hv-empty-text">'+(q?'无匹配结果':'暂无记录')+'</div></div>';return;}
  var html='';
  rec.forEach(function(rr){
    var ts=rr.created_at?rr.created_at.substring(0,10):(rr.create_time?rr.create_time.substring(0,10):'');
    var qText=esc((rr.question||'').substring(0,80));
    var summary=(rr.summary||'').replace(/[*#\[\]|]/g,'').trim().substring(0,100);
    var passed=rr.reflection_passed;
    html+='<div class="hv-item" onclick="viewHistoryDetail('+rr.id+')'+
      '"><div class="hv-item-badge '+(passed?'hv-badge-pass':'hv-badge-fail')+'">'+(passed?'✅':'<span style="font-size:11px">⚠️</span>')+'</div>'+
      '<div class="hv-item-body"><div class="hv-item-q">'+qText+'</div>'+
      (summary?'<div class="hv-item-s">'+esc(summary)+'</div>':'')+
      '<div class="hv-item-meta"><span class="hv-item-time">📅 '+ts+'</span>'+
      '<span class="hv-item-status '+(passed?'hv-st-pass':'hv-st-fail')+'">'+(passed?'通过检查':'需审查')+'</span></div></div></div>';
  });
  var tp=Math.ceil((_hvData.total||0)/20);
  if(tp>1){
    html+='<div class="hv-pages">';
    for(var p=1;p<=tp;p++) html+='<button class="hv-page'+(p===_hvData._page?' active':'')+'" onclick="loadHistoryView('+p+')">'+p+'</button>';
    html+='</div>';
  }
  document.getElementById('historyList').innerHTML=html;
}
async function loadHistoryView(page){
  if(!token)return;
  page=page||1;
  try{
    var r=await fetch(BASE+'/analysis/history?page='+page+'&page_size=20',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)return;
    var d=await r.json(),rec=(d.records||[]).filter(function(rr){return!hiddenIds.has(rr.id)&&!dismissedIds.has(rr.id);});
    rec.total=d.total;rec._page=page;_hvData=rec;
    document.getElementById('hvCount').textContent=(d.total||0)+' 条';
    renderHistoryList(rec,(document.getElementById('hvSearch')||{}).value||'');
  }catch(e){console.warn("Catch:",e);}
}
async function viewHistoryDetail(id){
  try{
    var r=await fetch(BASE+'/analysis/history/'+id,{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok){toast('加载失败','error');return;}
    var d=await r.json();
    _lastReportText=d.report||'';_lastQuestionText=d.question||'';
    document.getElementById('chat').innerHTML='<div class="msg user"><div class="bubble">'+esc(d.question||'')+'</div></div>';
    if(d.report){
      var sup='',ds='',fq='',rh='',fb='',tb='';
      try{sup=buildSupervisorPlan(d.supervisor_plan);}catch(e){}
      try{var _r2=d.report.replace(/\[FOLLOWUP[^\]]*\]\]/g,'');rh=sanitizeHtml(marked.parse(convertTextTables(expandChartTags(_r2))));}catch(e){rh=esc(d.report);}
      try{ds=buildTracePanel(d.data_sources);}catch(e){}
      try{fq=buildFollowupButtons(d.followup_questions);}catch(e){}
      try{if(d.id)fb='<div class="feedback-bar"><span>这个回答对你有帮助吗？</span><button class="feedback-btn" onclick="showFeedback(&#39;helpful&#39;)">👍 有帮助</button><button class="feedback-btn" onclick="showFeedback(&#39;bad&#39;)">👎 没有帮助</button></div>';}catch(e){}
      tb='<div style="display:flex;justify-content:flex-end;gap:6px;margin-top:8px;flex-wrap:wrap">'+
        (d.id?'<span style="font-size:10px;color:var(--muted);margin-right:auto;align-self:center">#'+d.id+'</span>':'')+
        '<span class="print-btn" onclick="_copyReport()">📋 复制</span>'+
        '<span class="print-btn" onclick="window.print()">🖨️ 打印</span>'+
        '<span class="share-btn" onclick="downloadMD()">⬇️ Markdown</span>'+
        '<span class="share-btn" onclick="exportPDF()">📄 PDF</span></div>';
      document.getElementById('chat').innerHTML+='<div class="msg assistant"><div class="bubble">'+sup+rh+trustFooter()+ds+fq+'</div>'+tb+fb+'</div>';
    }else{
      document.getElementById('chat').innerHTML+='<div class="msg assistant"><div class="bubble" style="color:var(--amber)">无报告内容</div></div>';
    }
    switchTab('analysis');
  }catch(e){console.warn("Catch:",e);}
}

var CAP_CARDS=[
  {icon:"📊",title:"销售分析",desc:"趋势·排名·对比",question:"各门店销售额排名"},
  {icon:"👥",title:"会员洞察",desc:"增长·留存·画像",question:"会员增长与留存情况"},
  {icon:"💰",title:"财务诊断",desc:"成本·利润·应收",question:"整体经营分析报告"},
  {icon:"📦",title:"库存预警",desc:"滞销·周转·缺货",question:"各区域经营对比"},
  {icon:"🚚",title:"供应链优化",desc:"交期·评级·采购",question:"供应商准时交货率排名"}
];
function renderCapabilityCards(){
  var cc=document.getElementById("capCards");
  if(!cc)return;
  cc.innerHTML=CAP_CARDS.map(function(c){
    return "<div class=\"cap-card\" data-question=\""+esc(c.question)+"\"><span class=\"cap-card-icon\">"+c.icon+"</span><div class=\"cap-card-text\"><span class=\"cap-card-title\">"+esc(c.title)+"</span><span class=\"cap-card-desc\">"+esc(c.desc)+"</span></div></div>"
  }).join("");
}
function fillQuestion(q){document.getElementById("question").value=q;document.getElementById("question").focus();}
function renderQuickGrid(){var g=document.getElementById('quickGrid');if(!g)return;var q=getQuickQuestions(_currentRole);g.innerHTML=q.map(function(q){return '<button class="quick-btn" data-question="'+esc(q.text)+'">'+q.icon+' '+esc(q.text)+'</button>';}).join('');}
function renderEmptyStats(){
  var qs=document.getElementById("quickStats");
  if(!qs)return;
  var dashCached=_cache["dashboard"];
  if(!dashCached||!dashCached.data){qs.style.display="none";return}
  var d=dashCached.data;
  var tS=d.today_sales||0,yS=d.yesterday_sales||0;
  var sc=yS>0?((tS-yS)/yS*100).toFixed(1):0,up=sc>=0;
  var greeting="";
  var h=new Date().getHours();
  if(h<6)greeting="深夜了";
  else if(h<9)greeting="早上好";
  else if(h<12)greeting="上午好";
  else if(h<14)greeting="中午好";
  else if(h<18)greeting="下午好";
  else greeting="晚上好";
  document.getElementById("greetingText").textContent=greeting+"，今天有什么经营问题需要分析？";
  qs.innerHTML='<div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center;margin-bottom:14px">'+
    '<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 16px;text-align:center;min-width:100px">'+
      '<div style="font-size:20px;font-weight:700;color:var(--accent-hover)">'+formatCurrency(tS)+'</div>'+
      '<div style="font-size:10px;color:var(--muted)">今日销售额</div></div>'+
    '<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 16px;text-align:center;min-width:100px">'+
      '<div style="font-size:20px;font-weight:700;color:'+(up?"var(--green)":"var(--red)")+'">'+(up?"↑":"↓")+' '+Math.abs(sc)+'%</div>'+
      '<div style="font-size:10px;color:var(--muted)">vs 昨日</div></div>'+
    '<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 16px;text-align:center;min-width:100px">'+
      '<div style="font-size:20px;font-weight:700;color:var(--text)">'+(d.active_stores||"---")+'</div>'+
      '<div style="font-size:10px;color:var(--muted)">活跃门店</div></div>'+
    '<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 16px;text-align:center;min-width:100px">'+
      '<div style="font-size:20px;font-weight:700;color:var(--text)">'+formatPercent(d.week_refund_rate)+'</div>'+
      '<div style="font-size:10px;color:var(--muted)">退款率</div></div>'+
    '<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 16px;text-align:center;min-width:100px">'+
      '<div style="font-size:20px;font-weight:700;color:var(--text)">'+(d.recent_orders_24h||"---")+'</div>'+
      '<div style="font-size:10px;color:var(--muted)">近24h订单</div></div>'+
  '</div>';
  qs.style.display="block";
}
function quickAsk(q){document.getElementById('question').value=q;document.getElementById('btn').click();}
function askFollowup(q){document.getElementById('question').value=q;document.getElementById('btn').click();}

/* Voice */
function initVoice(){
  if(!('webkitSpeechRecognition'in window)&&!('SpeechRecognition'in window))return;
  voiceRecognition=new(window.SpeechRecognition||window.webkitSpeechRecognition)();
  voiceRecognition.lang='zh-CN';voiceRecognition.continuous=false;voiceRecognition.interimResults=true;
  voiceRecognition.onresult=function(e){var t='';for(var i=e.resultIndex;i<e.results.length;i++)t+=e.results[i][0].transcript;document.getElementById('question').value=t;};
  voiceRecognition.onend=function(){stopVoice();};
}
function toggleVoice(){
  if(voiceListening){stopVoice();return;}
  if(!voiceRecognition)initVoice();
  voiceListening=true;document.getElementById('voiceBtn').classList.add('listening');document.getElementById('voiceToast').classList.add('show');
  try{voiceRecognition.start();}catch(e){}
}
function stopVoice(){
  voiceListening=false;document.getElementById('voiceBtn').classList.remove('listening');document.getElementById('voiceToast').classList.remove('show');
  try{voiceRecognition.stop();}catch(e){}
  var q=document.getElementById('question').value.trim();if(q)document.getElementById('btn').click();
}

/* 报告信任分级（合规标注，V4.5 重构时丢失，2026-07-31 恢复） */
function trustFooter(){
  return '<div style="display:flex;align-items:center;gap:6px;margin-top:14px;margin-bottom:6px"><span style="font-size:14px">🛡️</span><span style="font-weight:600;color:var(--text)">本报告信任分级</span></div>'+
    '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:2px"><span style="color:var(--green);font-weight:600;white-space:nowrap">✅ 数据层</span><span style="color:var(--muted)">数据直接来自您的数据库，每条结论可点击 <span style="color:var(--accent)">📊 查看SQL</span> 追溯原始查询，可信度极高</span></div>'+
    '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:2px"><span style="color:var(--amber);font-weight:600;white-space:nowrap">⚠️ 分析层</span><span style="color:var(--muted)">趋势判断和原因分析由 AI 基于数据推理生成，建议结合业务经验判断</span></div>'+
    '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:2px"><span style="color:var(--accent);font-weight:600;white-space:nowrap">💡 建议层</span><span style="color:var(--muted)">经营建议为 AI 参考性输出，执行前请结合实际情况进行人工复核</span></div>'+
    '<div style="margin-top:6px;font-size:10px;color:var(--muted);text-align:right">本报告由 AI 自动生成 · 符合《生成式人工智能服务管理暂行办法》</div>';
}

/* Chat SSE */
function stopAnalysis(){
  if(_abortController){_abortController.abort();_abortController=null;}
  _isAnalyzing=false;document.getElementById('btn').disabled=false;document.getElementById('stopBtn').style.display='none';document.getElementById('quickBar').style.display='flex';
  var pg=document.getElementById('progressMsg');if(pg)pg.remove();
}
async function ask(e){
  if(e)e.preventDefault();
  if(_isAnalyzing||!token)return;
  var q=document.getElementById('question').value.trim();if(!q)return;
  var el=document.getElementById('chat');
  document.getElementById('question').value='';document.getElementById('btn').disabled=true;document.getElementById('stopBtn').style.display='';
  _isAnalyzing=true;_abortController=new AbortController();_lastQuestionText=q;_lastReportText='';document.getElementById('quickBar').style.display='none';
  el.innerHTML+='<div class="msg user"><div class="bubble">'+esc(q)+'</div></div>';
  var ps='';STEPS.forEach(function(n,i){ps+='<span class="step" id="s-'+n+'">'+(SEMOJIS[n]||'')+' '+LABELS[i]+'</span>';});
  el.innerHTML+='<div class="msg assistant" id="pM"><div class="bubble" style="padding:0;overflow:visible"><div class="progress"><h3><div class="spinner"></div> <span id="pT">🧠 规划中...</span></h3><div class="steps">'+ps+'</div></div></div></div>';
  el.scrollTop=el.scrollHeight;var cs=[];
  if(!sessionId)try{var sr=await fetch(BASE+'/session/create',{method:'POST',headers:{'Authorization':'Bearer '+token}});var sd=await sr.json();sessionId=sd.session_id;}catch(e){}
  try{
    var sr2=await fetch(BASE+'/analysis/analyze-stream',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({question:q,session_id:sessionId}),signal:_abortController.signal});
    if(!sr2.ok)throw Error('API error');
    var r2=sr2.body.getReader(),dec=new TextDecoder(),buf='',sc='',fr='',fid=null,fds=[],ffqs=[],fers=[],first=false,sb=null,fsp=null;
    while(true){
      var{done,value}=await r2.read();if(done)break;
      buf+=dec.decode(value,{stream:true});var ls=buf.split('\n');buf=ls.pop();
      for(var l of ls){
        if(!l.startsWith('data: '))continue;
        try{
          var ev=JSON.parse(l.slice(6));
          if(ev.type==='phase'&&ev.status==='start'){
            var pt=document.getElementById('pT');if(pt)pt.textContent=ev.message||ev.label||'';
            document.querySelectorAll('.step.active').forEach(function(s){s.classList.remove('active');});
            var ae=document.getElementById('s-'+ev.node);if(ae)ae.classList.add('active');
          }else if(ev.type==='step'&&ev.status==='done'){
            if(cs.indexOf(ev.node)===-1)cs.push(ev.node);
            var de=document.getElementById('s-'+ev.node);if(de){de.classList.remove('active');de.classList.add('done');if(!de.querySelector('.ck'))de.innerHTML+='<span class="ck" style="margin-left:2px">✓</span>';}
          }else if(ev.type==='token'){
            if(!first)first=true;
            if(cs.indexOf('report_agent')>=0){cs=cs.filter(function(n){return n!=='report_agent';});sc='';}
            sc+=ev.text;
          }else if(ev.type==='done'){
            fr=ev.report||'';fers=ev.errors||[];fds=ev.data_sources||[];ffqs=ev.followup_questions||[];fid=ev.record_id||null;fsp=ev.supervisor_plan||null;
            var ctr=fr||sc;
            if(ctr&&!sb){
              sb=document.createElement('div');sb.className='msg assistant';
              var sd2=document.createElement('div');sd2.className='bubble stream-content';sb.appendChild(sd2);
              var pm=document.getElementById('pM');
              if(pm&&pm.parentNode)pm.parentNode.insertBefore(sb,pm.nextSibling);else el.appendChild(sb);
              var fh;try{fh=sanitizeHtml(marked.parse(convertTextTables(expandChartTags(ctr))));}catch(e){fh=esc(ctr);}
              sd2.innerHTML=fh.replace(/\[FOLLOWUP[^\]]*\]\]/g,'');
              try{
                sd2.insertAdjacentHTML('afterend',trustFooter());
                var ext='';try{ext=buildSupervisorPlan(fsp);}catch(e){}
                try{ext+=buildTracePanel(fds);}catch(e){}
                try{ext+=buildFollowupButtons(ffqs);}catch(e){}
                try{if(fid)ext+='<div class="feedback-bar"><span>有帮助吗？</span><button class="feedback-btn" onclick="showFeedback(\'helpful\')">👍</button><button class="feedback-btn" onclick="showFeedback(\'bad\')">👎</button></div>';}catch(e){}
                sd2.insertAdjacentHTML('afterend',ext);
                sd2.insertAdjacentHTML('afterend','<div style="display:flex;justify-content:flex-end;gap:6px;margin-top:8px;flex-wrap:wrap">'+(fid?'<span style="font-size:10px;color:var(--muted);margin-right:auto;align-self:center">#'+fid+'</span>':'')+'<span class="print-btn" onclick="window.print()">✂️ 打印</span><span class="print-btn" onclick="downloadMD()">⬇️ MD</span><span class="share-btn" onclick="exportPDF()">📄 PDF</span></div>');
                try{sb.scrollIntoView({block:'start',behavior:'smooth'});}catch(e){}
                initChartsInBubble(sb);_lastReportText=sd2.textContent||'';_lastQuestionText=q||'';
              }catch(e){console.error(e);}
            }
          }
        }catch(e){_sseParseErrs++;if(_sseParseErrs>5){toast('连接不稳定，部分数据可能丢失');_sseParseErrs=0;}console.warn('SSE event parse:',e);}
      }
    }
    var pm2=document.getElementById('pM');if(pm2)pm2.remove();
    if(sb){}else if(fr){
      try{var e2='';try{e2=buildSupervisorPlan(fsp);}catch(e){}try{e2+=buildTracePanel(fds);}catch(e){}try{e2+=buildFollowupButtons(ffqs);}catch(e){}
      el.innerHTML+='<div class="msg assistant"><div class="bubble">'+sanitizeHtml(marked.parse(convertTextTables(expandChartTags(fr))))+trustFooter()+e2+'</div></div>';}catch(e){el.innerHTML+='<div class="msg assistant"><div class="bubble">'+esc(fr)+trustFooter()+'</div></div>';}
    }else if(!fr&&!sc){el.innerHTML+='<div class="msg assistant"><div class="bubble" style="color:var(--amber)">未生成报告</div></div>';}
    if(!sb)el.scrollTop=el.scrollHeight;
    document.getElementById('quickBar').style.display='flex';lastRecordId=fid;loadSessionInfo();
  }catch(err){
    if(err.name==='AbortError')return;
    document.getElementById('question').value=q;var pm3=document.getElementById('pM');if(pm3)pm3.remove();
    el.innerHTML+='<div class="msg assistant"><div class="bubble" style="color:var(--red)">请求失败</div></div>';
  }finally{
    _isAnalyzing=false;_abortController=null;document.getElementById('btn').disabled=false;document.getElementById('stopBtn').style.display='none';document.getElementById('quickBar').style.display='flex';document.getElementById('question').focus();
  }
}

/* Feedback */
function showFeedback(r){pendingFeedback={rating:r,record_id:lastRecordId};document.getElementById('feedbackModal').style.display='flex';setTimeout(function(){document.getElementById('feedbackText').focus();},100);}
function closeFeedbackModal(){document.getElementById('feedbackModal').style.display='none';pendingFeedback=null;}
async function submitFeedback(){
  var t=document.getElementById('feedbackText').value.trim();if(!pendingFeedback){closeFeedbackModal();return;}
  try{
    var r=await fetch(BASE+'/feedback/submit',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({analysis_history_id:pendingFeedback.record_id,rating:pendingFeedback.rating,reason:t||null})});
    var d=await r.json();closeFeedbackModal();document.getElementById('feedbackText').value='';
    toast((d.stats&&d.stats.text)||d.message||'感谢反馈！');
  }catch(e){toast('提交失败','error');}
}
async function showFeedbackHistory(){
  if(!token){toast('请先登录');return;}
  try{
    var r=await fetch(BASE+'/feedback/history?limit=20',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok){toast('加载失败','error');return;}
    var d=await r.json(),h='<div class="modal-box" style="width:560px;max-width:95%;max-height:85vh;overflow-y:auto"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><span style="font-size:18px;font-weight:700;color:var(--text)">📝 我的反馈</span>'+(d.total>0?' <span style="font-size:12px;color:var(--muted)">好评率 '+d.helpful_rate+'%</span>':'')+'<button onclick="closeFeedbackHistory()" style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px">&times;</button></div>';
    if(!d.entries||!d.entries.length)h+='<div style="padding:40px 0;text-align:center;color:var(--muted)">暂无记录</div>';
    else d.entries.forEach(function(e){var ri=e.rating==='helpful'?'👍':'👎',rc=e.rating==='helpful'?'var(--green)':'var(--red)';h+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:8px"><div style="display:flex;justify-content:space-between">'+ri+' <span style="color:'+rc+';font-weight:600">'+(e.rating==='helpful'?'有帮助':'不准确')+'</span> <span style="color:var(--muted);font-size:11px">'+((e.created_at||'').slice(0,10)||'')+'</span></div>'+(e.question?'<div style="font-size:12px;color:var(--muted)">"'+esc(e.question)+'"</div>':'')+'</div>';});
    h+='</div>';
    var ov=document.createElement('div');ov.className='modal-overlay';ov.id='fbHistoryOverlay';ov.style.display='flex';ov.onclick=function(ev){if(ev.target===ov)closeFeedbackHistory();};ov.innerHTML=h;document.body.appendChild(ov);
  }catch(e){toast('加载失败','error');console.warn(e);}
}
function closeFeedbackHistory(){var el=document.getElementById('fbHistoryOverlay');if(el)el.remove();}

/* Export */
async function exportPDF(){
  if(!_lastReportText){toast('无报告','error');return;}
  try{
    var r=await fetch(BASE+'/weekly/export',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({report:_lastReportText,title:(_lastQuestionText||'报告').substring(0,40)})});
    if(!r.ok){var e=await r.json();toast(e.detail||'导出失败');return;}
    var b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='report.pdf';a.click();URL.revokeObjectURL(u);toast('PDF已下载');
  }catch(e){toast('导出失败','error');}
}

/* Copy report (复用 utils.js 中的 copyToClipboard) */

function _copyReport(){if(_lastReportText) copyToClipboard(_lastReportText);}
