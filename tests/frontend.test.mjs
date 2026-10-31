import test from "node:test";
import assert from "node:assert/strict";
import {
  toMinor,
  utcDate,
  filterPayments,
  singleFlight,
} from "../payops/static/core.mjs";

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
