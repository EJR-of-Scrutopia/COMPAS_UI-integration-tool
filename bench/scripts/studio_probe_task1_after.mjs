// Task 1 AFTER capture: re-run the exact reproduction scenarios against
// the real (fixed) studio.js source -- no live patching -- to confirm both
// fixes land for real, not just in a probe-side monkeypatch.
import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const CAPTURE_DIR = path.join(REPO_ROOT, ".superpowers", "sdd", "2026-08-17-studio-tweaks", "captures");
const STUDIO_URL = "http://127.0.0.1:8641";
const BROWSER_EXE = "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function waitFor(page, fn, { timeout = 15000, interval = 200 } = {}) {
  const start = Date.now();
  for (;;) { if (await page.evaluate(fn)) return true; if (Date.now() - start > timeout) return false; await sleep(interval); }
}

const reportLines = [];
function log(line) { console.log(line); reportLines.push(line); }

async function main() {
  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE, headless: true,
    args: ["--use-angle=default"], defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
  await waitFor(page, () => !!window.__studio, { timeout: 10000 });
  await page.evaluate(() => {
    const s = document.getElementById("study-select");
    s.value = "Algebraic TNA method";
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await waitFor(page, () => window.__studio.state.bundle && window.__studio.state.bundle.export === "Algebraic TNA method", { timeout: 20000 });
  await page.evaluate(() => {
    const s = document.getElementById("material-select");
    s.value = "timber";
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await waitFor(page, () => window.__studio.state.bundle && window.__studio.state.bundle.material === "timber" && window.__studio.state.objects.shell.children.length > 0, { timeout: 20000 });

  // ---------- Ghost: same scenario as task1b-scrub250-* ----------
  await page.evaluate(() => {
    const sc = document.getElementById("timeline-scrubber");
    sc.value = 250;
    sc.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await sleep(200);
  await page.evaluate(() => {
    const c = window.__studio.state.centre;
    window.__studio.camera.position.set(c.x + 14, c.y - 14, c.z + 6);
    window.__studio.camera.lookAt(c.x, c.y, c.z + 1.5);
  });
  await sleep(150);
  const wireReading = await page.evaluate(() => {
    const wm = window.__studio.state.objects.wires.material;
    const nm = window.__studio.state.objects.nodes.material;
    return {
      wireVertexColors: wm.vertexColors, wireColor: "#" + wm.color.getHexString(),
      wireMetalness: wm.metalness, wireRoughness: wm.roughness,
      nodeVertexColors: nm.vertexColors,
      formworkMode: window.__studio.state.formworkMode,
    };
  });
  log("AFTER-fix wire/node material at scrub250: " + JSON.stringify(wireReading));
  await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-AFTER-ghost-scrub250-hidden.png") });
  log("screenshot: task1-AFTER-ghost-scrub250-hidden.png");

  // Framework mode alone (net with no build state), matching task1d before.
  await page.evaluate(() => {
    const s = document.getElementById("show-mode");
    s.value = "framework";
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await sleep(250);
  await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-AFTER-framework-mode-net-alone.png") });
  log("screenshot: task1-AFTER-framework-mode-net-alone.png");
  await page.evaluate(() => {
    const s = document.getElementById("show-mode");
    s.value = "timeline";
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await sleep(150);

  // Wire-forces layer still works (regression check on the toggle fix).
  await page.evaluate(() => {
    const scrubber = document.getElementById("timeline-scrubber");
    scrubber.value = 1000;
    scrubber.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await sleep(200);
  const forcesCheck = await page.evaluate(() => {
    const labels = Array.from(document.querySelectorAll("#layer-toggles label"));
    const boxes = Array.from(document.querySelectorAll('#layer-toggles input[type="checkbox"]'));
    const idx = labels.findIndex((l) => l.textContent.toLowerCase().includes("wire forces"));
    if (idx < 0) return { found: false };
    boxes[idx].checked = true;
    boxes[idx].dispatchEvent(new Event("change", { bubbles: true }));
    return { found: true, disabled: boxes[idx].disabled };
  });
  await sleep(200);
  const afterForcesOn = await page.evaluate(() => {
    const wm = window.__studio.state.objects.wires.material;
    return { vertexColors: wm.vertexColors, colorHex: "#" + wm.color.getHexString() };
  });
  log("forces checkbox: " + JSON.stringify(forcesCheck) + " material after ON: " + JSON.stringify(afterForcesOn));
  await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-AFTER-forces-layer-on.png") });
  log("screenshot: task1-AFTER-forces-layer-on.png (wire-forces tint must still show)");
  // Turn back off, confirm it returns to legible (not dark).
  await page.evaluate(() => {
    const labels = Array.from(document.querySelectorAll("#layer-toggles label"));
    const boxes = Array.from(document.querySelectorAll('#layer-toggles input[type="checkbox"]'));
    const idx = labels.findIndex((l) => l.textContent.toLowerCase().includes("wire forces"));
    boxes[idx].checked = false;
    boxes[idx].dispatchEvent(new Event("change", { bubbles: true }));
  });
  await sleep(200);
  const afterForcesOff = await page.evaluate(() => {
    const wm = window.__studio.state.objects.wires.material;
    return { vertexColors: wm.vertexColors, colorHex: "#" + wm.color.getHexString() };
  });
  log("material after forces OFF again: " + JSON.stringify(afterForcesOff));
  await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-AFTER-forces-layer-off-again.png") });

  // ---------- Ribbon: same scenario as the original default-hidden shot ----------
  await page.evaluate(() => {
    const scrubber = document.getElementById("timeline-scrubber");
    scrubber.value = 667;
    scrubber.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await sleep(300);
  const ribbonAfter = await page.evaluate(() => {
    const s = window.__studio.state;
    const t = s.timeline.t;
    const build = Math.max(0, t - s.timeline.inflateSeconds);
    const placementCount = s.bundle.pieces.length;
    const step = 35 / Math.max(1, placementCount);
    const dropSeconds = 0.8;
    let crownRestZ = -Infinity;
    for (const seg of s.objects.shell.children) {
      if (typeof seg.userData.centreZ === "number") crownRestZ = Math.max(crownRestZ, seg.userData.centreZ);
    }
    const rows = [];
    for (const seg of s.objects.shell.children) {
      if (!seg.visible) continue;
      const entry = s.segmentIndex.get(seg.userData.key);
      const start = entry.order * step;
      const u = Math.min(1, Math.max(0, (build - start) / dropSeconds));
      const worldZ = (seg.userData.centreZ || 0) + seg.position.z;
      rows.push({ key: seg.userData.key, course: entry.course, order: entry.order, u, worldZ });
    }
    rows.sort((a, b) => b.worldZ - a.worldZ);
    return { t, dropReach: s.timeline.dropReach, crownRestZ, top5: rows.slice(0, 5) };
  });
  log("AFTER-fix ribbon reading: " + JSON.stringify(ribbonAfter, null, 2));
  // No camera repositioning here, matching the original "before" capture's
  // own method: whatever the app's own default camera position is after
  // boot + scrub, exactly as task1-default-hidden-before.png was taken.
  await page.screenshot({ path: path.join(CAPTURE_DIR, "task1-AFTER-ribbon-default-view.png") });
  log("screenshot: task1-AFTER-ribbon-default-view.png");

  writeFileSync(path.join(CAPTURE_DIR, "task1-AFTER-report.md"), reportLines.join("\n") + "\n");
  await browser.close();
}
main();
