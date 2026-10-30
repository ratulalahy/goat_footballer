// Render dist/standalone.html at desktop and phone widths, light and dark; report console errors.
// Usage: node shoot.js <outDir> [sectionId]
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const outDir = process.argv[2];
  const only = process.argv[3];
  const browser = await chromium.launch({ proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined });
  const file = "file://" + path.resolve(__dirname, "dist/standalone.html");
  const runs = [
    { name: "desktop-light", width: 1366, height: 900, scheme: "light" },
    { name: "phone-dark", width: 400, height: 860, scheme: "dark" },
  ];
  for (const r of runs) {
    const ctx = await browser.newContext({ viewport: { width: r.width, height: r.height }, colorScheme: r.scheme, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(`${m.type()}: ${m.text()}`); });
    page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
    page.on("requestfailed", (q) => errors.push("requestfailed: " + q.url() + " " + (q.failure() || {}).errorText));
    await page.goto(file, { waitUntil: "networkidle", timeout: 60000 });
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const fonts = await page.evaluate(() => [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family).filter((v, i, a) => a.indexOf(v) === i));
    if (only) {
      const el = await page.$("#" + only);
      await el.screenshot({ path: `${outDir}/${r.name}-${only}.png` });
    } else {
      await page.screenshot({ path: `${outDir}/${r.name}-full.png`, fullPage: true });
    }
    console.log(r.name, "horizontal overflow px:", overflow, "| fonts:", fonts.join(", "));
    for (const e of errors.slice(0, 15)) console.log("  ", e);
    await ctx.close();
  }
  await browser.close();
})();
