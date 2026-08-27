import { chromium } from 'playwright';
const url=process.env.PWA_URL || 'http://127.0.0.1:4175/index.html';
const step=(name)=>console.log(`[STEP] ${new Date().toISOString()} ${name}`);
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'});
const page=await context.newPage();
page.setDefaultTimeout(12000);
page.setDefaultNavigationTimeout(15000);
page.on('console',msg=>console.log(`[PAGE:${msg.type()}] ${msg.text()}`));
page.on('pageerror',err=>console.log(`[PAGEERROR] ${err.message}`));
page.on('requestfailed',req=>console.log(`[REQUESTFAILED] ${req.url()} :: ${req.failure()?.errorText||''}`));
try{
  step('goto initial');
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:15000});
  step('wait external version');
  await page.waitForFunction(()=>window.PWA_DATA_VERSION && window.PWA_DATA_VERSION.records>0,null,{timeout:12000});
  const first=await page.evaluate(()=>({version:window.PWA_DATA_VERSION,loginDisabled:document.getElementById('loginBtn')?.disabled,body:document.body.innerText}));
  step(`initial data loaded records=${first.version.records}`);
  if(first.loginDisabled) throw new Error('Login remained disabled after external data load');
  if(first.body.includes('手动抽芯铆钉枪')||first.body.includes('声光漏水报警器')) throw new Error('Locked UI leaked SKU text');

  step('fetch version/data directly');
  const vresp=await page.request.get(new URL('./pwa-data-version.json',url).toString(),{timeout:10000});
  const dresp=await page.request.get(new URL('./sku-data.enc.json',url).toString(),{timeout:10000});
  const networkVersion=await vresp.json();const encrypted=await dresp.json();
  if(encrypted.kind!=='SKU-PWA-HYBRID-ENVELOPE') throw new Error('External data is not hybrid envelope');
  if(encrypted.records!==networkVersion.records||networkVersion.records!==first.version.records) throw new Error('External record count mismatch');

  step('wait service worker ready');
  await page.evaluate(()=>Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error('SW ready timeout')),10000))]));
  step('reload under SW control');
  await page.reload({waitUntil:'domcontentloaded',timeout:15000});
  step('wait automation center online');
  await page.waitForFunction(()=>window.PWA_DATA_VERSION && document.getElementById('automationCenter'),null,{timeout:12000});
  const onlineCenter=await page.locator('#automationCenter').innerText({timeout:5000});
  if(!onlineCenter.includes('SKU自动化中心')||!onlineCenter.includes('25项自动化路线图')) throw new Error('Automation center missing after SW control');

  step('switch offline');
  await context.setOffline(true);
  step('offline reload');
  await page.reload({waitUntil:'domcontentloaded',timeout:15000});
  step('wait cached external version offline');
  await page.waitForFunction(()=>window.PWA_DATA_VERSION && window.PWA_DATA_VERSION.records>0,null,{timeout:12000});
  const offline=await page.evaluate(()=>({records:window.PWA_DATA_VERSION.records,loginDisabled:document.getElementById('loginBtn')?.disabled,center:document.getElementById('automationCenter')?.innerText||''}));
  if(offline.records!==first.version.records) throw new Error(`Offline record mismatch ${offline.records}/${first.version.records}`);
  if(offline.loginDisabled) throw new Error('Offline cached external data did not enable login');
  if(!offline.center.includes('SKU自动化中心')) throw new Error('Automation center missing offline');
  await context.setOffline(false);
  step('success');
  console.log(JSON.stringify({records:first.version.records,version:first.version.version,onlineCenter:onlineCenter.slice(0,180),offlineRecords:offline.records},null,2));
} finally {
  await browser.close();
}
