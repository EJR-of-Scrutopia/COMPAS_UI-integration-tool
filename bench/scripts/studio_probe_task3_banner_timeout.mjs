// Follow-up to studio_probe_task3.mjs: confirms the double-failure banner
// is not left stuck (the "one failed load also left a stuck error banner"
// concern from the task-3 brief's context). Reproduces the monkeypatched
// double failure, then waits past showBanner's own 12000ms error-level
// timer and re-checks, rather than checking a few hundred ms after the
// banner appears (too soon to tell "still on its timer" from "stuck").
//
// Run: node bench/scripts/studio_probe_task3_banner_timeout.mjs
import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const STUDIO_URL = process.env.STUDIO_URL || "http://127.0.0.1:8642";
const BROWSER_EXE = process.env.BROWSER_EXE ||
  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function waitFor(page, fn, { timeout = 15000, interval = 200 } = {}) {
  const start = Date.now();
  for (;;) {
    const ok = await page.evaluate(fn);
    if (ok) return true;
    if (Date.now() - start > timeout) return false;
    await sleep(interval);
  }
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE, headless: true,
    args: ["--use-angle=default"], defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
  await waitFor(page, () => !!window.__studio, { timeout: 10000 });
  await page.evaluate(() => {
    const select = document.getElementById("environment-mode");
    select.value = "hdri";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await sleep(400);

  await page.evaluate(() => {
    const THRESHOLD = 500000;
    function wrap(Orig, label) {
      return new Proxy(Orig, {
        construct(target, args) {
          const len = typeof args[0] === "number" ? args[0] : (args[0] && args[0].length) || 0;
          if (len > THRESHOLD) throw new RangeError("Array buffer allocation failed (banner-timeout probe, " + label + ")");
          return Reflect.construct(target, args);
        },
      });
    }
    window.__origF32 = window.Float32Array;
    window.__origU16 = window.Uint16Array;
    window.Float32Array = wrap(window.Float32Array, "Float32Array");
    window.Uint16Array = wrap(window.Uint16Array, "Uint16Array");
  });
  await page.evaluate(() => {
    const select = document.getElementById("hdri-select");
    select.value = "hdri0.hdr";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const t0 = Date.now();
  const bannerUp = await waitFor(page, () =>
    !document.getElementById("banner").classList.contains("hidden"), { timeout: 15000 });
  const upAt = Date.now() - t0;
  const bannerTextAtShow = await page.evaluate(() => document.getElementById("banner-text").textContent);
  console.log("banner appeared: " + bannerUp + " after " + upAt + " ms, text: " + JSON.stringify(bannerTextAtShow));

  await page.evaluate(() => {
    window.Float32Array = window.__origF32;
    window.Uint16Array = window.__origU16;
  });

  // showBanner arms error-level banners for 12000ms. Poll past that
  // without touching the banner (no hover, no close click) and confirm
  // it clears itself.
  const hiddenAfterTimeout = await waitFor(page, () =>
    document.getElementById("banner").classList.contains("hidden"), { timeout: 14000, interval: 250 });
  const totalWaited = Date.now() - t0;
  console.log("banner auto-hidden without any interaction: " + hiddenAfterTimeout +
    " (" + totalWaited + " ms after the load was triggered, past showBanner's 12000ms error timer)");

  await browser.close();
}

main();
