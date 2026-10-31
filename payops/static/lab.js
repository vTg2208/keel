import { startActivity, busyButton, skeleton } from "./feedback.mjs";
const $ = (id) => document.getElementById(id);
let catalog = {};
let report = null;
let selected = 0;
let view = "minimal";
let stepIndex = 0;
let running = false;
let selectionVersion = 0;
let reportLoadVersion = 0;
let historyLoadVersion = 0;
let stopReportFeedback = () => {};
let stopReplayFeedback = () => {};
let replayBusy = false;
let controllerReady = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
async function request(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal,
      headers: { "Content-Type": "application/json", ...options.headers } });
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((item) => item.msg).join("; ") : data.detail;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Request timed out. Refresh history before trying again; the campaign may have completed.");
    throw error;
  } finally { clearTimeout(timer); }
}
function showError(error) {
  $("error").textContent = error.message || String(error);
  $("error").hidden = false;
}
function percentRemoved(findings) {
  const killed = findings.filter((f) => f.status === "killed");
  const before = killed.reduce((sum, f) => sum + f.original_trace.length, 0);
  const after = killed.reduce((sum, f) => sum + f.minimal_trace.length, 0);
  return before ? `${Math.round(100 * (before - after) / before)}%` : "—";
}
function renderReport(data) {
  reportLoadVersion++;
  stopReportFeedback();
  $("results").setAttribute("aria-busy", "false");
  report = data;
  $("empty").hidden = true;
  $("results").hidden = false;
  $("report-meta").textContent = `Seed ${data.seed} / budget ${data.budget} / ${new Date(data.created_at).toLocaleString()}`;
  $("metric-killed").textContent = `${data.killed} / ${data.total}`;
  $("metric-reduction").textContent = percentRemoved(data.findings);
  $("metric-executions").textContent = data.evaluations;
  $("metric-baseline").textContent = data.killed ? `${data.killed} clean` : "No findings";
  for (const kind of ["json", "markdown", "pytest"]) {
    $("download-" + kind).href = `/api/lab/campaigns/${data.id}/artifacts/${kind}`;
  }
  $("findings").replaceChildren();
  data.findings.forEach((finding, index) => {
    const button = node("button", undefined, "finding");
    button.type = "button";
    const label = node("div");
    label.append(node("strong", catalog[finding.mutation]?.title || finding.mutation));
    label.append(node("small", finding.status === "killed"
      ? `${finding.original_trace.length} → ${finding.minimal_trace.length} events · ${finding.reduction_checks} reduction checks`
      : `No counterexample in ${finding.attempted} schedules`));
    button.append(node("span", String(index + 1).padStart(2, "0"), "finding-index"), label,
      node("span", finding.status === "killed" ? "Exposed" : "Not found", "finding-status " + finding.status));
    button.addEventListener("click", () => selectFinding(index));
    $("findings").append(button);
  });
  history.replaceState(null, "", `#run=${data.id}`);
  selectFinding(0);
}
function selectFinding(index) {
  stopReplayFeedback();
  selectionVersion++;
  selected = index;
  view = "minimal";
  $("replay-status").textContent = "";
  busyButton($("replay"), replayBusy, replayBusy ? "Replay running…" : "Replay reduced sequence ↻");
  const finding = report.findings[index];
  const info = catalog[finding.mutation] || {};
  [...$("findings").children].forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
  $("finding-detail").hidden = false;
  $("finding-title").textContent = info.title || finding.mutation;
  $("finding-boundary").textContent = info.boundary || "Payment recovery";
  const killed = finding.status === "killed";
  $("counterexample").hidden = !killed;
  $("minimal-badge").hidden = !killed;
  $("finding-explanation").replaceChildren();
  if (!killed) {
    $("finding-explanation").append(node("strong", "Search budget exhausted"),
      node("div", "No counterexample was found. This does not establish that the implementation is safe. Increase the budget or change the seed."));
    return;
  }
  const violation = finding.minimal.violations[0];
  $("finding-explanation").append(node("strong", violation.invariant.replaceAll("_", " ")),
    node("div", violation.actual), node("p", "Guarantee: " + violation.expected));
  stepIndex = finding.minimal.steps.length - 1;
  renderTrace();
}
function renderTrace() {
  const finding = report.findings[selected];
  const execution = finding[view];
  const baseline = view === "baseline";
  const isOriginal = view === "original";
  $("trace-caption").textContent = baseline
    ? "Identical reduced sequence, correct implementation. No invariant violations observed."
    : isOriginal ? "Original discovered execution. Steps stop at the first violated invariant; later scheduled events are not executed."
      : "Every remaining event matters: deleting any one no longer reproduces this invariant.";
  for (const button of $("trace-views").children) button.setAttribute("aria-pressed", String(button.dataset.view === view));
  $("trace").replaceChildren();
  execution.steps.forEach((step, index) => {
    const li = node("li");
    const button = node("button", undefined, !step.applied ? "noop" : "");
    button.type = "button";
    button.append(node("span", String(index + 1).padStart(2, "0")), document.createTextNode(step.action));
    if (index === execution.steps.length - 1 && execution.violations.length) button.classList.add("failure");
    button.setAttribute("aria-pressed", String(index === stepIndex));
    button.addEventListener("click", () => { stepIndex = index; renderTrace(); });
    li.append(button);
    $("trace").append(li);
  });
  if (isOriginal) {
    finding.original_trace.slice(execution.steps.length).forEach((action, offset) => {
      const li = node("li");
      const button = node("button", undefined, "unexecuted");
      button.type = "button";
      button.disabled = true;
      button.title = "Not executed: replay stopped at the first violated invariant.";
      button.append(node("span", String(execution.steps.length + offset + 1).padStart(2, "0")),
        document.createTextNode(action + " · not executed"));
      li.append(button);
      $("trace").append(li);
    });
  }
  const step = execution.steps[stepIndex] || execution.steps.at(-1);
  if (!step) return;
  $("step-title").textContent = `After event ${step.index + 1}: ${step.action}`;
  $("step-applied").textContent = step.applied ? "Applied" : "Preconditions absent";
  $("step-note").textContent = step.note;
  const state = step.state;
  const values = [
    ["Payment state", state.payment?.status || "Not submitted"],
    ["Processing attempts", state.payment?.attempts ?? 0],
    ["Provider successes", state.provider_effects],
    ["Unpublished work", state.outbox_pending],
    ["Queued messages", state.queue_ready],
    ["Worker lease", state.payment?.has_lease ? "Active" : "None"],
  ];
  $("state-grid").replaceChildren(...values.map(([label, value]) => {
    const cell = node("div"); cell.append(node("span", label), node("strong", value)); return cell;
  }));
  $("raw-state").textContent = JSON.stringify(step, null, 2);
}
async function loadReport(id) {
  const version = ++reportLoadVersion;
  selectionVersion++;
  stopReportFeedback();
  const stop = startActivity($("report-progress"), "Loading saved campaign",
    "Fetching its findings, execution traces and baseline evidence.");
  stopReportFeedback = stop;
  $("results").setAttribute("aria-busy", "true");
  $("error").hidden = true;
  try {
    const data = await request(`/api/lab/campaigns/${encodeURIComponent(id)}`);
    if (version === reportLoadVersion) { renderReport(data); await refreshHistory(); }
  } catch (error) { if (version === reportLoadVersion) showError(error); }
  finally {
    if (version === reportLoadVersion) {
      stop();
      $("results").setAttribute("aria-busy", "false");
    }
  }
}
async function refreshHistory() {
  const version = ++historyLoadVersion;
  busyButton($("refresh-history"), true);
  $("history").setAttribute("aria-busy", "true");
  if (!$("history").querySelector("button")) skeleton($("history"), 3);
  try {
    const runs = await request("/api/lab/campaigns");
    if (version !== historyLoadVersion) return;
    $("history").replaceChildren();
    if (!runs.length) $("history").append(node("p", "No campaigns yet. Your first run will be saved here.", "muted"));
    runs.forEach((run) => {
      const button = node("button", `${run.killed}/${run.total} exposed · seed ${run.seed}`);
      button.type = "button";
      button.setAttribute("aria-current", String(report?.id === run.id));
      button.append(node("span", new Date(run.created_at).toLocaleString()));
      button.addEventListener("click", () => loadReport(run.id));
      $("history").append(button);
    });
  } catch (error) {
    if (version === historyLoadVersion) $("history").replaceChildren(node("p", error.message, "muted"));
  } finally {
    if (version === historyLoadVersion) {
      busyButton($("refresh-history"), false);
      $("history").setAttribute("aria-busy", "false");
    }
  }
}
$("campaign-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (running || replayBusy) return;
  const mutations = [...document.querySelectorAll('input[name="mutation"]:checked')].map((input) => input.value);
  if (!mutations.length) { showError(new Error("Select at least one fault to investigate.")); return; }
  running = true;
  busyButton($("run-campaign"), true, "Discovering…");
  $("campaign-form").setAttribute("aria-busy", "true");
  $("mutation-options").disabled = true;
  $("seed").disabled = true;
  $("budget").disabled = true;
  $("empty").hidden = true;
  $("results").hidden = true;
  const stop = startActivity($("progress"), "Discovery is running",
    "Searching recovery sequences, reducing failures and checking the correct implementation. Results appear when the engine finishes.",
    "The engine is still working. Elapsed time is shown; this is not a completion estimate.");
  $("progress").scrollIntoView({ block: "nearest", behavior: "instant" });
  $("error").hidden = true;
  try {
    const data = await request("/api/lab/campaigns", { method: "POST", body: JSON.stringify({
      seed: Number($("seed").value), budget: Number($("budget").value), mutations,
    }) });
    renderReport(data);
    await refreshHistory();
    $("results").scrollIntoView({ block: "start", behavior: "instant" });
  } catch (error) { showError(error); }
  finally {
    running = false;
    stop();
    busyButton($("run-campaign"), !controllerReady, "Run discovery →");
    $("campaign-form").setAttribute("aria-busy", "false");
    $("mutation-options").disabled = false;
    $("seed").disabled = false;
    $("budget").disabled = false;
    $("results").hidden = !report;
    $("empty").hidden = Boolean(report);
  }
});
$("trace-views").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button || !report) return;
  view = button.dataset.view;
  stepIndex = report.findings[selected][view].steps.length - 1;
  renderTrace();
});
$("replay").addEventListener("click", async () => {
  if (replayBusy || running) return;
  const finding = report.findings[selected];
  const version = selectionVersion;
  replayBusy = true;
  busyButton($("replay"), true, "Replaying…");
  $("run-campaign").disabled = true;
  const stop = startActivity($("replay-progress"), "Replaying the reduced sequence",
    "Running the same events against a fresh isolated database.");
  stopReplayFeedback = stop;
  $("replay-status").textContent = "Replaying in a fresh database…";
  try {
    const result = await request("/api/lab/replay", { method: "POST", body: JSON.stringify({
      actions: finding.minimal_trace, mutation: finding.mutation,
    }) });
    if (version !== selectionVersion) return;
    const expected = finding.minimal.violations[0].invariant;
    $("replay-status").textContent = result.violations.some((v) => v.invariant === expected)
      ? `Reproduced: ${expected}. ${result.steps.length} events executed.`
      : "The expected failure did not reproduce. Inspect the downloaded evidence.";
  } catch (error) { if (version === selectionVersion) $("replay-status").textContent = error.message; }
  finally {
    replayBusy = false;
    busyButton($("replay"), false, "Replay reduced sequence ↻");
    $("run-campaign").disabled = !controllerReady;
    stop();
  }
});
$("refresh-history").addEventListener("click", refreshHistory);
async function init() {
  const stop = startActivity($("report-progress"), "Preparing the workbench",
    "Loading available faults and checking the experiment controller.");
  try {
    const data = await request("/api/lab/catalog");
    catalog = data.mutations;
    controllerReady = data.controller_ready;
    $("mutation-options").replaceChildren(node("legend", "Faults to investigate"));
    for (const [id, info] of Object.entries(catalog)) {
      const label = node("label", undefined, "mutation");
      const input = document.createElement("input");
      input.type = "checkbox"; input.name = "mutation"; input.value = id; input.checked = true;
      const text = node("span"); text.append(node("strong", info.title), node("small", info.boundary));
      label.append(input, text); $("mutation-options").append(label);
    }
    $("engine-status").textContent = data.controller_ready
      ? "Go controller ready · Python replay protocol v1"
      : "Controller missing. Run: python -m payops.lab build, then refresh this page.";
    $("run-campaign").disabled = !controllerReady;
    $("mutation-options").setAttribute("aria-busy", "false");
    stop();
    const id = new URLSearchParams(location.hash.slice(1)).get("run");
    if (id) await loadReport(id);
    else await refreshHistory();
  } catch (error) {
    showError(error);
    $("engine-status").textContent = "Cannot reach the workbench API. Refresh to retry.";
    $("mutation-options").replaceChildren(node("legend", "Fault catalog unavailable"));
    $("mutation-options").setAttribute("aria-busy", "false");
    $("history").replaceChildren(node("p", "Refresh the page to reconnect.", "muted"));
    $("history").setAttribute("aria-busy", "false");
  } finally { stop(); }
}
init();
