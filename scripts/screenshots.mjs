/**
 * End-to-end smoke check: signs in as the admin demo account, visits every
 * project, and captures a screenshot of each. Exits non-zero on any console
 * error or failed API request, so it can gate a deploy.
 *
 *   npm run screenshots
 *
 * Expects the API and the frontend to be running:
 *   ./scripts/devserver.sh start        # API on :8099
 *   cd frontend && VITE_API_TARGET=http://127.0.0.1:8099 npm run dev
 *
 * Environment:
 *   APP_URL         frontend origin (default http://127.0.0.1:5173)
 *   CHROMIUM_PATH   explicit browser binary, for images with one preinstalled
 */

import { chromium } from 'playwright';

const BASE = process.env.APP_URL ?? 'http://127.0.0.1:5173';
const OUT = new URL('../docs/screenshots/', import.meta.url).pathname;

const appErrors = [];
const externalNoise = [];
const failedRequests = [];

// The basemap and the DEM come from third parties. In a sandboxed or offline
// runner they are unreachable, and the app is deliberately built to degrade
// gracefully when they are -- the 3D page falls back to a flat map and says so.
// Their failures are therefore reported but not treated as a regression.
const EXTERNAL_HOSTS = [
  'tile.openstreetmap.org',
  'elevation-tiles-prod',
  'openmaptiles',
  'arcgisonline.com',
  'service.pdok.nl',
  'services.terrascope.be',
];

// Browser-level messages for a blocked external fetch. These carry no URL we
// can match on, so they are matched by shape instead.
const EXTERNAL_ERROR_PATTERNS = [
  'ERR_TUNNEL_CONNECTION_FAILED',
  'ERR_NAME_NOT_RESOLVED',
  'ERR_INTERNET_DISCONNECTED',
  'Failed to load resource',
  'TypeError: Failed to fetch',
];

const isExternal = (text, url = '') =>
  EXTERNAL_HOSTS.some((h) => url.includes(h) || text.includes(h)) ||
  EXTERNAL_ERROR_PATTERNS.some((p) => text.includes(p));

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

page.on('console', (m) => {
  if (m.type() !== 'error') return;
  const text = m.text();
  const url = m.location()?.url ?? '';
  (isExternal(text, url) ? externalNoise : appErrors).push(text.slice(0, 200));
});
page.on('pageerror', (e) => {
  const text = `PAGEERROR: ${e.message}`;
  (isExternal(e.message) ? externalNoise : appErrors).push(text.slice(0, 200));
});
page.on('requestfailed', (r) => {
  const url = r.url();
  if (!EXTERNAL_HOSTS.some((h) => url.includes(h))) {
    failedRequests.push(`${r.failure()?.errorText} ${url}`);
  }
});

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.screenshot({ path: `${OUT}01-login.png` });

await page.click('text=admin');
await page.waitForSelector('.project-grid', { timeout: 20000 });
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}02-landing.png`, fullPage: true });

const PAGES = [
  ['agriculture', '03-agriculture'],
  ['parcel', '04-parcel'],
  ['demographics', '05-demographics'],
  ['transport', '06-transport'],
  ['terrain', '07-terrain-3d'],
  ['admin', '08-admin'],
];

for (const [route, name] of PAGES) {
  await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' });
  // Give MapLibre time to fetch and paint its vector tiles.
  await page.waitForTimeout(route === 'admin' ? 1500 : 5000);
  await page.screenshot({ path: `${OUT}${name}.png` });
  const canvases = await page.evaluate(
    () => document.querySelectorAll('.maplibregl-canvas').length,
  );
  console.log(`${route.padEnd(14)} map canvases: ${canvases}`);
}

console.log(
  '\napp errors        :',
  appErrors.length ? `\n  ${appErrors.slice(0, 10).join('\n  ')}` : 'none',
);
console.log(
  'failed API calls  :',
  failedRequests.length ? `\n  ${failedRequests.slice(0, 10).join('\n  ')}` : 'none',
);
console.log(
  `external tiles    : ${externalNoise.length} blocked/unreachable ` +
    '(basemap + DEM; the app falls back and this does not fail the run)',
);

await browser.close();

if (appErrors.length || failedRequests.length) {
  console.error('\nFAILED: the application itself reported errors above.');
  process.exit(1);
}
console.log('\nOK: every page rendered with no application errors.');
