// Rim close-up probe: loads the studio, selects the Trial 2 export at
// bonded-courses / 0.4 m, frames the camera on the known rim notch (the
// ±125 degree region domain.WOBBLE_TOLERANCE names, axis roughly
// (1.33, 0)), and screenshots the shell. Used before/after the
// 2026-08-18 rim-rectangular fix; run once per code state, save output
// under a different filename each time.
//
// Modelled on bench/scripts/studio_probe.mjs's own rig (puppeteer-core,
// Brave, window.__studio hook), trimmed to just what a screenshot needs.
//
// Run: node bench/scripts/probe_rim_closeup.mjs <output.png> <label>
// Env: STUDIO_URL (default http://127.0.0.1:8646)

import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const STUDIO_URL = process.env.STUDIO_URL || "http://127.0.0.1:8646";
const BROWSER_EXE = process.env.BROWSER_EXE ||
  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
const OUT = process.argv[2];
const LABEL = process.argv[3] || "probe";

if (!OUT) {
  console.error("usage: node probe_rim_closeup.mjs <output.png> <label>");
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(page, fn, { timeout = 20000, interval = 200 } = {}) {
  const start = Date.now();
  for (;;) {
    const ok = await page.evaluate(fn);
    if (ok) return true;
    if (Date.now() - start > timeout) return false;
    await sleep(interval);
  }
}

async function main() {
  console.log("[" + LABEL + "] launching browser");
  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE,
    headless: true,
    args: ["--use-angle=default"],
    defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("[" + LABEL + "] pageerror: " + e.message));

  try {
    await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
    const hasHook = await waitFor(page, () => !!window.__studio, { timeout: 15000 });
    if (!hasHook) throw new Error("window.__studio never appeared");

    const options = await page.evaluate(() =>
      Array.from(document.getElementById("study-select").options).map((o) => o.value));
    console.log("[" + LABEL + "] study options: " + JSON.stringify(options));
    const target = options.find((o) => o === "Trial 2") || options[0];
    if (!target) throw new Error("no studies available at all");

    await page.evaluate((name) => {
      const select = document.getElementById("study-select");
      select.value = name;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }, target);
    await page.waitForFunction((name) => {
      return window.__studio.state.bundle !== null &&
        window.__studio.state.bundle.export === name &&
        window.__studio.state.objects.shell &&
        window.__studio.state.objects.shell.children.length > 0;
    }, { timeout: 20000 }, target);
    console.log("[" + LABEL + "] study loaded: " + target);

    // pattern: bonded-courses (should already be the default/only real one)
    await page.evaluate(() => {
      const select = document.getElementById("pattern-select");
      if (select.value !== "bonded-courses") {
        select.value = "bonded-courses";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await sleep(300);

    // size: 0.4 m
    await page.evaluate(() => {
      const slider = document.getElementById("size-slider");
      slider.value = "0.4";
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      slider.dispatchEvent(new Event("change", { bubbles: true }));
    });
    // scheduleReload has a settle window; wait for the piece count label
    // (updated once the new bundle lands) and give the shell a beat to
    // rebuild after that.
    await page.waitForFunction(() => {
      const label = document.getElementById("size-value");
      return label && label.textContent === "400";
    }, { timeout: 10000 });
    await sleep(2500);

    const pieceCount = await page.evaluate(() =>
      document.getElementById("piece-count").textContent);
    console.log("[" + LABEL + "] piece-count label: " + pieceCount);

    // Show: switch to Shell (not the default Timeline) so every piece is
    // simply placed and visible, no animation state to wait out.
    await page.evaluate(() => {
      const select = document.getElementById("show-mode");
      select.value = "shell";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await sleep(800);

    // Frame the camera on the real Trial 2 rim notch: axis roughly
    // (1.33, 0), the ±125.4 degree notch this repo's own domain.py names,
    // near world point (-4.8, -8.7). Looking straight down at the rim
    // from a modest height, close enough to read individual piece edges.
    const framed = await page.evaluate(() => {
      const s = window.__studio;
      // The known course-0 notch stretch: true rim vertex near
      // (-4.67, -8.51), the neighbouring outermost-crossing point near
      // (-4.99, -8.89), and the long spike edge running from there past
      // (-3.53, -7.80) toward (-2.88, -5.44) (see diagnosis.md). Framed
      // wide and low, raking along the course direction, so a run of
      // uneven piece lengths reads as a visibly uneven row rather than a
      // single patch.
      const target = { x: -4.0, y: -7.6, z: 0.6 };
      s.camera.position.set(target.x + 6.5, target.y - 4.0, target.z + 3.2);
      s.controls.target.set(target.x, target.y, target.z);
      s.controls.update();
      return { camera: s.camera.position.toArray(), target: s.controls.target.toArray() };
    });
    console.log("[" + LABEL + "] camera framed: " + JSON.stringify(framed));
    await sleep(600);

    await page.screenshot({ path: OUT });
    console.log("[" + LABEL + "] screenshot written: " + OUT);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error("[" + LABEL + "] FAILED: " + error.stack);
  process.exit(1);
});
