// Photograph the og card (scripts/frontend/og_card.py) in local headless
// Chromium.  Every request that is not the card's own file is aborted, so
// nothing leaves the machine; the count is reported and og_card.py refuses a
// render that attempted any.  Run from frontend/ so @playwright/test resolves
// to the pinned version in package-lock.json.
// Usage: node render_og_card.cjs <card.html> <card.png> <width> <height>
const { chromium } = require(require.resolve("@playwright/test", { paths: [process.cwd()] }));

(async () => {
  const [source, output, width, height] = process.argv.slice(2);
  const size = { width: Number(width), height: Number(height) };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 });
  let external = 0;
  await page.route("**/*", (route) => {
    if (route.request().url().startsWith("file://")) return route.continue();
    external += 1;
    return route.abort();
  });
  await page.goto("file://" + source, { waitUntil: "load" });
  await page.screenshot({ path: output, clip: { x: 0, y: 0, ...size } });
  const renderer = `chromium ${browser.version()} ${process.platform}`;
  await browser.close();
  console.log(JSON.stringify({ external_requests: external, renderer }));
})().catch((error) => {
  console.error(String(error && error.stack || error));
  process.exit(1);
});
