const BUILD_TOKEN=new URL(self.location.href).searchParams.get('v')||'v1-5';
const CACHE=`sku-decision-auth-${BUILD_TOKEN}`;
const BOOT_QUERY=encodeURIComponent(BUILD_TOKEN);
const ASSETS=[`./index.html?_pwa=${BOOT_QUERY}`,`./manifest.webmanifest?_pwa=${BOOT_QUERY}`,'./icons/icon-180.png','./icons/icon-192.png','./icons/icon-512.png'];

const SESSION_PATCH=`<script>(()=>{const KEY='pwa-refresh-once-password';let activeSessionPassword='';const baseUnlock=window.unlockWithPassword;if(typeof baseUnlock==='function'){window.unlockWithPassword=async function(password){const ok=await baseUnlock(password);if(ok)activeSessionPassword=String(password||'');return ok;};}const baseLock=window.lockApp;if(typeof baseLock==='function'){window.lockApp=function(){activeSessionPassword='';try{sessionStorage.removeItem(KEY);}catch(_){}return baseLock();};}window.manualRefresh=async function(){const btn=document.getElementById('refreshBtn');if(btn){btn.disabled=true;btn.textContent='刷新中…';}try{if(activeSessionPassword)sessionStorage.setItem(KEY,activeSessionPassword);if('serviceWorker' in navigator){const regs=await navigator.serviceWorker.getRegistrations();await Promise.all(regs.map(r=>r.update().catch(()=>{})));}if('caches' in window){const keys=await caches.keys();await Promise.all(keys.map(k=>caches.delete(k)));}}finally{const u=new URL(window.location.href);u.searchParams.set('_refresh',Date.now().toString());window.location.replace(u.toString());}};let once='';try{once=sessionStorage.getItem(KEY)||'';sessionStorage.removeItem(KEY);}catch(_){}if(once){setTimeout(async()=>{try{await window.unlockWithPassword(once);}finally{once='';}},0);}})();</script>`;

async function patchHtml(resp){
  const ct=resp.headers.get('content-type')||'';
  if(!ct.includes('text/html'))return resp;
  const html=await resp.text();
  if(html.includes('pwa-refresh-once-password'))return new Response(html,{status:resp.status,statusText:resp.statusText,headers:resp.headers});
  const out=html.replace('</body>',SESSION_PATCH+'</body>');
  const headers=new Headers(resp.headers);headers.delete('content-length');
  return new Response(out,{status:resp.status,statusText:resp.statusText,headers});
}

self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{const r=event.request;if(r.method!=='GET')return;const u=new URL(r.url);if(u.origin!==self.location.origin)return;const isDocument=r.mode==='navigate'||u.pathname.endsWith('/index.html')||u.pathname.endsWith('/');event.respondWith((async()=>{try{let target=r;if(isDocument){const fresh=new URL(r.url);fresh.searchParams.set('_pwa',`${BUILD_TOKEN}-${Date.now()}`);target=fresh.toString();}const resp=await fetch(target,isDocument?{cache:'no-store'}:undefined);if(!resp.ok)throw new Error(`HTTP ${resp.status}`);const patched=isDocument?await patchHtml(resp):resp;const copy=patched.clone();await caches.open(CACHE).then(c=>c.put(r,copy));return patched;}catch(_){const cached=isDocument?(await caches.match(ASSETS[0])||await caches.match(r)):await caches.match(r);return cached?(isDocument?patchHtml(cached):cached):Response.error();}})());});
