// Task 1 probe (W1 ghost + staircase diagnosis): reproduces Param's
// screenshot state -- a real export, timber material, timeline mid-build --
// and reads scene numbers via window.__studio to identify (a) the dark
// ghost surface and (b) the airborne block ribbon.
// Run: node bench/scripts/studio_probe_task1.mjs
// Env: STUDIO_URL (default http://127.0.0.1:8641), BROWSER_EXE, PROBE_OUT.

import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");

const STUDIO_URL = process.env.STUDIO_URL || "http://127.0.0.1:8641";
const BROWSER_EXE = process.env.BROWSER_EXE ||
  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
const PROBE_OUT = process.env.PROBE_OUT ||
  path.join(REPO_ROOT, ".superpowers", "sdd", "2026-08-17-studio-tweaks");
const CAPTURE_DIR = path.join(PROBE_OUT, "captures");
mkdirSync(CAPTURE_DIR, { recursive: true });

const reportLines = [];
function log(line) { console.log(line); reportLines.push(line); }
function heading(text) { log(""); log("## " + text); }
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function waitFor(page, fn, { timeout = 15000, interval = 200, arg } = {}) {
  const start = Date.now();
  for (;;) {
    const ok = await page.evaluate(fn, arg);
    if (ok) return true;
    if (Date.now() - start > timeout) return false;
    await sleep(interval);
  }
}

async function setSelect(page, id, value) {
  await page.evaluate((elementId, v) => {
    const select = document.getElementById(elementId);
    select.value = v;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, id, value);
}

async function scrubTo(page, value) {
  await page.evaluate((v) => {
    const scrubber = document.getElementById("timeline-scrubber");
    scrubber.value = v;
    scrubber.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

async function main() {
  log("# Task 1 probe report (W1 ghost + staircase)");
  log("STUDIO_URL: " + STUDIO_URL);
  log("timestamp: " + new Date().toISOString());

  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE,
    headless: true,
    args: ["--use-angle=default"],
    defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
  page.on("pageerror", (error) => consoleErrors.push("pageerror: " + error.message));

  try {
    heading("1. Boot");
    await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
    const hasHook = await waitFor(page, () => !!window.__studio, { timeout: 10000 });
    log("window.__studio present: " + hasHook);
    if (!hasHook) throw new Error("boot failed");

    heading("2. Load a real export (Algebraic TNA method), timber material");
    await setSelect(page, "study-select", "Algebraic TNA method");
    await waitFor(page, () =>
      window.__studio.state.bundle && window.__studio.state.bundle.export === "Algebraic TNA method",
      { timeout: 20000 });
    await setSelect(page, "material-select", "timber");
    await waitFor(page, () =>
      window.__studio.state.bundle && window.__studio.state.bundle.material === "timber" &&
      window.__studio.state.objects.shell && window.__studio.state.objects.shell.children.length > 0,
      { timeout: 20000 });
    const loaded = await page.evaluate(() => ({
      export: window.__studio.state.bundle.export,
      material: window.__studio.state.bundle.material,
      pieceCount: window.__studio.state.bundle.pieces.length,
      courses: window.__studio.state.bundle.tessellation.courses,
      formworkModeAfterLoad: window.__studio.state.formworkMode,
      showModeAfterLoad: window.__studio.state.showMode,
    }));
    log("loaded: " + JSON.stringify(loaded));

    heading("3. Default-state check: formwork mode untouched, scrub to two-thirds");
    const durationInfo = await page.evaluate(() => {
      const s = window.__studio.state;
      return { inflateSeconds: s.timeline.inflateSeconds, t: s.timeline.t };
    });
    log("timeline before scrub: " + JSON.stringify(durationInfo));
    await scrubTo(page, 667);
    await sleep(300);
    const afterScrub = await page.evaluate(() => {
      const s = window.__studio.state;
      const f = s.objects.falsework;
      return {
        t: s.timeline.t,
        formworkMode: s.formworkMode,
        showMode: s.showMode,
        falsework: f ? {
          visible: f.visible,
          opacity: f.material.opacity,
          transparent: f.material.transparent,
          z: f.position.z,
          colorHex: "#" + f.material.color.getHexString(),
        } : null,
      };
    });
    log("DEFAULT state (formwork untouched) at t=" + afterScrub.t + ": " + JSON.stringify(afterScrub));
    await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-default-hidden-before.png") });
    log("screenshot: task1-default-hidden-before.png");

    heading("4. Reproduce with Formwork=Animation (the plausible ghost cause)");
    await setSelect(page, "formwork-mode", "animation");
    await sleep(200);
    const animationState = await page.evaluate(() => {
      const s = window.__studio.state;
      const f = s.objects.falsework;
      return {
        t: s.timeline.t,
        formworkMode: s.formworkMode,
        showMode: s.showMode,
        falsework: f ? {
          visible: f.visible,
          opacity: f.material.opacity,
          transparent: f.material.transparent,
          z: f.position.z,
          colorHex: "#" + f.material.color.getHexString(),
        } : null,
      };
    });
    log("ANIMATION mode at t=" + animationState.t + ": " + JSON.stringify(animationState));
    await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-animation-mode-ghost.png") });
    log("screenshot: task1-animation-mode-ghost.png");

    heading("5. Reproduce with Formwork=Always (the other ghost candidate)");
    await setSelect(page, "formwork-mode", "always");
    await sleep(200);
    const alwaysState = await page.evaluate(() => {
      const s = window.__studio.state;
      const f = s.objects.falsework;
      return {
        t: s.timeline.t,
        formworkMode: s.formworkMode,
        falsework: f ? {
          visible: f.visible,
          opacity: f.material.opacity,
          z: f.position.z,
        } : null,
      };
    });
    log("ALWAYS mode at t=" + alwaysState.t + ": " + JSON.stringify(alwaysState));
    await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-always-mode-ghost.png") });
    log("screenshot: task1-always-mode-ghost.png");

    // Restore to hidden/default for the ribbon investigation below.
    await setSelect(page, "formwork-mode", "hidden");
    await sleep(150);

    heading("6. Ribbon scan: in-flight blocks at t=" + afterScrub.t);
    const ribbonScan = await page.evaluate(() => {
      const s = window.__studio.state;
      const DROP_HEIGHT = 12, DROP_SECONDS = 0.8, STRIKE_SECONDS = 2, BUILD_TARGET_SECONDS = 35;
      const t = s.timeline.t;
      const build = Math.max(0, t - s.timeline.inflateSeconds);
      const placementCount = s.bundle.pieces.length;
      const step = BUILD_TARGET_SECONDS / Math.max(1, placementCount);
      const rows = [];
      let visibleCount = 0, inFlightCount = 0, landedCount = 0;
      let crownRestZ = -Infinity;
      for (const seg of s.objects.shell.children) {
        const centreZ = seg.userData.centreZ;
        if (typeof centreZ === "number") crownRestZ = Math.max(crownRestZ, centreZ);
      }
      for (const seg of s.objects.shell.children) {
        if (!seg.visible) continue;
        visibleCount++;
        const key = seg.userData.key;
        const entry = s.segmentIndex.get(key);
        const start = entry.order * step;
        const u = Math.min(1, Math.max(0, (build - start) / DROP_SECONDS));
        const worldZ = (seg.userData.centreZ || 0) + seg.position.z;
        if (u < 1) inFlightCount++; else landedCount++;
        rows.push({
          key, course: entry.course, order: entry.order, start,
          u, restZ: seg.userData.centreZ, dropOffset: seg.position.z, worldZ,
          aboveCrownRest: worldZ > crownRestZ,
        });
      }
      // Sort by worldZ descending to surface the highest-flying blocks.
      rows.sort((a, b) => b.worldZ - a.worldZ);
      return {
        build, step, placementCount, crownRestZ,
        visibleCount, inFlightCount, landedCount,
        top10ByWorldZ: rows.slice(0, 10),
      };
    });
    log("ribbon scan summary: build=" + ribbonScan.build.toFixed(4) +
      " step=" + ribbonScan.step.toFixed(6) +
      " placementCount=" + ribbonScan.placementCount +
      " crownRestZ=" + ribbonScan.crownRestZ.toFixed(4) +
      " visible=" + ribbonScan.visibleCount +
      " inFlight=" + ribbonScan.inFlightCount +
      " landed=" + ribbonScan.landedCount);
    log("top 10 highest-worldZ visible blocks (should be near-crown rest or genuinely in-flight):");
    for (const row of ribbonScan.top10ByWorldZ) {
      log("  key=" + row.key + " course=" + row.course + " order=" + row.order +
        " start=" + row.start.toFixed(3) + " u=" + row.u.toFixed(3) +
        " restZ=" + (row.restZ !== undefined ? row.restZ.toFixed(3) : "?") +
        " dropOffset=" + row.dropOffset.toFixed(3) +
        " worldZ=" + row.worldZ.toFixed(3) +
        " aboveCrownRest=" + row.aboveCrownRest);
    }
    writeFileSync(path.join(CAPTURE_DIR, "task1-ribbon-scan.json"), JSON.stringify(ribbonScan, null, 2));

    heading("7. Course-window scan: are simultaneously in-flight blocks spatially contiguous?");
    const courseWindow = await page.evaluate(() => {
      const s = window.__studio.state;
      const DROP_SECONDS = 0.8, BUILD_TARGET_SECONDS = 35;
      const t = s.timeline.t;
      const build = Math.max(0, t - s.timeline.inflateSeconds);
      const placementCount = s.bundle.pieces.length;
      const step = BUILD_TARGET_SECONDS / Math.max(1, placementCount);
      const inFlight = [];
      for (const seg of s.objects.shell.children) {
        if (!seg.visible) continue;
        const entry = s.segmentIndex.get(seg.userData.key);
        const start = entry.order * step;
        const u = Math.min(1, Math.max(0, (build - start) / DROP_SECONDS));
        if (u < 1) {
          inFlight.push({
            key: seg.userData.key, course: entry.course, order: entry.order, u,
            worldZ: (seg.userData.centreZ || 0) + seg.position.z,
          });
        }
      }
      const courses = [...new Set(inFlight.map((r) => r.course))].sort((a, b) => a - b);
      return { inFlightTotal: inFlight.length, distinctCoursesInFlight: courses, sample: inFlight.slice(0, 60) };
    });
    log("in-flight total=" + courseWindow.inFlightTotal +
      " distinct courses in flight=" + JSON.stringify(courseWindow.distinctCoursesInFlight));
    writeFileSync(path.join(CAPTURE_DIR, "task1-course-window.json"), JSON.stringify(courseWindow, null, 2));

    heading("8. Wide-angle capture at Param's viewpoint (below/inside looking up)");
    // Approximate Param's screenshot framing: camera pulled back and low,
    // looking up into the vault, to catch both the under-shell ghost and
    // any airborne blocks against the sky.
    await scrubTo(page, 667);
    await sleep(300);
    await page.evaluate(() => {
      const c = window.__studio.state.centre || { x: 0, y: 0, z: 0 };
      window.__studio.camera.position.set(c.x + 6, c.y - 10, c.z + 2);
      window.__studio.camera.lookAt(c.x, c.y, c.z + 3);
    });
    await sleep(150);
    await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-lowangle-default.png") });
    log("screenshot: task1-lowangle-default.png (default hidden formwork, mid-build, low-angle)");

    await setSelect(page, "formwork-mode", "animation");
    await sleep(200);
    await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-lowangle-animation.png") });
    log("screenshot: task1-lowangle-animation.png (animation formwork, mid-build, low-angle)");
    await setSelect(page, "formwork-mode", "hidden");
    await sleep(150);

  } catch (error) {
    log("");
    log("## PROBE ERROR");
    log(String(error && error.stack ? error.stack : error));
  } finally {
    heading("Console errors");
    if (consoleErrors.length === 0) log("(none)");
    else for (const e of consoleErrors) log(e);
    await browser.close();
    writeFileSync(path.join(CAPTURE_DIR, "task1-probe-report.md"), reportLines.join("\n") + "\n");
    console.log("");
    console.log("Report: " + path.join(CAPTURE_DIR, "task1-probe-report.md"));
  }
}

main();
