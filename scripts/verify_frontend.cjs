// Deterministic browser checks. Responses are controlled here, not in the app.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const output = path.join(root, ".local", "frontend-qa");
const base = process.env.FRONTEND_URL || "http://127.0.0.1:8010";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
function payment(id, status = "pending", attempts = 0) {
  return { id, status, attempts, amount_minor: 12500, currency: "INR", scenario: "success",
    provider_reference: status === "succeeded" ? "sim-browser-check" : null,
    last_error: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
}
async function shot(page, name) { await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true }); }
async function waitHidden(page, selector) { await page.locator(selector).waitFor({ state: "hidden" }); }
async function consoleChecks(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let rows = [payment("11111111-1111-4111-8111-111111111111"), payment("22222222-2222-4222-8222-222222222222", "succeeded", 1)];
  let first = true, failLedger = false, failPost = false, postCode = 202, postCount = 0;
  await page.route("**/readyz", (r) => r.fulfill({ json: { status: "ready" } }));
  await page.route("**/payments**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST") {
      postCount++;
      await delay(2200);
      if (failPost) return route.abort("timedout");
      if (postCode !== 202) return route.fulfill({ status: postCode, json: { detail: "Idempotency-Key already used with different input" } });
      return route.fulfill({ status: 202, json: rows[0] });
    }
    if (pathname === "/payments") {
      if (first) { first = false; await delay(1800); }
      if (failLedger) return route.fulfill({ status: 503, json: { detail: "Test: API unavailable" } });
      return route.fulfill({ json: rows });
    }
    const id = pathname.split("/")[2];
    const snapshot = structuredClone(rows.find((p) => p.id === id));
    // A's old response arrives while B's newer panel is still loading.
    await delay(id === rows[0].id ? 2200 : 3200);
    if (pathname.endsWith("/events")) return route.fulfill({ json: [{ id: 1, kind: "created", detail: "", created_at: rows[0].created_at }] });
    return route.fulfill({ json: snapshot });
  });
  await page.goto(base + "/");
  await page.getByText("Loading your payments", { exact: true }).waitFor();
  assert.equal(await page.locator("#ledger").getAttribute("aria-busy"), "true");
  assert.ok(await page.locator("#payments .skeleton-line").count() > 0);
  await shot(page, "initial-loading");
  await waitHidden(page, "#ledger-progress");
  checks.push("Initial ledger loading screen, skeleton and busy cleanup");

  await page.getByRole("button", { name: `View payment ${rows[0].id}`, exact: true }).click();
  await page.locator("#detail-progress").waitFor({ state: "visible" });
  await page.locator("#close-drawer").click();
  await page.getByRole("button", { name: `View payment ${rows[1].id}`, exact: true }).click();
  await delay(2500);
  assert.equal(await page.locator("#detail-progress").isVisible(), true);
  assert.match(await page.locator("#payment-detail").innerText(), new RegExp(rows[1].id));
  await waitHidden(page, "#detail-progress");
  await page.locator("#close-drawer").click();
  checks.push("Late responses cannot clear another payment's loading feedback");

  await page.locator("#new-payment").click();
  await page.locator("#amount").fill("125.00");
  await page.locator("#submit-payment").click();
  await page.locator("#submission-progress").waitFor({ state: "visible" });
  assert.equal(await page.locator("#submit-payment").getAttribute("aria-busy"), "true");
  assert.equal(await page.locator("#close-drawer").isDisabled(), true);
  await page.locator("#submit-payment").evaluate((button) => button.click());
  await shot(page, "submission-loading");
  await waitHidden(page, "#submission-progress");
  assert.equal(postCount, 1);
  rows[0] = { ...rows[0], status: "succeeded", attempts: 1, updated_at: new Date().toISOString() };
  await page.locator("#refresh").evaluate((button) => button.click());
  await page.waitForFunction(() => document.querySelector("#payment-journey").dataset.tone === "success");
  await waitHidden(page, "#detail-progress");
  assert.equal(await page.locator("#payment-journey").getAttribute("data-tone"), "success");
  assert.match(await page.locator(".receipt-summary strong").innerText(), /completed/);
  await page.locator("#close-drawer").click();
  checks.push("Submission feedback, duplicate-click prevention and stale receipt-response fencing");

  for (const status of ["pending", "processing", "retrying", "unknown", "succeeded"]) {
    rows[0] = { ...rows[0], status, attempts: status === "pending" ? 0 : 2,
      updated_at: new Date().toISOString(), provider_reference: status === "succeeded" ? "sim-browser-check" : null };
    await page.locator("#refresh").click();
    await page.waitForFunction((expected) => document.querySelector("#payment-journey").dataset.tone === expected,
      status === "succeeded" ? "success" : status === "unknown" ? "review" : status === "retrying" ? "retry" : "active");
    await page.waitForFunction(() => document.querySelector("#refresh").getAttribute("aria-busy") === "false");
    if (status === "unknown") assert.equal(await page.locator("#payment-journey").getAttribute("data-active"), "false");
    if (status === "processing") await shot(page, "payment-processing");
  }
  assert.equal(await page.locator('#journey-steps [data-state="done"]').count(), 4);
  await shot(page, "payment-completed");
  checks.push("Observed pending/processing/retry/review/success states; no timed success");

  rows[0] = { ...rows[0], status: "pending" };
  await page.locator("#refresh").click();
  await page.waitForFunction(() => document.querySelector("#refresh").getAttribute("aria-busy") === "false");
  failLedger = true;
  await page.locator("#refresh").click();
  await page.locator("#list-error").waitFor({ state: "visible" });
  assert.match(await page.locator("#journey-live").innerText(), /unavailable/);
  assert.equal(await page.locator("#payment-journey").getAttribute("data-active"), "false");
  assert.ok(await page.locator("#payments button").count() > 0);
  failLedger = false;
  await page.locator("#refresh").click();
  await waitHidden(page, "#list-error");
  await page.locator("#auto-refresh").uncheck();
  assert.match(await page.locator("#journey-live").innerText(), /paused/);
  checks.push("Failed refresh preserves data and stops live motion; paused polling is explicit");

  await page.locator("#new-payment").click();
  await page.locator("#amount").fill("125.00");
  const key = await page.locator("#idempotency-key").inputValue();
  failPost = true;
  await page.locator("#submit-payment").click();
  await page.locator("#form-error").waitFor({ state: "visible" });
  assert.equal(await page.locator("#idempotency-key").inputValue(), key);
  assert.match(await page.locator("#journey-heading").innerText(), /not confirmed/);
  assert.equal(await page.locator("#submit-payment").isEnabled(), true);
  await waitHidden(page, "#submission-progress");
  failPost = false; postCode = 409;
  await page.locator("#submit-payment").click();
  await page.waitForFunction(() => document.querySelector("#journey-heading").textContent === "Request key conflict");
  await page.locator("#close-drawer").click();
  checks.push("Unconfirmed submissions and conflicts preserve the request key and clear busy state");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#auto-refresh").check();
  await page.waitForFunction(() => document.querySelector("#refresh").getAttribute("aria-busy") === "false");
  await page.locator("#payments button").first().click();
  await page.locator("#close-drawer").click();
  assert.equal(await page.locator("#payment-journey").getAttribute("data-active"), "true");
  assert.equal(await page.locator('#payment-journey [data-state="current"] .step-marker').evaluate((el) => getComputedStyle(el, "::before").animationName), "none");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await shot(page, "payment-mobile-reduced-motion");
  assert.deepEqual(errors, []);
  checks.push("Mobile layout and reduced-motion alternative; no app runtime errors");
  await context.close();
}

async function labChecks(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const catalog = await (await page.request.get(base + "/api/lab/catalog")).json();
  const campaigns = await (await page.request.get(base + "/api/lab/campaigns")).json();
  assert.ok(campaigns.length, "Run a real campaign before the lab UI checks");
  const report = await (await page.request.get(base + "/api/lab/campaigns/" + campaigns[0].id)).json();
  let failCampaign = true, failReport = false;
  await page.route("**/api/lab/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/catalog")) { await delay(1400); return route.fulfill({ json: catalog }); }
    if (url.pathname.endsWith("/replay")) { await delay(2300); return route.fulfill({ json: report.findings[0].minimal }); }
    if (route.request().method() === "POST") {
      await delay(2300);
      return route.fulfill({ status: failCampaign ? 503 : 201, json: failCampaign ? { detail: "Test: engine unavailable" } : report });
    }
    await delay(1700);
    if (url.pathname.endsWith("/campaigns")) return route.fulfill({ json: campaigns });
    return route.fulfill({ status: failReport ? 503 : 200, json: failReport ? { detail: "Test: report unavailable" } : report });
  });
  await page.goto(base + "/lab");
  await page.getByText("Preparing the workbench", { exact: true }).waitFor();
  assert.equal(await page.locator("#run-campaign").isDisabled(), true);
  await page.getByText("Go controller ready", { exact: false }).waitFor();
  await page.waitForFunction(() => document.querySelector("#history").getAttribute("aria-busy") === "false");
  await page.locator("#run-campaign").click();
  await page.getByText("Discovery is running", { exact: true }).waitFor();
  assert.equal(await page.locator("#progress").isVisible(), true);
  assert.equal(await page.locator("#results").isVisible(), false);
  assert.equal(await page.locator("#seed").isDisabled(), true);
  await shot(page, "campaign-running");
  await page.locator("#error").waitFor({ state: "visible" });
  await waitHidden(page, "#progress");
  assert.equal(await page.locator("#empty").isVisible(), true);
  assert.equal(await page.locator("#run-campaign").isEnabled(), true);
  failCampaign = false;
  await page.locator("#run-campaign").click();
  await page.locator("#results").waitFor({ state: "visible" });
  await waitHidden(page, "#progress");
  checks.push("Workbench preparation, running screen, error cleanup and successful retry");
  failReport = true;
  await page.locator("#history button").first().click();
  await page.getByText("Loading saved campaign", { exact: true }).waitFor();
  await page.locator("#error").waitFor({ state: "visible" });
  await waitHidden(page, "#report-progress");
  assert.equal(await page.locator("#results").getAttribute("aria-busy"), "false");
  checks.push("Saved-report loading failure clears busy feedback and preserves previous report");
  await page.locator("#replay").click();
  await page.getByText("Replaying the reduced sequence", { exact: true }).waitFor();
  await page.locator("#history button").first().click();
  await page.waitForFunction(() => !document.querySelector("#replay").disabled);
  assert.equal(await page.locator("#replay-progress").isVisible(), false);
  checks.push("Replay feedback clears even if a competing saved-report load fails");
  await page.locator("#replay").click();
  await page.getByText("Replaying the reduced sequence", { exact: true }).waitFor();
  await page.locator("#findings button").nth(1).click();
  assert.equal(await page.locator("#replay").isDisabled(), true);
  assert.equal(await page.locator("#run-campaign").isDisabled(), true);
  await page.waitForFunction(() => !document.querySelector("#replay").disabled);
  assert.equal(await page.locator("#replay-status").innerText(), "");
  checks.push("Replay feedback survives selection changes without stale messages or concurrent runs");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#run-campaign").click();
  await page.locator("#progress").waitFor({ state: "visible" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await shot(page, "campaign-running-mobile");
  await waitHidden(page, "#progress");
  assert.deepEqual(errors, []);
  await context.close();
}

async function timerChecks(browser) {
  const page = await browser.newPage();
  await page.goto(base + "/healthz");
  await page.clock.install();
  await page.evaluate(async (url) => {
    const { startActivity } = await import(url + "/assets/feedback.mjs");
    const panel = document.createElement("div");
    panel.id = "timer-check";
    document.body.append(panel);
    window.stopTimerCheck = startActivity(panel, "Request running", "Waiting for a response", "Still waiting; keep the same key");
  }, base);
  await page.clock.runFor(8500);
  assert.match(await page.locator("#timer-check").innerText(), /Still waiting/);
  assert.match(await page.locator("#timer-check .activity-elapsed").innerText(), /8s elapsed/);
  await page.evaluate(() => window.stopTimerCheck());
  const stoppedAt = await page.locator("#timer-check .activity-elapsed").textContent();
  await page.clock.runFor(5000);
  assert.equal(await page.locator("#timer-check").isHidden(), true);
  assert.equal(await page.locator("#timer-check .activity-elapsed").textContent(), stoppedAt);
  await page.evaluate(async (url) => {
    const { startActivity } = await import(url + "/assets/feedback.mjs");
    const nextStop = startActivity(document.getElementById("timer-check"), "New request", "A new operation is running");
    window.stopTimerCheck();
    window.stopNextTimerCheck = nextStop;
  }, base);
  assert.equal(await page.locator("#timer-check").isVisible(), true);
  await page.evaluate(() => window.stopNextTimerCheck());
  checks.push("Slow-request copy and elapsed clock update; cleanup stops the interval");
  await page.close();
}

(async () => {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    if (!process.argv.includes("--timer-only")) {
      if (!process.argv.includes("--lab-only")) await consoleChecks(browser);
      await labChecks(browser);
    }
    await timerChecks(browser);
  }
  finally { await browser.close(); }
  await fs.writeFile(path.join(output, "checks.json"), JSON.stringify(checks, null, 2));
  console.log(checks.map((check) => "PASS " + check).join("\n"));
})().catch((e) => { console.error(e); process.exitCode = 1; });
