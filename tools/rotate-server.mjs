import http from 'node:http';
import fs from 'node:fs';
import crypto from 'node:crypto';

const PORT = Number(process.env.PORT || 8790);
const TOKEN = process.env.ROTATE_TOKEN;
const INDEX_PATH = process.env.CURRENT_INDEX || '/tmp/current-index.html';
const OUT_INDEX = process.env.NEW_INDEX || '/tmp/new-index.html';
const DONE_PATH = process.env.DONE_PATH || '/tmp/rotation-done.json';
if (!TOKEN) throw new Error('ROTATE_TOKEN missing');

const original = fs.readFileSync(INDEX_PATH, 'utf8');
const m = original.match(/const ENCRYPTED_PAYLOAD=(\{.*?\});\s*let data=/s);
if (!m) throw new Error('Encrypted payload not found');
const currentEnvelope = JSON.parse(m[1]);
let used = false;

const b64ok = (s) => typeof s === 'string' && /^[A-Za-z0-9+/]+={0,2}$/.test(s) && s.length % 4 === 0;
const decodeLen = (s) => Buffer.from(s, 'base64').length;
const json = (res, status, obj) => {
  const body = JSON.stringify(obj);
  res.writeHead(status, {'content-type':'application/json; charset=utf-8','cache-control':'no-store'});
  res.end(body);
};
const validToken = (url) => url.searchParams.get('token') === TOKEN;

const page = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>修改SKU访问密码</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:#172033;background:#f3f6fa}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:18px}.card{width:min(94vw,420px);background:#fff;border:1px solid #dce4ef;border-radius:22px;padding:22px;box-shadow:0 18px 50px rgba(15,23,42,.10)}.mark{width:52px;height:52px;display:grid;place-items:center;border-radius:15px;background:#13233f;color:#fff;font-size:24px}h1{font-size:21px;margin:14px 0 7px}p{font-size:12px;color:#667085;line-height:1.65;margin:0 0 16px}.notice{padding:10px 12px;border-radius:12px;background:#eff6ff;color:#1e40af;font-size:11px;line-height:1.55;margin-bottom:14px}label{font-size:12px;font-weight:750;display:block;margin:11px 0 6px}input{width:100%;min-height:48px;border:1px solid #ccd6e5;border-radius:12px;padding:10px 12px;font-size:16px}button{width:100%;min-height:48px;margin-top:14px;border:0;border-radius:12px;background:#1f5bd8;color:#fff;font-size:15px;font-weight:800}.status{min-height:42px;margin-top:12px;font-size:12px;line-height:1.55}.err{color:#b91c1c}.ok{color:#067647}.muted{color:#667085}.rule{font-size:11px;color:#667085;margin-top:10px;padding-top:10px;border-top:1px solid #eef2f6;line-height:1.55}</style></head><body><main class="card"><div class="mark">🔑</div><h1>修改访问密码</h1><p>旧密码和新密码只在这台手机浏览器里使用。服务器只接收重新加密后的密文。</p><div class="notice">建议新密码至少12位，包含字母和数字。不要使用银行卡、邮箱或其他重要账号的同一密码。</div><form id="f" autocomplete="off"><label for="old">当前密码</label><input id="old" type="password" autocomplete="current-password" required><label for="nw">新密码</label><input id="nw" type="password" autocomplete="new-password" required minlength="10"><label for="cf">再次输入新密码</label><input id="cf" type="password" autocomplete="new-password" required minlength="10"><button id="btn" type="submit">确认修改密码</button><div id="st" class="status muted"></div></form><div class="rule">完成后旧密码将对新发布版本失效。此页面为一次性改密通道，成功提交后不能重复使用。</div></main><script>
const qs=new URLSearchParams(location.search), token=qs.get('token');
const st=document.getElementById('st'),btn=document.getElementById('btn');
const te=new TextEncoder(),td=new TextDecoder();
const b64bytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const bytes64=u=>{let s='';for(let i=0;i<u.length;i+=0x8000)s+=String.fromCharCode(...u.subarray(i,i+0x8000));return btoa(s)};
async function keyFor(password,salt,iterations){const km=await crypto.subtle.importKey('raw',te.encode(password),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations,hash:'SHA-256'},km,{name:'AES-GCM',length:256},false,['encrypt','decrypt'])}
async function decrypt(env,pw){const key=await keyFor(pw,b64bytes(env.salt),env.iterations);const p=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64bytes(env.iv),additionalData:te.encode(env.aad)},key,b64bytes(env.cipher));return JSON.parse(td.decode(p))}
async function encrypt(data,pw,iterations,aad){const salt=crypto.getRandomValues(new Uint8Array(16)),iv=crypto.getRandomValues(new Uint8Array(12));const key=await keyFor(pw,salt,iterations);const plain=te.encode(JSON.stringify(data));const cipher=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:te.encode(aad)},key,plain));return {salt:bytes64(salt),iv:bytes64(iv),cipher:bytes64(cipher),iterations,aad}}
async function getEnvelope(){const r=await fetch('/api/envelope?token='+encodeURIComponent(token),{cache:'no-store'});if(!r.ok)throw new Error('一次性通道已失效');return r.json()}
document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();const old=document.getElementById('old').value,nw=document.getElementById('nw').value,cf=document.getElementById('cf').value;if(nw!==cf){st.className='status err';st.textContent='两次新密码不一致。';return}if(nw.length<10){st.className='status err';st.textContent='新密码至少10位，建议12位以上。';return}btn.disabled=true;st.className='status muted';st.textContent='正在本机验证旧密码并重新加密…';try{const env=await getEnvelope();let data;try{data=await decrypt(env,old)}catch{throw new Error('当前密码不正确')}if(!Array.isArray(data)||data.length!==31)throw new Error('数据校验失败');const next=await encrypt(data,nw,env.iterations,env.aad);const check=await decrypt(next,nw);if(!Array.isArray(check)||check.length!==31)throw new Error('本机新密码复核失败');const r=await fetch('/api/submit?token='+encodeURIComponent(token),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(next)});const out=await r.json().catch(()=>({}));if(!r.ok)throw new Error(out.error||'提交失败');document.getElementById('old').value='';document.getElementById('nw').value='';document.getElementById('cf').value='';st.className='status ok';st.textContent='✅ 新密文已安全提交。请回到ChatGPT，我会确认新版本发布完成。';btn.disabled=true}catch(err){st.className='status err';st.textContent=err.message||'修改失败';btn.disabled=false}});
if(!token){st.className='status err';st.textContent='无效的一次性链接';btn.disabled=true}
</script></body></html>`;

const server = http.createServer((req,res)=>{
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (url.pathname === '/' || url.pathname === '/rotate') {
    if (!validToken(url) || used) { res.writeHead(403,{'content-type':'text/plain; charset=utf-8','cache-control':'no-store'}); return res.end('链接无效或已使用'); }
    res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store','x-frame-options':'DENY','content-security-policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"});
    return res.end(page);
  }
  if (url.pathname === '/api/envelope' && req.method === 'GET') {
    if (!validToken(url) || used) return json(res,403,{error:'invalid'});
    return json(res,200,currentEnvelope);
  }
  if (url.pathname === '/api/submit' && req.method === 'POST') {
    if (!validToken(url) || used) return json(res,403,{error:'链接无效或已使用'});
    let raw=''; req.on('data',d=>{raw+=d;if(raw.length>150000)req.destroy()}); req.on('end',()=>{
      try{
        const env=JSON.parse(raw);
        if (!env || !b64ok(env.salt)||!b64ok(env.iv)||!b64ok(env.cipher)) throw new Error('密文格式错误');
        if (decodeLen(env.salt)!==16 || decodeLen(env.iv)!==12) throw new Error('密文参数错误');
        if (decodeLen(env.cipher)<1000 || decodeLen(env.cipher)>100000) throw new Error('密文长度异常');
        if (env.iterations!==currentEnvelope.iterations || env.aad!==currentEnvelope.aad) throw new Error('加密参数不一致');
        if (env.cipher===currentEnvelope.cipher) throw new Error('新密文未变化');
        const nextLiteral=JSON.stringify(env);
        const next=original.replace(/const ENCRYPTED_PAYLOAD=\{.*?\};\s*let data=/s, `const ENCRYPTED_PAYLOAD=${nextLiteral};\nlet data=`);
        if (next===original) throw new Error('无法更新加密数据');
        for (const forbidden of ['声光漏水报警器','手动抽芯铆钉枪','3.6×150mm 100条黑色']) if (next.includes(forbidden)) throw new Error('明文检查失败');
        fs.writeFileSync(OUT_INDEX,next,'utf8');
        const meta={at:new Date().toISOString(),oldCipherSha256:crypto.createHash('sha256').update(currentEnvelope.cipher).digest('hex'),newCipherSha256:crypto.createHash('sha256').update(env.cipher).digest('hex')};
        fs.writeFileSync(DONE_PATH,JSON.stringify(meta,null,2));
        used=true;
        return json(res,200,{ok:true});
      }catch(e){return json(res,400,{error:e.message||'invalid'});}
    });
    return;
  }
  if (url.pathname === '/health') return json(res,200,{ok:true,used});
  res.writeHead(404);res.end('not found');
});
server.listen(PORT,'0.0.0.0',()=>console.log(JSON.stringify({ok:true,port:PORT})));
