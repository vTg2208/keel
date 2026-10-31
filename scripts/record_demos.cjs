// Record real local UI demonstrations. Requires Playwright and its Chromium/FFmpeg.
// Set PLAYWRIGHT_MODULE to a module path if Playwright is not in NODE_PATH.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const fs = require("node:fs/promises");
const path = require("node:path");
const execute = promisify(execFile);
const root = path.resolve(__dirname, "..");
const media = path.join(root, "docs", "demos");
const raw = path.join(root, ".local", "demo-recordings");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function setup(browser, name) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    recordVideo: { dir: raw, size: { width: 1280, height: 900 } },
    acceptDownloads: true,
    reducedMotion: "reduce",
  });
  await context.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const caption = document.createElement("aside");
      caption.id = "keel-recording-caption";
      caption.setAttribute("popover", "manual");
      Object.assign(caption.style, {
        position: "fixed", bottom: "0", left: "0", right: "0", zIndex: "2147483647",
        background: "#132f3b", color: "#fff", padding: "17px 28px 20px",
        fontFamily: "Plex, Segoe UI, sans-serif",
        pointerEvents: "none", minHeight: "91px", boxSizing: "border-box",
        margin: "0", width: "100%", maxWidth: "none", border: "0",
        borderTop: "2px solid #a7c7af", top: "auto",
      });
      const eyebrow = document.createElement("div");
      Object.assign(eyebrow.style, {
        color: "#b4d0bd", fontSize: "11px", letterSpacing: "1.3px", marginBottom: "8px",
      });
      const description = document.createElement("div");
      Object.assign(description.style, { fontSize: "18px", lineHeight: "1.4" });
      caption.append(eyebrow, description);
      document.body.append(caption);
      document.body.style.paddingBottom = "115px";
      window.keelDemoCaption = (title, text) => {
        eyebrow.textContent = title;
        description.textContent = text;
        if (caption.matches(":popover-open")) caption.hidePopover();
        caption.showPopover();
      };
    });
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const video = page.video();
  return { context, page, errors, name, video };
}

async function caption(page, title, text, hold = 2400) {
  await page.evaluate(([a, b]) => window.keelDemoCaption(a, b), [title, text]);
  console.log(title + " / " + text);
  await pause(hold);
}

async function finish(recording) {
  await recording.context.close();
  await recording.video.saveAs(path.join(raw, recording.name + ".webm"));
  if (recording.errors.length) throw new Error(recording.errors.join("\n"));
}

async function recordDiscovery(browser) {
  const recording = await setup(browser, "keel-failure-discovery");
  const { page } = recording;
  await page.goto(process.env.LAB_URL || "http://127.0.0.1:8010/lab");
  await page.getByText("Go controller ready", { exact: false }).waitFor();
  await caption(page, "KEEL / FAILURE DISCOVERY · 01", "Can a healthy application still get payment recovery wrong?", 3500);
  await page.locator("#seed").fill("42");
  await page.locator("#budget").fill("4");
  await caption(page, "02 / SEARCH", "Four deliberate defects. Seeded schedules. Real payment logic in isolated databases.", 3500);
  await page.getByRole("button", { name: "Run discovery" }).click();
  await caption(page, "03 / EXECUTE", "Go coordinates Python replays and removes events that do not explain the failure.", 1800);
  await page.locator("#results:not([hidden])").waitFor({ timeout: 90000 });
  if (await page.locator("#metric-killed").innerText() !== "4 / 4") throw new Error("Expected four detected faults");
  await page.evaluate(() => scrollTo(0, 0));
  await caption(page, "04 / EVIDENCE", "All four known defects exposed. Every finding includes a passing baseline comparison.", 4000);
  await page.getByRole("button", { name: /Changing provider identity/ }).click();
  await page.locator("#finding-detail").scrollIntoViewIfNeeded();
  await page.evaluate(() => scrollBy(0, 160));
  await caption(page, "05 / THE COUNTEREXAMPLE", "Changing the provider key after a worker crash produces two successful provider effects.", 4500);
  await page.screenshot({ path: path.join(media, "failure-discovery-poster.jpg"), type: "jpeg", quality: 88 });
  await page.locator("#trace button").nth(2).click();
  await caption(page, "06 / FOLLOW THE STATE", "The first attempt reaches the provider: one successful effect is stored.", 3500);
  await page.locator("#trace button").last().click();
  await caption(page, "07 / AFTER RECOVERY", "A second attempt uses a new identity. Provider storage now contains two successes.", 3500);
  await page.getByRole("button", { name: "Correct implementation", exact: true }).click();
  await caption(page, "08 / SAME EVENTS, CORRECT LOGIC", "With stable provider identity, the same sequence preserves one successful effect.", 4500);
  await page.getByRole("button", { name: "Original", exact: true }).click();
  await caption(page, "09 / REDUCE", "The original schedule includes noise and events after the failure.", 3000);
  await page.getByRole("button", { name: "Reduced", exact: true }).click();
  await caption(page, "10 / A SMALLER REPRODUCTION", "Eleven scheduled events become six. Removing any remaining event removes this violation.", 4000);
  await page.getByRole("button", { name: "Replay reduced sequence" }).click();
  await page.locator("#replay-status").filter({ hasText: "Reproduced:" }).waitFor({ timeout: 15000 });
  await caption(page, "11 / REPRODUCE", "Replay confirms the same invariant violation in a fresh database.", 3500);
  await page.evaluate(() => scrollTo(0, 0));
  const download = page.waitForEvent("download");
  await page.locator("#download-pytest").click();
  await (await download).saveAs(path.join(raw, "downloaded-regression.py"));
  await caption(page, "12 / KEEP THE PROOF", "Export an executable regression test, JSON evidence and a readable incident report.", 4000);
  const url = page.url();
  await page.reload();
  await page.locator("#results:not([hidden])").waitFor();
  await caption(page, "KEEL / REPLAYABLE EVIDENCE", "Saved campaigns survive reloads. Explore, explain and preserve a payment-recovery failure.", 4000);
  await finish(recording);
  return { name: recording.name, url, faults: 4, baseline: true, replay: true, download: true };
}

async function createPayment(page, amount, scenario, key) {
  await page.getByRole("button", { name: "New payment" }).click();
  await page.locator("#amount").fill(amount);
  await page.locator("#scenario").selectOption(scenario);
  if (key) {
    await page.locator("#request-options").evaluate((element) => { element.open = true; });
    await page.locator("#idempotency-key").fill(key);
  }
  const idempotencyKey = await page.locator("#idempotency-key").inputValue();
  return { idempotencyKey, submit: async () => {
    const response = page.waitForResponse((r) => r.url().endsWith("/payments") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Submit payment", exact: true }).click();
    const result = await response;
    return { payment: await result.json(), status: result.status() };
  } };
}

async function recordPayments(browser) {
  const recording = await setup(browser, "keel-payment-recovery");
  const { page } = recording;
  let stopped = false;
  let paymentId;
  try {
    const worker = await execute("docker", ["compose", "ps", "--services", "--status", "running", "worker"], { cwd: root });
    if (!worker.stdout.includes("worker")) throw new Error("Start the Compose worker before recording");
    await page.goto(process.env.PAYMENT_URL || "http://127.0.0.1:8000/");
    await page.getByText("API connected", { exact: false }).waitFor();
    await caption(page, "KEEL / PAYMENT OPERATIONS · 01", "A synthetic payment travels through PostgreSQL, an outbox, RabbitMQ and a worker.", 3500);
    const first = await createPayment(page, "125.00", "flaky");
    await caption(page, "02 / SUBMIT", "Simulate a temporary provider failure. The API accepts work before processing completes.", 3500);
    const created = await first.submit();
    if (created.status !== 202) throw new Error("Expected a newly accepted payment");
    await page.locator("#payment-detail .status").filter({ hasText: "Succeeded" }).waitFor({ timeout: 30000 });
    await caption(page, "03 / RETRY AND RECOVER", "The temporary failure triggers a retry. Event history records the path to success.", 5000);
    await page.locator("#close-drawer").click();
    const replay = await createPayment(page, "125.00", "flaky", first.idempotencyKey);
    await caption(page, "04 / SAFE REQUEST REPLAY", "Submit identical input with the same idempotency key.", 3500);
    const repeated = await replay.submit();
    if (repeated.status !== 200 || repeated.payment.id !== created.payment.id) throw new Error("Idempotency check failed");
    await caption(page, "05 / NO DUPLICATE PAYMENT", "The API returns the original payment ID instead of creating another payment.", 4000);
    await page.locator("#close-drawer").click();
    stopped = true;
    await execute("docker", ["compose", "stop", "worker"], { cwd: root });
    const queued = await createPayment(page, "250.00", "success");
    await caption(page, "06 / INJECT A REAL WORKER OUTAGE", "The Compose worker is stopped. The API and database remain available.", 3500);
    const pending = await queued.submit();
    paymentId = pending.payment.id;
    await page.locator("#payment-detail .status").filter({ hasText: "Pending" }).waitFor();
    await caption(page, "07 / ACCEPTED WORK IS RETAINED", "The payment stays pending while the worker is unavailable; its durable intent is preserved.", 6500);
    await execute("docker", ["compose", "start", "worker"], { cwd: root });
    stopped = false;
    await caption(page, "08 / RESTORE THE WORKER", "Restart the worker. The existing payment resumes without resubmitting it.", 2000);
    await page.locator("#payment-detail .status").filter({ hasText: "Succeeded" }).waitFor({ timeout: 30000 });
    await caption(page, "09 / VERIFY RECOVERY", "The same payment succeeds with one processing attempt and a provider reference.", 5000);
    await page.screenshot({ path: path.join(media, "payment-recovery-poster.jpg"), type: "jpeg", quality: 88 });
    const state = await page.request.get(new URL(`/payments/${paymentId}`, page.url()).toString());
    const saved = await state.json();
    if (saved.status !== "succeeded" || saved.attempts !== 1) throw new Error("Recovery integrity failed");
    await caption(page, "KEEL / SYNTHETIC PAYMENTS ONLY", "Real containers, real recovery and visible evidence. No money is moved.", 3500);
    await finish(recording);
    return { name: recording.name, paymentId, recovered: true, attempts: saved.attempts, idempotency: true };
  } finally {
    if (stopped) await execute("docker", ["compose", "start", "worker"], { cwd: root });
    if (recording.context.pages().length) await recording.context.close();
  }
}

(async () => {
  await fs.mkdir(media, { recursive: true });
  await fs.mkdir(raw, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const only = process.argv[process.argv.indexOf("--only") + 1];
    const results = [];
    if (!process.argv.includes("--only") || only === "discovery") results.push(await recordDiscovery(browser));
    if (!process.argv.includes("--only") || only === "payments") results.push(await recordPayments(browser));
    if (!results.length) throw new Error("Use --only discovery or --only payments");
    const report = process.argv.includes("--only") ? `verification-${only}.json` : "verification.json";
    await fs.writeFile(path.join(raw, report), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
