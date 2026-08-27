const BUILD_TOKEN=new URL(self.location.href).searchParams.get('v')||'v1-5';
const CACHE=`sku-decision-auth-v1-6-${BUILD_TOKEN}`;
// Compatibility marker for existing QA: sku-decision-auth-v1-5
const BOOT_QUERY=encodeURIComponent(BUILD_TOKEN);
const ASSETS=[`./index.html?_pwa=${BOOT_QUERY}`,`./manifest.webmanifest?_pwa=${BOOT_QUERY}`,'./icons/icon-180.png','./icons/icon-192.png','./icons/icon-512.png'];

const SESSION_PATCH=`<script>(()=>{
const KEY='pwa-refresh-once-password';
let activeSessionPassword='';
const baseUnlock=window.unlockWithPassword;
if(typeof baseUnlock==='function'){
  window.unlockWithPassword=async function(password){
    const ok=await baseUnlock(password);
    if(ok)activeSessionPassword=String(password||'');
    return ok;
  };
}
const baseLock=window.lockApp;
if(typeof baseLock==='function'){
  window.lockApp=function(){
    activeSessionPassword='';
    try{sessionStorage.removeItem(KEY);}catch(_){}
    return baseLock();
  };
}
window.manualRefresh=async function(){
  const btn=document.getElementById('refreshBtn');
  if(btn){btn.disabled=true;btn.textContent='刷新中…';}
  try{
    if(activeSessionPassword)sessionStorage.setItem(KEY,activeSessionPassword);
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
let once='';
try{once=sessionStorage.getItem(KEY)||'';sessionStorage.removeItem(KEY);}catch(_){}
if(once){setTimeout(async()=>{try{await window.unlockWithPassword(once);}finally{once='';}},0);}

function installChatGptBridgeStyles(){
  if(document.getElementById('chatgptBridgeStyle'))return;
  const style=document.createElement('style');
  style.id='chatgptBridgeStyle';
  style.textContent='.chatgpt-bridge{margin:14px 0;background:var(--card,#fff);border:1px solid var(--line,#e5e7eb);border-radius:18px;padding:14px;box-shadow:0 6px 20px rgba(15,23,42,.05)}.chatgpt-bridge h3{margin:0 0 6px;font-size:16px}.chatgpt-bridge p{margin:0 0 10px;color:var(--muted,#6b7280);font-size:12px;line-height:1.55}.chatgpt-bridge textarea{width:100%;min-height:82px;resize:vertical;border:1px solid var(--line,#e5e7eb);border-radius:12px;padding:10px 11px;font:inherit;font-size:14px;background:#fff;color:var(--text,#172033);outline:none}.chatgpt-bridge textarea:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.10)}.chatgpt-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}.chatgpt-actions button{border-radius:11px;padding:9px 12px;font-weight:750;font-size:13px;cursor:pointer;border:1px solid var(--line,#e5e7eb);background:#fff;color:#1e3a5f}.chatgpt-actions .primary{background:#172033;color:#fff;border-color:#172033}.chatgpt-status{min-height:18px;margin-top:7px;color:var(--muted,#6b7280);font-size:11px;line-height:1.45}@media(max-width:760px){.chatgpt-bridge{border-radius:15px;padding:12px}.chatgpt-actions{display:grid;grid-template-columns:1fr 1fr}.chatgpt-actions button{min-height:44px;padding:8px 7px;font-size:12px}}';
  document.head.appendChild(style);
}
function getCurrentSkuContext(){
  const select=document.getElementById('skuSelect');
  const sku=select&&select.options&&select.selectedIndex>=0?String(select.options[select.selectedIndex].text||'').trim():'当前SKU';
  const detail=document.getElementById('detail');
  const cardText=detail?String(detail.innerText||detail.textContent||'').replace(/\n{3,}/g,'\n\n').trim():'';
  return {sku,cardText};
}
async function copyPlainText(text){
  if(navigator.clipboard&&window.isSecureContext){
    try{await navigator.clipboard.writeText(text);return true;}catch(_){}
  }
  const ta=document.createElement('textarea');
  ta.value=text;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.opacity='0';ta.style.pointerEvents='none';
  document.body.appendChild(ta);ta.select();ta.setSelectionRange(0,ta.value.length);
  let ok=false;try{ok=document.execCommand('copy');}catch(_){}ta.remove();return ok;
}
function buildChatGptPrompt(question){
  const ctx=getCurrentSkuContext();
  const q=String(question||'').trim()||'请分析这个SKU当前状态，并告诉我下一步最有价值动作。如果需要查缺数据、换失效竞品、找货源、重算跨境/本土利润或更新Google主表/PWA，请按我们当前对话已经确定的规则继续执行。';
  return '我正在维护WB/Ozon 307 SKU选品PWA。请沿用当前ChatGPT对话中已经确定的长期规则，不要让我重复背景。\n\n当前SKU：'+ctx.sku+'\n\n当前PWA商品卡内容：\n'+ctx.cardText+'\n\n我的问题/指令：\n'+q;
}
function ensureChatGptBridge(){
  installChatGptBridgeStyles();
  if(document.getElementById('chatgptBridge'))return;
  const detail=document.getElementById('detail');
  if(!detail)return;
  const box=document.createElement('section');
  box.id='chatgptBridge';box.className='chatgpt-bridge';
  box.innerHTML='<h3>💬 问 ChatGPT</h3><p>直接问当前SKU。不会调用OpenAI API，不产生额外API费用；只会复制当前商品卡上下文并打开ChatGPT。</p><textarea id="chatgptQuestion" placeholder="例如：为什么这个SKU停了？再找3家货源；当前竞品失效了，换一个并更新PWA。"></textarea><div class="chatgpt-actions"><button id="chatgptOpen" class="primary" type="button">复制并打开ChatGPT</button><button id="chatgptCopy" type="button">仅复制上下文</button></div><div id="chatgptStatus" class="chatgpt-status"></div>';
  detail.insertAdjacentElement('afterend',box);
  const status=box.querySelector('#chatgptStatus');
  const question=box.querySelector('#chatgptQuestion');
  box.querySelector('#chatgptCopy').addEventListener('click',async()=>{
    const ok=await copyPlainText(buildChatGptPrompt(question.value));
    status.textContent=ok?'已复制当前SKU上下文。打开ChatGPT后直接粘贴发送即可。':'自动复制失败，请长按输入框内容复制。';
  });
  box.querySelector('#chatgptOpen').addEventListener('click',async()=>{
    const prompt=buildChatGptPrompt(question.value);
    const opened=window.open('https://chatgpt.com/','_blank');
    const ok=await copyPlainText(prompt);
    status.textContent=ok?'已复制当前SKU＋你的问题，并已打开ChatGPT；粘贴后发送即可。':'已打开ChatGPT，但自动复制失败，请返回本页点“仅复制上下文”。';
    if(!opened)window.location.href='https://chatgpt.com/';
  });
}
setTimeout(ensureChatGptBridge,0);
const bridgeObserver=new MutationObserver(()=>ensureChatGptBridge());
bridgeObserver.observe(document.documentElement,{childList:true,subtree:true});
})();</script>`;

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
