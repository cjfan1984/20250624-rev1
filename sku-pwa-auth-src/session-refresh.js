(()=>{
  const KEY='pwa-refresh-once-password';
  let activeSessionPassword='';

  const baseUnlock=window.unlockWithPassword;
  if(typeof baseUnlock==='function'){
    window.unlockWithPassword=async function(password){
      const ok=await baseUnlock(password);
      if(ok) activeSessionPassword=String(password||'');
      return ok;
    };
  }

  const baseLock=window.lockApp;
  if(typeof baseLock==='function'){
    window.lockApp=function(){
      activeSessionPassword='';
      try{sessionStorage.removeItem(KEY);}catch(_){ }
      return baseLock();
    };
  }

  window.manualRefresh=async function(){
    const btn=document.getElementById('refreshBtn');
    if(btn){btn.disabled=true;btn.textContent='刷新中…';}
    try{
      // 只为这一次重载临时跨页保存；新页面读到后会立即删除。
      if(activeSessionPassword) sessionStorage.setItem(KEY,activeSessionPassword);
      if('serviceWorker' in navigator){
        const regs=await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(r=>r.update().catch(()=>{})));
      }
      if('caches' in window){
        const keys=await caches.keys();
        await Promise.all(keys.map(k=>caches.delete(k)));
      }
    }finally{
      const u=new URL(window.location.href);
      u.searchParams.set('_refresh',Date.now().toString());
      window.location.replace(u.toString());
    }
  };

  // 若本页是“人工刷新”后的新页面，立即取出一次性密码并清除，再自动解锁。
  let once='';
  try{once=sessionStorage.getItem(KEY)||'';sessionStorage.removeItem(KEY);}catch(_){ }
  if(once){
    setTimeout(async()=>{
      try{await window.unlockWithPassword(once);}finally{once='';}
    },0);
  }
})();
