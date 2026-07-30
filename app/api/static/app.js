/* Enterprise Insight Agent V4 — 入口
 * 初始化 + 会话恢复
 * V4.5: 用同步方式检查 token，避免异步导致主界面闪烁
 */
(function(){
  // 兜底：如果欢迎页被意外隐藏，立即恢复
  var _checkTimer = setInterval(function(){
    var intro = document.getElementById('introOverlay');
    var login = document.getElementById('loginOverlay');
    if(!intro || !login) return;
    // 如果两个都隐藏了但 app 也没显示，说明出了问题，恢复欢迎页
    if(intro.style.display !== 'none' && login.style.display !== 'none' &&
       intro.style.display !== '' && login.style.display !== '') return;
    if(intro.style.display === 'none' && login.style.display === 'none'){
      var app = document.getElementById('app');
      if(app && app.style.display !== 'flex'){
        intro.style.display = '';
        intro.style.opacity = '1';
      }
    }
  }, 100);

  function init(){
    initIntroParticles();

    var savedUser = localStorage.getItem('eia_user');
    var savedToken = localStorage.getItem('eia_token');
    if(savedToken && savedUser){
      token = savedToken;
      // 同步检查 token（用同步 XHR 避免闪屏）
      try{
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/v1/admin/users', false);  // false = 同步
        xhr.setRequestHeader('Authorization', 'Bearer ' + token);
        xhr.send();
        if(xhr.status === 200){
          clearInterval(_checkTimer);
          restoreSession(savedUser);
          checkAdmin();
          return;
        }
      }catch(e){}
      // token 无效
      localStorage.removeItem('eia_token');
      localStorage.removeItem('eia_user');
      token = '';
    }
    // 停留在欢迎页
    clearInterval(_checkTimer);
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
