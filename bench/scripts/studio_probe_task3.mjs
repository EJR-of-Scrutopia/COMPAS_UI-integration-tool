// Task 3 probe (W3, big HDRIs): verifies the retry shape in loadHdri
// against a live studio in headless Brave.
//
// Two independent checks:
//   1. A REAL 16K fixture (kloppenheim_06_puresky_16k.hdr, 16384x8192,
//      already present locally under bench/studio/hdri/, gitignored) is
//      loaded unpatched. This is the actual Param-reported failure size
//      class: Float32 RGBA at that resolution is 16384*8192*4*4 =
//      2147483648 bytes, exactly 2^31, right at the ArrayBuffer ceiling
//      that produced his "Array buffer allocation failed" RangeError. If
//      the browser's allocator throws there, the retry should recover
//      silently at half float; if it does not throw (a more generous
//      allocator), the float path itself should simply succeed. Either
//      outcome is logged; only the browser's own decision distinguishes
//      them, not this script.
//   2. A MONKEYPATCHED double failure: Float32Array and Uint16Array are
//      temporarily wrapped so any allocation above a small threshold
//      throws a synthetic RangeError, then a small real fixture
//      (hdri0.hdr) is loaded through the unmodified loadHdri code. This
//      forces both the float and half-float attempts to fail
//      deterministically and cheaply, proving the double-failure banner
//      path (header-read megapixels, ceiling wording) actually runs,
//      independent of whether check 1 above ever reproduces a real
//      allocator failure on this machine.
//
// Run: node bench/scripts/studio_probe_task3.mjs
// Env: STUDIO_URL (default http://127.0.0.1:8642), BROWSER_EXE

import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const STUDIO_URL = process.env.STUDIO_URL || "http://127.0.0.1:8642";
const BROWSER_EXE = process.env.BROWSER_EXE ||
  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
const PROBE_OUT = path.join(REPO_ROOT, ".superpowers", "sdd", "2026-08-17-studio-tweaks", "captures");
mkdirSync(PROBE_OUT, { recursive: true });

const reportLines = [];
const consoleErrors = [];
let currentCheck = "boot";

function log(line) { console.log(line); reportLines.push(line); }
function heading(text) { log(""); log("## " + text); }
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

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
  log("# Task 3 probe raw report (W3, big HDRIs)");
  log("");
  log("STUDIO_URL: " + STUDIO_URL);
  log("timestamp: " + new Date().toISOString());

  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE,
    headless: true,
    args: ["--use-angle=default"],
    defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push({ check: currentCheck, text: msg.text() });
  });
  page.on("pageerror", (error) => {
    consoleErrors.push({ check: currentCheck, text: "pageerror: " + error.message });
  });

  try {
    currentCheck = "boot";
    heading("1. Boot");
    await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
    const hasHook = await waitFor(page, () => !!window.__studio, { timeout: 10000 });
    log("window.__studio present: " + hasHook);
    if (!hasHook) throw new Error("window.__studio never appeared; boot failed");

    currentCheck = "hdri-mode";
    heading("2. Switch to hdri mode, list files");
    await page.evaluate(() => {
      const select = document.getElementById("environment-mode");
      select.value = "hdri";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await sleep(400);
    const files = await page.evaluate(() =>
      Array.from(document.getElementById("hdri-select").options).map((o) => o.value));
    log("hdri files listed by the server: " + JSON.stringify(files));
    const has16k = files.includes("kloppenheim_06_puresky_16k.hdr");
    const hasSmall = files.includes("hdri0.hdr");
    log("kloppenheim_06_puresky_16k.hdr present: " + has16k);
    log("hdri0.hdr present: " + hasSmall);
    if (!has16k || !hasSmall) throw new Error("expected local fixtures missing from bench/studio/hdri/");

    // ---------- CHECK 1: real 16K fixture, unpatched ----------
    currentCheck = "real-16k";
    heading("3. Real 16K fixture (kloppenheim_06_puresky_16k.hdr), unpatched code path");
    const t0 = Date.now();
    await page.evaluate(() => {
      const select = document.getElementById("hdri-select");
      select.value = "kloppenheim_06_puresky_16k.hdr";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const settled16k = await waitFor(page, () => {
      const s = window.__studio.state;
      const statusText = document.getElementById("hdri-status").textContent;
      const bannerVisible = !document.getElementById("banner").classList.contains("hidden");
      return statusText === "" && (s.hdriName === "kloppenheim_06_puresky_16k.hdr" || bannerVisible);
    }, { timeout: 180000, interval: 500 });
    const elapsedMs = Date.now() - t0;
    log("settled: " + settled16k + " after " + elapsedMs + " ms");
    const result16k = await page.evaluate(() => {
      const s = window.__studio.state;
      const tex = s.hdriTexture;
      return {
        hdriName: s.hdriName,
        textureType: tex ? tex.type : null, // 1015 = FloatType, 1016 = HalfFloatType
        dataCtor: tex && tex.image && tex.image.data ? tex.image.data.constructor.name : null,
        imageWidth: tex && tex.image ? tex.image.width : null,
        imageHeight: tex && tex.image ? tex.image.height : null,
        sceneEnvironmentPresent: !!window.__studio.scene.environment,
        sceneEnvironmentType: window.__studio.scene.environment ? window.__studio.scene.environment.type : null,
        sceneBackground: window.__studio.scene.background ? "set" : null,
        bannerText: document.getElementById("banner-text").textContent,
        bannerHidden: document.getElementById("banner").classList.contains("hidden"),
        eventLog: document.getElementById("event-log").textContent,
      };
    });
    log("result: " + JSON.stringify(result16k, null, 2));
    log("FloatType=1015, HalfFloatType=1016");
    const retriedHalf = result16k.eventLog.includes("overflowed float32");
    log("event log shows a float32 overflow + retry: " + retriedHalf);
    if (retriedHalf) {
      log("=> the browser's real allocator threw on the Float32 attempt (2^31 bytes) and the code " +
        "silently recovered at half float, exactly Param's reported failure and its fix.");
    } else if (result16k.hdriName === "kloppenheim_06_puresky_16k.hdr" && result16k.textureType === 1015) {
      log("=> this browser/build's allocator did not throw on the 2 GB Float32 array; the float " +
        "path itself succeeded, so the retry branch was not exercised by this run.");
    }
    writeFileSync(path.join(PROBE_OUT, "task3-real-16k-result.json"), JSON.stringify(result16k, null, 2));

    // Screenshot the hdri backdrop so the projected dome/backdrop can be
    // eyeballed as sane (not black, not corrupted) with a real half-float
    // texture through PMREM.
    await sleep(300);
    await page.screenshot({ path: path.join(PROBE_OUT, "task3-real-16k-backdrop.png") });
    log("screenshot: task3-real-16k-backdrop.png");

    // ---------- CHECK 2: monkeypatched double failure ----------
    currentCheck = "monkeypatch-double-failure";
    heading("4. Monkeypatched double failure (hdri0.hdr, both attempts forced to RangeError)");
    await page.evaluate(() => {
      const THRESHOLD = 500000; // elements; hdri0.hdr's decode needs tens of millions
      function wrap(Orig, label) {
        return new Proxy(Orig, {
          construct(target, args) {
            const len = typeof args[0] === "number" ? args[0] : (args[0] && args[0].length) || 0;
            if (len > THRESHOLD) {
              throw new RangeError("Array buffer allocation failed (task3 probe monkeypatch, " +
                label + ", len=" + len + ")");
            }
            return Reflect.construct(target, args);
          },
        });
      }
      window.__probeOriginalFloat32Array = window.Float32Array;
      window.__probeOriginalUint16Array = window.Uint16Array;
      window.Float32Array = wrap(window.Float32Array, "Float32Array");
      window.Uint16Array = wrap(window.Uint16Array, "Uint16Array");
    });
    const beforeName = await page.evaluate(() => window.__studio.state.hdriName);
    await page.evaluate(() => {
      const select = document.getElementById("hdri-select");
      select.value = "hdri0.hdr";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const settledPatched = await waitFor(page, () => {
      const statusText = document.getElementById("hdri-status").textContent;
      const bannerVisible = !document.getElementById("banner").classList.contains("hidden");
      return statusText === "" && bannerVisible;
    }, { timeout: 20000, interval: 200 });
    log("settled (banner visible): " + settledPatched);
    const resultPatched = await page.evaluate(() => ({
      hdriName: window.__studio.state.hdriName,
      bannerText: document.getElementById("banner-text").textContent,
      bannerHidden: document.getElementById("banner").classList.contains("hidden"),
      eventLog: document.getElementById("event-log").textContent,
    }));
    await page.evaluate(() => {
      window.Float32Array = window.__probeOriginalFloat32Array;
      window.Uint16Array = window.__probeOriginalUint16Array;
      delete window.__probeOriginalFloat32Array;
      delete window.__probeOriginalUint16Array;
    });
    log("state.hdriName before: " + beforeName + ", after failed hdri0.hdr load: " + resultPatched.hdriName);
    log("hdriName unchanged by the failed load: " + (beforeName === resultPatched.hdriName));
    log("banner text: " + JSON.stringify(resultPatched.bannerText));
    const hasImageTooLarge = resultPatched.bannerText.includes("image too large:");
    const hasCeiling = resultPatched.bannerText.includes("practical ceiling is around");
    const hasMP = /\d+ MP/.test(resultPatched.bannerText);
    log("banner names 'image too large:': " + hasImageTooLarge);
    log("banner names the practical ceiling: " + hasCeiling);
    log("banner includes at least one 'N MP' figure: " + hasMP);
    // hdri0.hdr's real header is 1792x3584 = 6,422,528 px = 6.42 MP.
    log("banner mentions hdri0.hdr's true size (6 MP, from a header-only read, not the failed decode): " +
      resultPatched.bannerText.includes("6 MP"));
    writeFileSync(path.join(PROBE_OUT, "task3-monkeypatch-result.json"), JSON.stringify(resultPatched, null, 2));

    // Sanity: a real, unpatched small file still loads fine afterwards
    // (the monkeypatch restore actually worked, and loadHdri recovers
    // cleanly after a prior failure -- the "stuck banner" concern from
    // the brief's context).
    currentCheck = "post-patch-sanity";
    heading("5. Sanity: hdri0.hdr loads for real once the monkeypatch is removed");
    await page.evaluate(() => {
      const select = document.getElementById("hdri-select");
      select.value = "hdri0.hdr";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const settledSanity = await waitFor(page, () =>
      window.__studio.state.hdriName === "hdri0.hdr" &&
      document.getElementById("hdri-status").textContent === "",
      { timeout: 30000, interval: 300 });
    log("hdri0.hdr loaded for real after restoring the constructors: " + settledSanity);
    const bannerNowHidden = await page.evaluate(() =>
      document.getElementById("banner").classList.contains("hidden"));
    log("banner is hidden again after a subsequent successful load (not stuck): " + bannerNowHidden);

  } catch (error) {
    log("");
    log("## PROBE ERROR");
    log(String(error && error.stack ? error.stack : error));
  } finally {
    heading("Console errors captured, by check");
    if (consoleErrors.length === 0) {
      log("(none)");
    } else {
      for (const entry of consoleErrors) log("[" + entry.check + "] " + entry.text);
    }
    await browser.close();
    writeFileSync(path.join(PROBE_OUT, "task3-probe-report.md"), reportLines.join("\n") + "\n");
    console.log("");
    console.log("Raw report written to " + path.join(PROBE_OUT, "task3-probe-report.md"));
  }
}

main();
