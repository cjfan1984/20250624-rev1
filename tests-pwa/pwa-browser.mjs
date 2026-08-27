import { chromium } from 'playwright';

const url = process.env.PWA_URL || 'http://127.0.0.1:4173/';
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 1,
  isMobile: true,
  hasTouch: true,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
});
const page = await context.newPage();
await page.goto(url, { waitUntil: 'networkidle' });

const optionCount = await page.locator('#skuSelect option').count();
if (optionCount !== 31) throw new Error(`Expected 31 SKU options, got ${optionCount}`);

const firstTitle = await page.locator('#detail h2').innerText();
if (!firstTitle.includes('声光漏水报警器')) throw new Error(`Unexpected first SKU: ${firstTitle}`);

await page.selectOption('#skuSelect', '2');
const secondTitle = await page.locator('#detail h2').innerText();
if (!secondTitle.includes('3.6×150mm 100条黑色')) throw new Error(`Dropdown switch failed: ${secondTitle}`);

await page.getByRole('button', { name: '按单件利润' }).click();
const topProfitOption = await page.locator('#skuSelect option').first().innerText();
if (!topProfitOption.includes('手动抽芯铆钉枪')) throw new Error(`Profit sort failed: ${topProfitOption}`);

const manifestHref = await page.locator('link[rel="manifest"]').getAttribute('href');
if (!manifestHref) throw new Error('Manifest link missing');
await page.evaluate(() => navigator.serviceWorker.ready);

await page.screenshot({ path: 'pwa-mobile.png', fullPage: true });

await context.setOffline(true);
await page.reload({ waitUntil: 'domcontentloaded' });
const offlineCount = await page.locator('#skuSelect option').count();
if (offlineCount !== 31) throw new Error(`Offline cache failed: ${offlineCount}`);
await context.setOffline(false);

const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await desktop.goto(url, { waitUntil: 'networkidle' });
await desktop.screenshot({ path: 'pwa-desktop.png', fullPage: true });

console.log(JSON.stringify({
  optionCount,
  firstTitle,
  secondTitle,
  topProfitOption,
  offlineCount,
  manifestHref
}, null, 2));
await browser.close();
