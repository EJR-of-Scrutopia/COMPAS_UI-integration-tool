// Task 5 probe (W6 ground tint and scale) against a live studio in
// headless Brave.
//
// Drives the real #ground-preset / #ground-tint / #ground-scale /
// #ground-reset controls (not direct state writes, so the actual input
// listeners + applyGroundAppearance run), and reads the live material
// straight off state.objects.ground.material via window.__studio.
//
// Checks: tint (color.set) and scale (repeat rescaled off the preset's own
// base, both map and roughnessMap) visibly apply to concrete-slab; the
// scale row hides for dark-studio while tint still works; tint/scale
// PERSIST across a preset switch away and back, and across a fresh page
// load (boot's own restoreGroundAppearance); reset restores the preset's
// base colour and repeat and clears the persisted entry.
//
// Run: node bench/scripts/studio_probe_task5.mjs
// Env: STUDIO_URL (default http://127.0.0.1:8643), BROWSER_EXE

import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const STUDIO_URL = process.env.STUDIO_URL || "http://127.0.0.1:8643";
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

async function readGround(page) {
  return page.evaluate(() => {
    const s = window.__studio;
    const material = s.state.objects.ground ? s.state.objects.ground.material : null;
    if (!material) return null;
    return {
      groundPreset: s.state.groundPreset,
      groundAppearance: JSON.parse(JSON.stringify(s.state.groundAppearance)),
      colorHex: "#" + material.color.getHexString(),
      mapRepeat: material.map ? { x: material.map.repeat.x, y: material.map.repeat.y } : null,
      roughnessMapRepeat: material.roughnessMap
        ? { x: material.roughnessMap.repeat.x, y: material.roughnessMap.repeat.y } : null,
      scaleRowHidden: document.getElementById("ground-scale-row").classList.contains("hidden"),
      tintInputValue: document.getElementById("ground-tint").value,
      scaleInputValue: document.getElementById("ground-scale").value,
      storedEntry: localStorage.getItem("bench-studio-ground:" + s.state.groundPreset),
    };
  });
}

async function setGroundPreset(page, value) {
  await page.evaluate((v) => {
    const select = document.getElementById("ground-preset");
    select.value = v;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
}

async function setGroundTint(page, hex) {
  await page.evaluate((v) => {
    const input = document.getElementById("ground-tint");
    input.value = v;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, hex);
}

async function setGroundScale(page, value) {
  await page.evaluate((v) => {
    const slider = document.getElementById("ground-scale");
    slider.value = v;
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

async function clickGroundReset(page) {
  await page.evaluate(() => document.getElementById("ground-reset").click());
}

async function main() {
  log("# Task 5 probe raw report (W6 ground tint and scale)");
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
    const bundleLoaded = await waitFor(page, () =>
      window.__studio.state.bundle !== null && window.__studio.state.objects.ground !== undefined
      && window.__studio.state.objects.ground !== null,
      { timeout: 15000 });
    log("bundle + ground mesh loaded: " + bundleLoaded);
    if (!bundleLoaded) throw new Error("no bundle/ground loaded at boot");

    // ---------- baseline: dark-studio (the boot default) ----------
    currentCheck = "baseline-dark-studio";
    heading("2. Baseline: dark-studio at boot, scale row hidden");
    const bootReading = await readGround(page);
    log("dark-studio at boot: " + JSON.stringify(bootReading));
    log("scale row hidden for dark-studio: " + bootReading.scaleRowHidden);

    // ---------- switch to concrete-slab, read its own base ----------
    currentCheck = "switch-concrete-slab";
    heading("3. Switch to concrete-slab: scale row visible, base colour/repeat");
    await setGroundPreset(page, "concrete-slab");
    await sleep(150);
    const concreteBase = await readGround(page);
    log("concrete-slab base: " + JSON.stringify(concreteBase));
    log("scale row visible for concrete-slab (not hidden): " + !concreteBase.scaleRowHidden);
    await page.screenshot({ path: path.join(PROBE_OUT, "task5-ground-concrete-base.png") });

    // ---------- apply tint and scale ----------
    currentCheck = "apply-tint-scale";
    heading("4. Apply tint #ff2200 and scale 2.5x to concrete-slab");
    await setGroundTint(page, "#ff2200");
    await setGroundScale(page, "2.5");
    await sleep(150);
    const concreteTinted = await readGround(page);
    log("concrete-slab after tint+scale: " + JSON.stringify(concreteTinted));
    await page.screenshot({ path: path.join(PROBE_OUT, "task5-ground-concrete-tinted.png") });
    const expectedMapRepeat = concreteBase.mapRepeat.x * 2.5;
    const expectedRoughRepeat = concreteBase.roughnessMapRepeat.x * 2.5;
    log("expected map repeat at 2.5x: " + expectedMapRepeat + ", actual: " + concreteTinted.mapRepeat.x);
    log("expected roughnessMap repeat at 2.5x: " + expectedRoughRepeat +
      ", actual: " + concreteTinted.roughnessMapRepeat.x);
    log("colour applied (color.set, exact hex): " + (concreteTinted.colorHex === "#ff2200"));
    log("both map slots rescaled from base (not compounded): " +
      (Math.abs(concreteTinted.mapRepeat.x - expectedMapRepeat) < 1e-6 &&
       Math.abs(concreteTinted.roughnessMapRepeat.x - expectedRoughRepeat) < 1e-6));

    // ---------- switch away and back: persistence across a preset switch ----------
    currentCheck = "persist-across-preset-switch";
    heading("5. Switch to dark-studio (tint-only, scale hides) then back to concrete-slab");
    await setGroundPreset(page, "dark-studio");
    await sleep(150);
    const darkAfterSwitch = await readGround(page);
    log("dark-studio after switch (own base colour, no leftover concrete override): " +
      JSON.stringify(darkAfterSwitch));
    log("scale row hidden again for dark-studio: " + darkAfterSwitch.scaleRowHidden);
    await setGroundPreset(page, "concrete-slab");
    await sleep(150);
    const concreteRestored = await readGround(page);
    log("concrete-slab restored after switching back: " + JSON.stringify(concreteRestored));
    log("tint SURVIVED the round trip: " + (concreteRestored.colorHex === "#ff2200"));
    log("scale SURVIVED the round trip: " +
      (Math.abs(concreteRestored.mapRepeat.x - expectedMapRepeat) < 1e-6));

    // ---------- persistence across a fresh boot ----------
    currentCheck = "persist-across-reload";
    heading("6. Reload the page: boot's own restoreGroundAppearance");
    await page.reload({ waitUntil: "networkidle0" });
    await waitFor(page, () => !!window.__studio && window.__studio.state.bundle !== null, { timeout: 15000 });
    await sleep(150);
    // boot defaults groundPreset back to dark-studio; switch to concrete-slab
    // to read its persisted (not-just-in-memory) tint/scale.
    await setGroundPreset(page, "concrete-slab");
    await sleep(150);
    const concreteAfterReload = await readGround(page);
    log("concrete-slab after a fresh page load: " + JSON.stringify(concreteAfterReload));
    log("tint SURVIVED a full reload (read from localStorage): " +
      (concreteAfterReload.colorHex === "#ff2200"));
    log("scale SURVIVED a full reload: " +
      (Math.abs(concreteAfterReload.mapRepeat.x - expectedMapRepeat) < 1e-6));

    // ---------- reset ----------
    currentCheck = "reset";
    heading("7. Reset ground appearance: back to concrete-slab's own base");
    await clickGroundReset(page);
    await sleep(150);
    const concreteAfterReset = await readGround(page);
    log("concrete-slab after reset: " + JSON.stringify(concreteAfterReset));
    log("colour back to base: " + (concreteAfterReset.colorHex === concreteBase.colorHex));
    log("repeat back to base (scale 1x): " +
      (Math.abs(concreteAfterReset.mapRepeat.x - concreteBase.mapRepeat.x) < 1e-6));
    log("localStorage entry cleared: " + (concreteAfterReset.storedEntry === null));
    await page.screenshot({ path: path.join(PROBE_OUT, "task5-ground-concrete-reset.png") });

    writeFileSync(path.join(PROBE_OUT, "task5-ground-readings.json"), JSON.stringify({
      bootReading, concreteBase, concreteTinted, darkAfterSwitch, concreteRestored,
      concreteAfterReload, concreteAfterReset,
    }, null, 2));

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
    writeFileSync(path.join(PROBE_OUT, "task5-probe-report.md"), reportLines.join("\n") + "\n");
    console.log("");
    console.log("Raw report written to " + path.join(PROBE_OUT, "task5-probe-report.md"));
  }
}

main();
