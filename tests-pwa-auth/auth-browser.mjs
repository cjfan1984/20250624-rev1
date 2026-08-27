import { chromium } from 'playwright';
const url=process.env.PWA_URL || 'http://127.0.0.1:4174/index.html';
const password=process.env.AUTH_TEST_PASSWORD;
if(!password) throw new Error('AUTH_TEST_PASSWORD missing');
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'});
const page=await context.newPage();
await page.goto(url,{waitUntil:'domcontentloaded'});
await page.locator('#authScreen:not([hidden])').waitFor();
const initialOptions=await page.locator('#skuSelect option').count();
if(initialOptions!==0) throw new Error(`Locked page exposed options: ${initialOptions}`);
const initialText=await page.locator('body').innerText();
if(initialText.includes('声光漏水报警器')) throw new Error('Locked UI leaked SKU name');
await page.fill('#authPassword','wrong-password');
await page.click('#loginBtn');
await page.waitForTimeout(400);
const wrongError=await page.locator('#authError').innerText();
if(!wrongError.includes('密码错误')) throw new Error(`Wrong password was not rejected: ${wrongError}`);
await page.fill('#authPassword',password);
await page.click('#loginBtn');
await page.locator('#appRoot:not([hidden])').waitFor();
const optionCount=await page.locator('#skuSelect option').count();
if(optionCount<1) throw new Error(`Expected at least one product card after login, got ${optionCount}`);
const firstTitle=await page.locator('#detail h2').innerText();
if(!firstTitle) throw new Error('Product card title missing');

// Validate the full-library ordering contract independently of legacy CI fixture fields:
// calculable SKUs sort by unit profit descending; negative profit stays above pending;
// pending profit must be last and must not be coerced to 0.
const syntheticOrder=await page.evaluate(()=>{
  const originalData=data;
  const originalSorted=sorted;
  data=[
    normalizeRow({rank:9901,sku:'CI待补',profitKnown:false,priority:'C'}),
    normalizeRow({rank:9902,sku:'CI高利润',profitKnown:true,profit:25,margin:30,priority:'A+'}),
    normalizeRow({rank:9903,sku:'CI低利润',profitKnown:true,profit:5,margin:10,priority:'B'}),
    normalizeRow({rank:9904,sku:'CI负利润',profitKnown:true,profit:-2,margin:-5,priority:'C'})
  ];
  sorted=[...data];
  sortBy('profit');
  const order=[...document.querySelectorAll('#skuSelect option')].map(o=>o.textContent||'');
  data=originalData;
  sorted=originalSorted;
  sortBy('margin');
  return order;
});
if(syntheticOrder.length!==4 || !syntheticOrder[0].includes('CI高利润') || !syntheticOrder[1].includes('CI低利润') || !syntheticOrder[2].includes('CI负利润') || !syntheticOrder[3].includes('CI待补')) {
  throw new Error(`Profit/pending ordering contract failed: ${JSON.stringify(syntheticOrder)}`);
}

await page.getByRole('button',{name:'按单件利润'}).click();
const topProfit=await page.locator('#skuSelect option').first().innerText();
if(!topProfit) throw new Error('Profit sort produced empty first option');
const cardText=await page.locator('#detail').innerText();
if(!cardText.includes('产品卡')||!cardText.includes('竞品差评洞察')) throw new Error('Product-card modules missing');
if(await page.locator('#refreshBtn').count()!==1) throw new Error('Manual refresh button missing');
await page.screenshot({path:'auth-app-mobile.png',fullPage:true});
await page.click('#lockBtn');
await page.locator('#authScreen:not([hidden])').waitFor();
const lockedOptions=await page.locator('#skuSelect option').count();
if(lockedOptions!==0) throw new Error('Lock did not clear options');
await page.screenshot({path:'auth-login-mobile.png',fullPage:true});
await page.fill('#authPassword',password);await page.click('#loginBtn');await page.locator('#appRoot:not([hidden])').waitFor();
await page.evaluate(()=>navigator.serviceWorker.ready);
await context.setOffline(true);
await page.reload({waitUntil:'domcontentloaded'});
await page.locator('#authScreen:not([hidden])').waitFor();
await page.fill('#authPassword',password);await page.click('#loginBtn');await page.locator('#appRoot:not([hidden])').waitFor();
const offlineOptions=await page.locator('#skuSelect option').count();
if(offlineOptions!==optionCount) throw new Error(`Offline unlock changed product-card count: ${optionCount} -> ${offlineOptions}`);
await context.setOffline(false);
console.log(JSON.stringify({initialOptions,wrongError,optionCount,firstTitle,syntheticOrder,topProfit,lockedOptions,offlineOptions},null,2));
await browser.close();
