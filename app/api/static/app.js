/* Enterprise Insight Agent V4 — 入口
 * 初始化 + 会话恢复
 * token 有效性验证已在 index.html 内联脚本中优先执行
 */
(function(){
  function init(){
    initIntroParticles();

    var savedUser = localStorage.getItem('eia_user');
    var savedToken = localStorage.getItem('eia_token');
    if(savedToken && savedUser){
      token = savedToken;
      restoreSession(savedUser);
      // checkAdmin 已合并到 restoreSession 的 /admin/users 请求中
    } else {
      // 无有效 token：显示登录页（解决 head 验证脚本异步删除 token 后的竞态）
      document.addEventListener('DOMContentLoaded', function(){
        showLogin();
      });
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
