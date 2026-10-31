# Failure Workbench Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Discover, reduce, explain and export payment-recovery counterexamples.
**Architecture:** Go orchestrates a versioned JSON-lines Python replay worker; FastAPI
stores reports and serves a JavaScript workbench. Each replay uses isolated SQLite.
**Tech Stack:** Go standard library, existing Python/FastAPI/SQLAlchemy, plain JavaScript.
**Spec:** docs/superpowers/specs/2026-10-31-failure-workbench-design.md

## Global Constraints

- No live database, broker, network chaos or global monkeypatches in experiments.
- At most four mutants, 32 search schedules each, and 32 actions per schedule.
- Reduction guarantees single-deletion minimality for the same invariant only.
- Existing payment semantics and internal service names remain compatible.

## Review Focus

- Invalid traces and mutations fail validation, not silently falling back.
- Bridge failures/timeouts propagate as errors, never mutant survival.
- Baseline failures invalidate findings rather than inflate mutation scores.
- Exported regressions execute real replay assertions and reject the faulty variant.
- Saved runs, navigation and errors remain usable after reload and on narrow screens.

## Task 1: Python replay engine

- [x] Write tests for baseline, four mutations, isolation and invalid input; observe failure.
- [x] Add `payops/lab/replay.py` and `bridge.py`, retaining real domain/provider calls.
- [x] Run targeted tests; verify persistent bridge requests have independent state.

## Task 2: Go discovery controller

- [x] Write Go tests for seeded generation, reduction, baseline rejection and bridge errors.
- [x] Add `cmd/keel-lab`, `internal/discovery`, and `go.mod`.
- [x] Implement bounded RPC and JSON command input/output; run Go tests and vet.
- [x] Run a real Go/Python campaign and check all findings and minimality.

## Task 3: API, persistence and exports

- [x] Write tests for request validation, storage, artifacts and generated test execution.
- [x] Add additive `LabRun`, routes, subprocess wrapper, exports and standalone CLI.
- [x] Run API tests and real executable integration tests.

## Task 4: Browser and delivery

- [x] Add accessible workbench UI with selection, history, traces and export links.
- [x] Integrate multistage Docker build, Go/JS checks in Jenkins, and README instructions.
- [x] Run Python, Go, JS, lint and browser desktop/mobile end-to-end verification.
- [x] Review the final diff and record actual results and limitations.
