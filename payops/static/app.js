import {
  toMinor,
  utcDate,
  filterPayments,
  singleFlight,
  scenarios,
  statuses,
  paymentPresentation,
  preferPaymentSnapshot,
} from "./core.mjs";
import { startActivity, busyButton, skeleton } from "./feedback.mjs";

const $ = (id) => document.getElementById(id);
const drawer = $("drawer");
let rows = [],
  loaded = false,
  refreshing = false,
  selectedId = null,
  detailVersion = 0;
let lastUpdate = null,
  returnFocus = null,
  returnPaymentId = null,
  submitting = false,
  noticeTimer;
let trackedPayment = null;
let journeyFresh = true;
let stopDetailFeedback = () => {};
const loadDetails = singleFlight((id) =>
  Promise.allSettled([
    request(`/payments/${encodeURIComponent(id)}`),
    request(`/payments/${encodeURIComponent(id)}/events`),
  ]),
);
const money = (p) =>
  new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: p.currency,
  }).format(p.amount_minor / 100);
const date = (value) =>
  new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(utcDate(value));
const fullDate = (value) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(utcDate(value));
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function renderJourney(payment = trackedPayment) {
  if (payment) payment = preferPaymentSnapshot(trackedPayment, payment);
  trackedPayment = payment;
  const state = paymentPresentation(payment);
  const journey = $("payment-journey");
  const polling = $("auto-refresh").checked;
  journey.dataset.tone = state.tone;
  const sending = payment?.status === "submitting";
  journey.dataset.active = String(state.active && (sending || (journeyFresh && polling)));
  const receipt = $("payment-detail").querySelector(".receipt-summary");
  if (receipt) receipt.dataset.active = journey.dataset.active;
  $("journey-heading").textContent = state.title;
  $("journey-copy").textContent = state.detail;
  $("journey-amount").textContent = payment ? money(payment) : "—";
  $("journey-open").hidden = !payment?.id;
  for (const [index, item] of [...$("journey-steps").children].entries()) {
    item.dataset.state = state.steps[index].state;
    item.querySelector(".step-marker").textContent = state.steps[index].state === "done" ? "✓" : index + 1;
    item.querySelector("span:last-child").textContent = state.steps[index].label;
    if (index === state.stage) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  }
  const live = sending ? "Sending your request. Waiting for acknowledgement."
    : payment?.status === "unconfirmed" ? "Submission not confirmed. Preserve your key when retrying."
    : payment && !payment.id ? `${state.title}. Review the request details before retrying.`
    : !journeyFresh ? "Live updates unavailable. Showing the last confirmed state."
    : !polling ? "Live updates paused. The payment can continue processing in the background."
      : state.active ? `${state.title} · checking every 3 seconds`
        : payment?.id ? `${state.title} · confirmed state from the API` : "Select or submit a payment to follow its progress.";
  if ($("journey-live").textContent !== live) $("journey-live").textContent = live;
  updateJourneyClock();
}
function updateJourneyClock() {
  const payment = trackedPayment;
  if (!payment?.created_at) {
    $("journey-label").textContent = payment?.status === "submitting" ? "Awaiting receipt" : "Synthetic payments only";
    return;
  }
  const age = Math.max(0, Math.floor((Date.now() - utcDate(payment.created_at).getTime()) / 1000));
  const active = paymentPresentation(payment).active;
  $("journey-label").textContent = active
    ? `${age}s since submission · ${payment.attempts || 0} attempt(s)`
    : `Payment ${payment.id.slice(0, 8)}`;
  if (payment.status === "pending" && age >= 15) {
    $("journey-copy").textContent = "Still waiting for a worker. Your accepted request remains stored; it has not failed.";
  }
}
$("journey-open").addEventListener("click", () => {
  if (trackedPayment?.id) void openPayment(trackedPayment.id, trackedPayment);
});
function statusNode(status) {
  const el = node("span", undefined, "status");
  const dot = node("i", undefined, `dot ${status in statuses ? status : ""}`);
  dot.setAttribute("aria-hidden", "true");
  el.append(dot, document.createTextNode(statuses[status]?.[0] || status));
  return el;
}
function errorMessage(error) {
  if (error.name === "TimeoutError")
    return "The API took too long to respond. Please try again with the same request key.";
  return error instanceof TypeError
    ? "Cannot reach the API. Check your connection and try again."
    : error.message;
}
async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(12000),
    cache: "no-store",
  });
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      /* A proxy may return plain text. */
    }
    const message =
      response.status === 409
        ? "This key was already used with different input. Restore the original input, or generate a new key to create a separate payment."
        : typeof body?.detail === "string"
          ? body.detail
          : `The API returned ${response.status}. Please try again.`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return { data: await response.json(), status: response.status };
}
function renderRows() {
  const filtered = filterPayments(
    rows,
    $("search").value,
    $("status-filter").value,
  );
  $("count").textContent =
    `${filtered.length === rows.length ? rows.length : `${filtered.length} of ${rows.length}`} payment${rows.length === 1 ? "" : "s"}`;
  const body = $("payments");
  // Keep focused row buttons stable during background refreshes.
  const signature =
    JSON.stringify(
      filtered.map((p) => [p.id, p.status, p.attempts, p.updated_at]),
    ) + selectedId;
  if (body.dataset.signature === signature) return;
  body.dataset.signature = signature;
  const activeId = document.activeElement?.dataset.paymentId;
  const previousStates = new Map([...body.children].map((row) => [row.dataset.paymentId, row.dataset.status]));
  body.replaceChildren();
  if (!filtered.length) {
    const cell = node("td", undefined, "empty");
    cell.colSpan = 6;
    cell.append(
      node("strong", rows.length ? "No matching payments" : "No payments yet"),
      document.createTextNode(
        rows.length
          ? "Try another ID or status."
          : "Create a test payment to see its progress here.",
      ),
    );
    const tr = node("tr");
    tr.append(cell);
    body.append(tr);
    return;
  }
  for (const payment of filtered) {
    const tr = node(
      "tr",
      undefined,
      payment.id === selectedId ? "selected" : "",
    );
    tr.dataset.paymentId = payment.id;
    tr.dataset.status = payment.status;
    if (previousStates.has(payment.id) && previousStates.get(payment.id) !== payment.status) tr.classList.add("row-updated");
    const id = node("td");
    const button = node("button", payment.id.slice(0, 8), "payment-link");
    button.type = "button";
    button.dataset.paymentId = payment.id;
    button.setAttribute("aria-label", `View payment ${payment.id}`);
    button.append(node("span", "›"));
    button.addEventListener("click", () => openPayment(payment.id));
    id.append(button);
    const created = node("td", date(payment.created_at), "date");
    created.title = fullDate(payment.created_at);
    const state = node("td");
    state.append(statusNode(payment.status));
    tr.append(
      id,
      created,
      node("td", money(payment), "amount"),
      node("td", scenarios[payment.scenario]?.[0] || payment.scenario),
      state,
      node("td", String(payment.attempts), "attempts"),
    );
    body.append(tr);
  }
  if (activeId)
    [...body.querySelectorAll("button")]
      .find((b) => b.dataset.paymentId === activeId)
      ?.focus({ preventScroll: true });
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  busyButton($("refresh"), true, "Refreshing…");
  $("ledger").setAttribute("aria-busy", "true");
  const stop = !loaded ? startActivity($("ledger-progress"), "Loading your payments",
    "Connecting to the API and retrieving your ledger.",
    "The API is taking longer than usual. You can retry if it does not respond.") : () => {};
  try {
    const [payments, health] = await Promise.all([
      request("/payments"),
      request("/readyz"),
    ]);
    if (health.data.status !== "ready")
      throw new Error("The database is not ready.");
    rows = payments.data.map((payment) => preferPaymentSnapshot(trackedPayment, payment));
    loaded = true;
    lastUpdate = new Date();
    $("connection").replaceChildren(
      node("i", undefined, "dot succeeded"),
      document.createTextNode("API connected"),
    );
    $("updated").textContent =
      `Updated ${lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    $("list-error").hidden = true;
    renderRows();
    if (trackedPayment?.id) {
      const current = rows.find((p) => p.id === trackedPayment.id);
      if (current) { journeyFresh = true; renderJourney(current); }
    }
  } catch (error) {
    journeyFresh = false;
    renderJourney();
    $("connection").replaceChildren(
      node("i", undefined, "dot offline"),
      document.createTextNode("API unavailable"),
    );
    $("list-error").textContent =
      `${errorMessage(error)}${loaded ? " Showing the last loaded payments." : ""}`;
    $("list-error").hidden = false;
    if (!loaded) {
      const cell = node(
        "td",
        "Payments could not be loaded. Use Refresh to try again.",
        "empty",
      );
      cell.colSpan = 6;
      const tr = node("tr");
      tr.append(cell);
      $("payments").replaceChildren(tr);
      $("count").textContent = "— payments";
    }
  } finally {
    refreshing = false;
    stop();
    $("ledger").setAttribute("aria-busy", "false");
    busyButton($("refresh"), false, "Refresh");
  }
  if (selectedId && drawer.open) await refreshDetail();
}
function showDrawer() {
  if (!drawer.open) {
    returnFocus = document.activeElement;
    returnPaymentId = returnFocus?.dataset.paymentId;
    drawer.showModal();
  }
  drawer.scrollTop = 0;
}
function openCreate() {
  stopDetailFeedback();
  selectedId = null;
  detailVersion++;
  $("drawer-title").textContent = "New payment";
  $("create-panel").hidden = false;
  $("detail-panel").hidden = true;
  if (!$("idempotency-key").value)
    $("idempotency-key").value = crypto.randomUUID();
  showDrawer();
  $("amount").focus();
  renderRows();
}
function closeDrawer() {
  if (!submitting) drawer.close();
}
drawer.addEventListener("cancel", (event) => {
  if (submitting) event.preventDefault();
});
drawer.addEventListener("close", () => {
  stopDetailFeedback();
  selectedId = null;
  detailVersion++;
  renderRows();
  const rowButton = [...$("payments").querySelectorAll("button")].find(
    (b) => b.dataset.paymentId === returnPaymentId,
  );
  if (rowButton) rowButton.focus();
  else if (returnFocus?.isConnected) returnFocus.focus();
  else $("new-payment").focus();
});
function announce(text) {
  clearTimeout(noticeTimer);
  $("announcement").textContent = text;
  $("announcement").hidden = false;
  noticeTimer = setTimeout(() => {
    $("announcement").hidden = true;
  }, 10000);
}
function renderDetail(payment) {
  payment = preferPaymentSnapshot(trackedPayment, payment);
  journeyFresh = true;
  renderJourney(payment);
  const target = $("payment-detail");
  const signature = JSON.stringify(payment);
  if (target.dataset.signature === signature) return;
  target.dataset.signature = signature;
  target.replaceChildren();
  target.append(
    node("p", payment.id, "detail-id mono"),
    node("p", money(payment), "detail-amount"),
    statusNode(payment.status),
    node(
      "p",
      statuses[payment.status]?.[1] || payment.status,
      "detail-description",
    ),
  );
  const fields = node("dl", undefined, "detail-fields");
  for (const [label, value, cls] of [
    ["Test case", scenarios[payment.scenario]?.[0] || payment.scenario],
    ["Attempts", String(payment.attempts)],
    ["Created", fullDate(payment.created_at)],
    ["Last updated", fullDate(payment.updated_at)],
    [
      "Provider reference",
      payment.provider_reference || "Not assigned",
      "mono",
    ],
    ...(payment.last_error
      ? [["Last error", payment.last_error, "error-text"]]
      : []),
  ]) {
    const row = node("div");
    row.append(node("dt", label), node("dd", value, cls));
    fields.append(row);
  }
  target.append(fields);
  const summary = node("section", undefined, "receipt-summary");
  summary.dataset.tone = paymentPresentation(payment).tone;
  const presentation = paymentPresentation(payment);
  summary.dataset.active = $("payment-journey").dataset.active;
  const symbol = node("span", payment.status === "succeeded" ? "✓" : presentation.active ? "↗" : "!", "receipt-symbol");
  symbol.setAttribute("aria-hidden", "true");
  const summaryCopy = node("div");
  summaryCopy.append(node("strong", presentation.title), node("p", presentation.detail));
  const miniSteps = node("ol", undefined, "receipt-steps");
  miniSteps.setAttribute("aria-label", "Payment stages");
  for (const step of presentation.steps) {
    const item = node("li", step.label);
    item.dataset.state = step.state;
    miniSteps.append(item);
  }
  summaryCopy.append(miniSteps);
  summary.append(symbol, summaryCopy);
  target.prepend(summary);
}
function renderEvents(events) {
  const list = $("events"),
    signature = JSON.stringify(events);
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  list.replaceChildren();
  $("event-count").textContent =
    `${events.length} event${events.length === 1 ? "" : "s"}`;
  if (!events.length) {
    list.append(node("li", "No events recorded yet."));
    return;
  }
  for (const event of events) {
    const item = node("li");
    const title = event.kind
      .replaceAll("_", " ")
      .replace(/^./, (c) => c.toUpperCase());
    const time = node("time", fullDate(event.created_at));
    time.dateTime = utcDate(event.created_at).toISOString();
    item.append(node("strong", title), time);
    if (event.detail)
      item.append(
        node(
          "p",
          typeof event.detail === "string"
            ? event.detail
            : JSON.stringify(event.detail),
        ),
      );
    list.append(item);
  }
}
async function refreshDetail(foreground = false) {
  const id = selectedId,
    version = detailVersion;
  const stop = foreground ? startActivity($("detail-progress"), "Fetching the latest payment state",
    "Loading the receipt and its processing history.", "Still waiting for the API. You can close this panel and try again.") : () => {};
  if (foreground) {
    stopDetailFeedback = stop;
    $("payment-detail").setAttribute("aria-busy", "true");
    $("events").setAttribute("aria-busy", "true");
  }
  const results = await loadDetails(id);
  if (id !== selectedId || version !== detailVersion || !drawer.open) return;
  stop();
  $("payment-detail").setAttribute("aria-busy", "false");
  $("events").setAttribute("aria-busy", "false");
  for (const [index, errorId] of ["detail-error", "events-error"].entries()) {
    const result = results[index],
      errorElement = $(errorId);
    errorElement.hidden = result.status === "fulfilled";
    if (result.status === "rejected") {
      errorElement.textContent = errorMessage(result.reason);
      if (index === 0) {
        journeyFresh = false;
        renderJourney();
        if (!$("payment-detail").dataset.signature) $("payment-detail").replaceChildren(node("p", "Payment details unavailable. Close this panel and reopen it to retry.", "drawer-intro"));
      } else if (!$("events").dataset.signature) $("events").replaceChildren(node("li", "Event history could not be loaded."));
    }
    else if (index === 0) renderDetail(result.value.data);
    else renderEvents(result.value.data);
  }
}
async function openPayment(id, initial) {
  stopDetailFeedback();
  selectedId = id;
  detailVersion++;
  $("drawer-title").textContent = "Payment details";
  $("create-panel").hidden = true;
  $("detail-panel").hidden = false;
  $("detail-error").hidden = true;
  $("events-error").hidden = true;
  $("payment-detail").dataset.signature = "";
  $("events").dataset.signature = "";
  skeleton($("payment-detail"), 5);
  const historyPlaceholder = node("li");
  skeleton(historyPlaceholder, 3);
  $("events").replaceChildren(historyPlaceholder);
  $("event-count").textContent = "";
  const known = initial || rows.find((p) => p.id === id);
  if (known) renderDetail(known);
  showDrawer();
  $("close-drawer").focus();
  renderRows();
  await refreshDetail(true);
}
$("payment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitting) return;
  $("form-error").hidden = true;
  clearTimeout(noticeTimer);
  $("announcement").hidden = true;
  let body;
  try {
    body = {
      amount_minor: toMinor($("amount").value),
      currency: $("currency").value,
      scenario: $("scenario").value,
    };
    const key = $("idempotency-key").value;
    if (!key.trim() || key !== key.trim())
      throw new Error("The idempotency key must have no surrounding spaces.");
  } catch (error) {
    $("form-error").textContent = error.message;
    $("form-error").hidden = false;
    return;
  }
  submitting = true;
  renderJourney({ ...body, status: "submitting" });
  $("payment-form").setAttribute("aria-busy", "true");
  const stopSubmission = startActivity($("submission-progress"), "Submitting your payment",
    "Waiting for the API to acknowledge your request. Your idempotency key is preserved.",
    "Confirmation is taking longer than usual. Keep this key if you need to retry.");
  busyButton($("submit-payment"), true, "Submitting…");
  const controls = [
    ...$("payment-form").querySelectorAll("input,select,button"),
  ];
  controls.forEach((el) => {
    el.disabled = true;
  });
  $("close-drawer").disabled = true;
  const unlock = () => {
    submitting = false;
    controls.forEach((el) => {
      el.disabled = false;
    });
    $("close-drawer").disabled = false;
    busyButton($("submit-payment"), false, "Submit payment");
    $("payment-form").setAttribute("aria-busy", "false");
  };
  try {
    const result = await request("/payments", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": $("idempotency-key").value,
      },
      body: JSON.stringify(body),
    });
    announce(
      result.status === 200
        ? "Existing payment returned. No duplicate was created."
        : "Payment submitted. Its status will update automatically.",
    );
    $("payment-form").reset();
    $("idempotency-key").value = "";
    updateScenario();
    unlock();
    void openPayment(result.data.id, result.data);
    void refresh();
  } catch (error) {
    renderJourney({ ...body, status: error.status === 409 ? "conflict"
      : [400, 422].includes(error.status) ? "not_submitted" : "unconfirmed" });
    $("form-error").textContent = errorMessage(error);
    $("form-error").hidden = false;
    if (error.status === 409) $("request-options").open = true;
    // Leave input and key intact: a request may have reached the API before a network error.
  } finally {
    stopSubmission();
    unlock();
  }
});
function updateScenario() {
  $("scenario-hint").textContent = scenarios[$("scenario").value][1];
}
$("scenario").addEventListener("change", updateScenario);
updateScenario();
$("new-payment").addEventListener("click", openCreate);
$("close-drawer").addEventListener("click", closeDrawer);
$("cancel-create").addEventListener("click", closeDrawer);
$("new-key").addEventListener("click", () => {
  $("idempotency-key").value = crypto.randomUUID();
  $("form-error").hidden = true;
});
$("search").addEventListener("input", renderRows);
$("status-filter").addEventListener("change", renderRows);
$("refresh").addEventListener("click", refresh);
$("auto-refresh").addEventListener("change", () => {
  renderJourney();
  if ($("auto-refresh").checked) refresh();
});
for (const link of document.querySelectorAll("[data-service]")) {
  const url = new URL(window.location.href);
  url.port = link.dataset.service;
  url.pathname = link.dataset.path || "/";
  url.search = "";
  url.hash = "";
  link.href = url.href;
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && $("auto-refresh").checked) refresh();
});
setInterval(() => {
  if ($("auto-refresh").checked && !document.hidden) refresh();
}, 3000);
setInterval(() => { if (!document.hidden) updateJourneyClock(); }, 1000);
refresh();
