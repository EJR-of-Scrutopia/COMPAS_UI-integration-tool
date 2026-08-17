// Console-error sanity pass across a full boot + study load + material
// switch + timeline scrub + wire-forces toggle, against the fixed source.
import puppeteer from "./probe-env/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";
const STUDIO_URL = "http://127.0.0.1:8641";
const BROWSER_EXE = "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function waitFor(page, fn, { timeout = 15000, interval = 200 } = {}) {
  const start = Date.now();
  for (;;) { if (await page.evaluate(fn)) return true; if (Date.now() - start > timeout) return false; await sleep(interval); }
}

async function main() {
  const errors = [];
  const browser = await puppeteer.launch({
    executablePath: BROWSER_EXE, headless: true,
    args: ["--use-angle=default"], defaultViewport: { width: 1600, height: 900 },
  });
  const page = await browser.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  await page.goto(STUDIO_URL, { waitUntil: "networkidle0" });
  await waitFor(page, () => !!window.__studio, { timeout: 10000 });
  for (const study of ["Algebraic TNA method", "Trial 2"]) {
    await page.evaluate((name) => {
      const s = document.getElementById("study-select");
      s.value = name;
      s.dispatchEvent(new Event("change", { bubbles: true }));
    }, study);
    await waitFor(page, (name) => window.__studio.state.bundle && window.__studio.state.bundle.export === name,
      { timeout: 20000 });
    for (const material of ["timber", "concrete-sprayed", "stone"]) {
      await page.evaluate((mat) => {
        const s = document.getElementById("material-select");
        s.value = mat;
        s.dispatchEvent(new Event("change", { bubbles: true }));
      }, material);
      await waitFor(page, (mat) => window.__studio.state.bundle && window.__studio.state.bundle.material === mat,
        { timeout: 20000 });
      for (const scrub of [0, 250, 500, 750, 1000]) {
        await page.evaluate((v) => {
          const sc = document.getElementById("timeline-scrubber");
          sc.value = v;
          sc.dispatchEvent(new Event("input", { bubbles: true }));
        }, scrub);
        await sleep(60);
      }
      await page.evaluate(() => {
        const labels = Array.from(document.querySelectorAll("#layer-toggles label"));
        const boxes = Array.from(document.querySelectorAll('#layer-toggles input[type="checkbox"]'));
        const idx = labels.findIndex((l) => l.textContent.toLowerCase().includes("wire forces"));
        if (idx < 0 || boxes[idx].disabled) return;
        boxes[idx].checked = true;
        boxes[idx].dispatchEvent(new Event("change", { bubbles: true }));
        boxes[idx].checked = false;
        boxes[idx].dispatchEvent(new Event("change", { bubbles: true }));
      });
      await sleep(100);
    }
  }
  console.log("console errors: " + errors.length);
  for (const e of errors) console.log("  " + e);
  await browser.close();
}
main();
