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
