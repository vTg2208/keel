export function toMinor(value) {
  const input = String(value).trim();
  if (!/^\d+(\.\d{1,2})?$/.test(input))
    throw new Error("Enter an amount with up to two decimal places.");
  const [whole, fraction = ""] = input.split(".");
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (!Number.isSafeInteger(minor) || minor < 1 || minor > 100000000) {
    throw new Error("Enter an amount between 0.01 and 1,000,000.00.");
  }
  return minor;
}
export function utcDate(value) {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
}
export function filterPayments(rows, query, status) {
  const term = query.trim().toLowerCase();
  return rows.filter(
    (p) =>
      (!status || p.status === status) &&
      `${p.id} ${p.provider_reference || ""}`.toLowerCase().includes(term),
  );
}
// Polling must wait for an existing request instead of starving slow responses.
export function singleFlight(run) {
  const active = new Map();
  return (key) => {
    if (!active.has(key)) {
      const promise = Promise.resolve()
        .then(() => run(key))
        .finally(() => active.delete(key));
      active.set(key, promise);
    }
    return active.get(key);
  };
}
export const scenarios = {
  success: [
    "Success",
    "The provider accepts the payment on the first attempt.",
  ],
  decline: [
    "Provider decline",
    "The provider rejects the payment. This is a final outcome.",
  ],
  flaky: [
    "Temporary failure",
    "The first attempt fails. A retry should succeed.",
  ],
  timeout: [
    "Provider timeout",
    "Every attempt times out. After retries are exhausted, the payment fails.",
  ],
  timeout_after_success: [
    "Timeout after success",
    "The provider accepts the payment but the response times out. A retry recovers the same result.",
  ],
};
export const statuses = {
  pending: ["Pending", "Waiting for a worker."],
  processing: ["Processing", "A worker is contacting the provider."],
  retrying: [
    "Retrying",
    "A temporary error occurred. Another attempt is scheduled.",
  ],
  succeeded: ["Succeeded", "The provider accepted this payment."],
  rejected: ["Rejected", "The provider declined this payment."],
  failed: [
    "Failed",
    "Retries are exhausted. Check the error and event history.",
  ],
  unknown: [
    "Unknown",
    "The provider outcome is uncertain. Reconciliation is required; do not assume it failed.",
  ],
};

// Presentation follows observed state, never a timer or an invented percentage.
export function paymentPresentation(payment) {
  const status = payment?.status || "idle";
  const states = {
    idle: [-1, "Ready for your next payment", "Submit a synthetic payment to follow its journey.", "neutral", false],
    submitting: [0, "Sending your payment", "Waiting for the API to confirm receipt. No payment outcome is confirmed yet.", "active", true],
    unconfirmed: [0, "Submission not confirmed", "Keep the same idempotency key when retrying. The request may already have been accepted.", "review", false],
    conflict: [0, "Request key conflict", "This key belongs to a payment with different input. Restore its original details or use a new key.", "review", false],
    not_submitted: [0, "Payment was not submitted", "Review the validation error and correct the request before trying again.", "danger", false],
    pending: [1, "Payment accepted. Waiting for a worker.", "Your request is stored. Processing resumes when a worker is available.", "active", true],
    processing: [2, "Your payment is being processed", "A worker is contacting the provider. Waiting for a confirmed result.", "active", true],
    retrying: [2, "A safe retry is scheduled", `Attempt ${payment?.attempts || 1} encountered a temporary problem. The same payment identity will be reused.`, "retry", true],
    succeeded: [3, "Payment completed", "The simulated provider confirmed success. Your receipt is ready below.", "success", false],
    rejected: [3, "Payment declined", "The provider declined this payment. It will not be retried.", "danger", false],
    failed: [3, "Payment could not be completed", "The retry limit was reached. Check the recorded error and event history.", "danger", false],
    unknown: [3, "This payment needs reconciliation", "The provider outcome is uncertain. Reconcile its records before taking further action.", "review", false],
  };
  const [stage, title, detail, tone, active] = states[status] ||
    [3, "Payment status needs review", "Refresh to retrieve a recognized payment state.", "review", false];
  return {
    stage, title, detail, tone, active,
    steps: ["Accepted", "Waiting", "Provider", "Result"].map((label, index) => ({
      label: index === 0 && status === "submitting" ? "Submitting"
        : index === 0 && status === "unconfirmed" ? "Unconfirmed"
          : index === 0 && status === "conflict" ? "Check key"
            : index === 0 && status === "not_submitted" ? "Not sent" : label,
      state: status === "succeeded" || (index < stage && status !== "unconfirmed")
        ? "done" : index === stage ? (active ? "current" : "attention") : "upcoming",
    })),
  };
}

export function preferPaymentSnapshot(current, incoming) {
  if (!current?.id || current.id !== incoming.id) return incoming;
  const previous = utcDate(current.updated_at).getTime();
  const next = utcDate(incoming.updated_at).getTime();
  if (next < previous) return current;
  if (next === previous) {
    const terminal = new Set(["succeeded", "rejected", "failed", "unknown"]);
    if (terminal.has(current.status) && !terminal.has(incoming.status)) return current;
    if (Number(incoming.attempts) < Number(current.attempts)) return current;
  }
  return incoming;
}
