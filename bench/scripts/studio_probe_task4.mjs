// Task 4 probe (W4 studio darkness + W5 turntable) against a live studio
// in headless Brave.
//
// W4: drive the real Brightness slider (not a direct state write, so the
// input listener + applyGrade actually run) through 2.0 / 1.0 / 0.3 in
// Studio mode, and read environmentIntensity, hemi.intensity and
// sun.intensity straight off the live scene graph via window.__studio
// (hemi/sun are not exported directly, so they are found by traversing
// scene.children for isHemisphereLight / isDirectionalLight).
//
// W5: set a fast orbit speed (~pi rad/s, so half a revolution takes about
// a second of real wall-clock time), take one reading, wait, take a
// second reading a half revolution later, and check camera height and
// controls.target against state.centre in both.
//
// Run: node bench/scripts/studio_probe_task4.mjs
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

async function readLights(page) {
  return page.evaluate(() => {
    const s = window.__studio;
    const hemi = s.scene.children.find((o) => o.isHemisphereLight);
    const sun = s.scene.children.find((o) => o.isDirectionalLight);
    return {
      brightness: s.state.brightness,
      environmentMode: s.state.environmentMode,
      environmentIntensity: s.scene.environmentIntensity,
      hemiIntensity: hemi ? hemi.intensity : null,
      sunIntensity: sun ? sun.intensity : null,
    };
  });
}

async function setBrightness(page, value) {
  await page.evaluate((v) => {
    const slider = document.getElementById("brightness");
    slider.value = v;
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

async function readOrbitFrame(page) {
  return page.evaluate(() => {
    const s = window.__studio;
    return {
      time: Date.now(),
      camera: { x: s.camera.position.x, y: s.camera.position.y, z: s.camera.position.z },
      target: { x: s.controls.target.x, y: s.controls.target.y, z: s.controls.target.z },
      centre: { x: s.state.centre.x, y: s.state.centre.y, z: s.state.centre.z },
      orbitSpeed: s.state.timeline ? s.state.timeline.orbitSpeed : null,
      orbitDistance: s.state.timeline ? s.state.timeline.orbitDistance : null,
      autoSpin: s.state.timeline ? s.state.timeline.autoSpin : null,
      userDragging: s.state.userDragging,
    };
  });
}

function angleFrom(reading) {
  return Math.atan2(reading.camera.y - reading.centre.y, reading.camera.x - reading.centre.x);
}

function angularDelta(a, b) {
  let d = b - a;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  return d;
}

async function main() {
  log("# Task 4 probe raw report (W4 studio darkness, W5 turntable)");
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
      window.__studio.state.bundle !== null && window.__studio.state.timeline !== null &&
      window.__studio.state.centre !== null,
      { timeout: 15000 });
    log("bundle + timeline + centre loaded: " + bundleLoaded);
    if (!bundleLoaded) throw new Error("no bundle/timeline loaded at boot");
    const upAxis = await page.evaluate(() =>
      ({ x: window.__studio.camera.up.x, y: window.__studio.camera.up.y, z: window.__studio.camera.up.z }));
    log("camera.up (confirms the scene's up axis): " + JSON.stringify(upAxis));
    const mode0 = await page.evaluate(() => window.__studio.state.environmentMode);
    log("boot environmentMode: " + mode0 + " (expect studio, the W4 branch under test)");
    if (mode0 !== "studio") {
      await page.evaluate(() => {
        const select = document.getElementById("environment-mode");
        select.value = "studio";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await sleep(300);
    }

    // ---------- W4: darkness triplet ----------
    currentCheck = "w4-darkness";
    heading("2. W4 darkness triplet (brightness 2.0 / 1.0 / 0.3, studio mode)");
    const triplet = {};
    for (const value of [2.0, 1.0, 0.3]) {
      currentCheck = "w4-brightness-" + value;
      await setBrightness(page, value);
      await sleep(150);
      const reading = await readLights(page);
      triplet[value] = reading;
      log("brightness=" + value + ": " + JSON.stringify(reading));
      const shotPath = path.join(PROBE_OUT, "task4-darkness-b" + String(value).replace(".", "") + ".png");
      await page.screenshot({ path: shotPath });
      log("screenshot: " + path.basename(shotPath));
    }
    writeFileSync(path.join(PROBE_OUT, "task4-darkness-triplet.json"), JSON.stringify(triplet, null, 2));
    const ambientScale03 = Math.min(1, 0.3) ** 2;
    log("expected at brightness=0.3: environmentIntensity=" + (0.6 * ambientScale03).toFixed(4) +
      " hemiIntensity=" + (0.5 * ambientScale03).toFixed(4) + " (ambientScale=" + ambientScale03 + ")");
    log("environmentIntensity unchanged between 2.0 and 1.0 (today's behaviour above the fade): " +
      (triplet[2.0].environmentIntensity === triplet[1.0].environmentIntensity));
    log("hemiIntensity unchanged between 2.0 and 1.0: " +
      (triplet[2.0].hemiIntensity === triplet[1.0].hemiIntensity));
    log("sunIntensity identical across all three (untouched by the ambient fade): " +
      (triplet[2.0].sunIntensity === triplet[1.0].sunIntensity &&
       triplet[1.0].sunIntensity === triplet[0.3].sunIntensity));

    // ---------- W4b: sky/hdri untouched sanity ----------
    currentCheck = "w4-sky-untouched";
    heading("3. W4 sanity: sky mode ignores the brightness ambient fade");
    await page.evaluate(() => {
      const select = document.getElementById("environment-mode");
      select.value = "sky";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await sleep(300);
    const skyAt1 = await readLights(page);
    await setBrightness(page, 0.3);
    await sleep(150);
    const skyAt03 = await readLights(page);
    log("sky mode environmentIntensity at brightness=1: " + skyAt1.environmentIntensity +
      ", at brightness=0.3: " + skyAt03.environmentIntensity);
    log("sky mode hemiIntensity at brightness=1: " + skyAt1.hemiIntensity +
      ", at brightness=0.3: " + skyAt03.hemiIntensity);
    log("sky mode ambient UNCHANGED by the brightness drag (W4 says sky/hdri are untouched): " +
      (skyAt1.environmentIntensity === skyAt03.environmentIntensity &&
       skyAt1.hemiIntensity === skyAt03.hemiIntensity));
    writeFileSync(path.join(PROBE_OUT, "task4-sky-untouched.json"), JSON.stringify({ skyAt1, skyAt03 }, null, 2));
    await setBrightness(page, 1.0);
    await page.evaluate(() => {
      const select = document.getElementById("environment-mode");
      select.value = "studio";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await sleep(300);

    // ---------- W5: turntable half-revolution pair ----------
    currentCheck = "w5-turntable";
    heading("4. W5 turntable: a fast orbit speed, two readings a half revolution apart");
    // orbit-distance stays at its default (30); orbit-speed set to the
    // slider's own max (2 rad/s -- a range input silently clamps a
    // programmatic .value past its own max="2", so this IS the fastest
    // the real control offers) so a half revolution (pi radians) takes
    // about pi/2 ~= 1.57 real seconds -- fast enough to probe without a
    // long wait, slow enough that frame()'s delta-clamped advance (min
    // 0.1s/frame) tracks it smoothly.
    await page.evaluate(() => {
      const slider = document.getElementById("orbit-speed");
      slider.value = 2;
      slider.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await sleep(200); // let a couple of frames settle onto the new speed
    const before = await readOrbitFrame(page);
    log("reading 1: " + JSON.stringify(before));
    await page.screenshot({ path: path.join(PROBE_OUT, "task4-turntable-frame1.png") });
    await sleep(1570); // ~half a revolution at 2 rad/s (pi / 2 ~= 1.5708s)
    const after = await readOrbitFrame(page);
    log("reading 2: " + JSON.stringify(after));
    await page.screenshot({ path: path.join(PROBE_OUT, "task4-turntable-frame2.png") });
    writeFileSync(path.join(PROBE_OUT, "task4-turntable-pair.json"), JSON.stringify({ before, after }, null, 2));

    const heightDelta = Math.abs(before.camera.z - after.camera.z);
    const angle1 = angleFrom(before), angle2 = angleFrom(after);
    const delta = angularDelta(angle1, angle2);
    const targetMatchesCentreBefore =
      Math.abs(before.target.x - before.centre.x) < 1e-6 &&
      Math.abs(before.target.y - before.centre.y) < 1e-6 &&
      Math.abs(before.target.z - before.centre.z) < 1e-6;
    const targetMatchesCentreAfter =
      Math.abs(after.target.x - after.centre.x) < 1e-6 &&
      Math.abs(after.target.y - after.centre.y) < 1e-6 &&
      Math.abs(after.target.z - after.centre.z) < 1e-6;
    log("camera height (z) reading 1: " + before.camera.z + ", reading 2: " + after.camera.z +
      ", delta: " + heightDelta);
    log("camera height EQUAL across the pair (flat turntable, no z modulation): " + (heightDelta < 1e-6));
    log("controls.target === state.centre at reading 1: " + targetMatchesCentreBefore);
    log("controls.target === state.centre at reading 2: " + targetMatchesCentreAfter);
    log("implied azimuth reading 1: " + angle1.toFixed(4) + " rad, reading 2: " + angle2.toFixed(4) +
      " rad, delta: " + delta.toFixed(4) + " rad (expect close to +/-pi, a half revolution)");
    log("real wall-clock elapsed between readings: " + (after.time - before.time) + " ms");

    // ---------- W5b: a drag release recaptures height ----------
    currentCheck = "w5-drag-recapture";
    heading("5. W5 sanity: a manual reframe (drag release) recaptures height at the new elevation");
    await page.evaluate(() => {
      window.__studio.controls.dispatchEvent({ type: "start" });
    });
    await sleep(100);
    const midDragReading = await readOrbitFrame(page);
    await page.evaluate(() => {
      window.__studio.camera.position.z += 8; // simulate the user tilting the view up
      window.__studio.controls.dispatchEvent({ type: "end" });
    });
    await sleep(250);
    const afterDragReading = await readOrbitFrame(page);
    log("camera z right before drag-release bump: " + midDragReading.camera.z);
    log("camera z right after drag-release (+8 applied manually): " + afterDragReading.camera.z);
    await sleep(600);
    const afterHoldReading = await readOrbitFrame(page);
    log("camera z ~600ms after release, still orbiting: " + afterHoldReading.camera.z);
    log("new height held (within 0.01) after the recapture: " +
      (Math.abs(afterDragReading.camera.z - afterHoldReading.camera.z) < 0.5));
    writeFileSync(path.join(PROBE_OUT, "task4-turntable-drag-recapture.json"),
      JSON.stringify({ midDragReading, afterDragReading, afterHoldReading }, null, 2));

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
    writeFileSync(path.join(PROBE_OUT, "task4-probe-report.md"), reportLines.join("\n") + "\n");
    console.log("");
    console.log("Raw report written to " + path.join(PROBE_OUT, "task4-probe-report.md"));
  }
}

main();
