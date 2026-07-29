/* Enterprise Insight Agent V4 — 入口
 * 初始化 + 会话恢复
 * HTML 内的 onclick/onsubmit 直接调用全局函数，无需 addEventListener
 */
(function(){
  function init(){
    // 欢迎页粒子
    initIntroParticles();

    // 会话恢复
    var savedUser = localStorage.getItem('eia_user');
    var savedToken = localStorage.getItem('eia_token');
    if(savedToken && savedUser){
      token = savedToken;
      restoreSession(savedUser);
      checkAdmin();
    }
    // 无登录态，停留在欢迎页等待用户点击"进入系统"
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
