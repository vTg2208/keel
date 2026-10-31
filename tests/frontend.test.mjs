import test from "node:test";
import assert from "node:assert/strict";
import {
  toMinor,
  utcDate,
  filterPayments,
  singleFlight,
  paymentPresentation,
  preferPaymentSnapshot,
} from "../payops/static/core.mjs";

test("late ledger and receipt responses cannot rewind a newer confirmed state", () => {
  const pending = { id: "one", status: "pending", attempts: 0, updated_at: "2026-10-31T12:00:00" };
  const success = { ...pending, status: "succeeded", attempts: 1, updated_at: "2026-10-31T12:00:02" };
  assert.equal(preferPaymentSnapshot(success, pending), success);
  assert.equal(preferPaymentSnapshot(pending, success), success);
  assert.equal(preferPaymentSnapshot(null, pending), pending);
  const other = { ...pending, id: "two" };
  assert.equal(preferPaymentSnapshot(success, other), other);
  assert.equal(preferPaymentSnapshot(success, { ...pending, updated_at: success.updated_at }), success);
});

test("payment journey follows real status without claiming success during waiting or retries", () => {
  for (const status of ["pending", "processing", "retrying"]) {
    const state = paymentPresentation({ status, attempts: 2 });
    assert.equal(state.active, true);
    assert.notEqual(state.tone, "success");
    assert.equal(state.steps.length, 4);
    assert.equal(state.steps.filter((s) => s.state === "current").length, 1);
  }
  assert.equal(paymentPresentation({ status: "pending" }).stage, 1);
  assert.equal(paymentPresentation({ status: "processing" }).stage, 2);
  assert.match(paymentPresentation({ status: "retrying", attempts: 2 }).detail, /2/);
});

test("payment outcomes and unconfirmed submissions retain their distinct meanings", () => {
  const success = paymentPresentation({ status: "succeeded" });
  assert.equal(success.tone, "success");
  assert.equal(success.active, false);
  assert.ok(success.steps.every((s) => s.state === "done"));
  for (const status of ["rejected", "failed", "unknown", "unconfirmed"]) {
    const state = paymentPresentation({ status });
    assert.equal(state.active, false);
    assert.notEqual(state.tone, "success");
  }
  assert.match(paymentPresentation({ status: "unknown" }).detail, /reconcil/i);
  assert.match(paymentPresentation({ status: "unconfirmed" }).detail, /same.*key/i);
  assert.equal(paymentPresentation(null).stage, -1);
  assert.equal(paymentPresentation({ status: "unexpected" }).tone, "review");
});

test("converts decimal money exactly and rejects invalid or excessive amounts", () => {
  assert.equal(toMinor("0.29"), 29);
  assert.equal(toMinor("125"), 12500);
  assert.equal(toMinor("1000000.00"), 100000000);
  for (const input of ["", "0", "-1", "1.234", "1e2", "1000000.01", "NaN"]) {
    assert.throws(() => toMinor(input));
  }
});
test("interprets naive API timestamps as UTC and preserves explicit offsets", () => {
  assert.equal(
    utcDate("2026-10-31T00:00:00").toISOString(),
    "2026-10-31T00:00:00.000Z",
  );
  assert.equal(
    utcDate("2026-10-31T05:30:00+05:30").toISOString(),
    "2026-10-31T00:00:00.000Z",
  );
});
test("combines status and case-insensitive ID/reference search", () => {
  const rows = [
    { id: "abc-123", status: "succeeded", provider_reference: "SIM-XYZ" },
    { id: "abc-456", status: "pending", provider_reference: null },
  ];
  assert.deepEqual(filterPayments(rows, " SIM-xyz ", "succeeded"), [rows[0]]);
  assert.deepEqual(filterPayments(rows, "abc", "pending"), [rows[1]]);
  assert.deepEqual(filterPayments(rows, "no match", ""), []);
});
test("coalesces slow polls per selection and releases failed requests", async () => {
  let finish,
    calls = 0;
  const load = singleFlight(async (key) => {
    calls++;
    if (key === "failed") throw new Error("offline");
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const first = load("payment");
  assert.equal(load("payment"), first);
  await Promise.resolve();
  assert.equal(calls, 1);
  finish("succeeded");
  assert.equal(await first, "succeeded");
  await assert.rejects(load("failed"), /offline/);
  await assert.rejects(load("failed"), /offline/);
  assert.equal(calls, 3);
});
