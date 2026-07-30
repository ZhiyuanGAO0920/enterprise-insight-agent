/* Enterprise Insight Agent V4 — 入口
 * 初始化 + 会话恢复
 * V4.5: 先验证 token 有效性再恢复会话，避免闪现主界面
 */
(function(){
  async function init(){
    initIntroParticles();

    var savedUser = localStorage.getItem('eia_user');
    var savedToken = localStorage.getItem('eia_token');
    if(savedToken && savedUser){
      // 先验证 token 是否有效，再决定是否恢复会话
      // 避免 token 过期时闪现主界面再跳回登录
      token = savedToken;
      try{
        var r = await fetch('/api/v1/admin/users', {
          headers: {'Authorization': 'Bearer ' + token}
        });
        if(r.ok){
          await restoreSession(savedUser);
          checkAdmin();
          return;
        }
      }catch(e){}
      // token 无效，清除并停留在欢迎页
      localStorage.removeItem('eia_token');
      localStorage.removeItem('eia_user');
      token = '';
    }
    // 无登录态，停留在欢迎页等待用户点击"进入系统"
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
