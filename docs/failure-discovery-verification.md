# Failure workbench verification

Executed 31 October 2026, Asia/Calcutta. Windows host, Go 1.25.6,
Python 3.11 virtual environment, bundled Chromium/Playwright, Docker Linux engine.

| Check | Observed result |
|---|---|
| Full Python suite | 66 passed, 2 PostgreSQL tests skipped without their dedicated database URL |
| Added CLI/setup checks, run separately after the full suite | 3 passed: missing controller, CI success, CI survivor failure |
| Current collection | 71 tests: 69 tested successfully, 2 PostgreSQL skips |
| Go | All 6 discovery tests passed; `go vet ./...` passed |
| JavaScript | 4 existing frontend helper tests passed; workbench syntax check passed |
| Ruff | Passed across the repository |
| Real Go/Python campaign | Seed 42, budget 8; 4/4 known faulty adapters detected in 131 replay evaluations |
| Reduction | Independent Python replay verified that every single-event deletion removes the same violation |
| Exported pytest | All baseline tests passed; each of four selected faulty adapters caused its corresponding test to fail |
| Protocol | Invalid version returned an error; successive faulty and baseline requests remained isolated |
| Browser | `/lab` identity/content, all four findings, event inspection, baseline comparison, replay, download, saved-run reload, validation and console health passed |
| Responsive layout | 1440x1100 desktop and 390x844 mobile; no horizontal overflow; payment-console navigation also checked on mobile |
| Review | Independent read-only code review found no important confirmed defect; minor original-schedule visibility gap fixed and browser-checked |
| Docker build | `keel:lab-verified` built successfully with Go executable in the Python runtime image |
| Constrained Linux execution | Docker `--network none --memory 256m --cpus 0.5`; all four faults detected in 131 executions; default artifact directory writable as nonroot user |

The browser plugin was unavailable; browser verification used the already bundled
Playwright/Chromium runtime. Screenshots and a downloaded regression file are ignored
local artifacts under `.local/lab-*` and `.local/browser-exported-regression.py`.
The browser campaign completed in approximately 10–12 seconds on this host; this is
an observation, not a performance guarantee.

## Observed reductions, seed 42

| Fault | Original scheduled events | Reduced events |
|---|---:|---:|
| Omitted durable intent | 10 | 1 |
| Premature acknowledgement | 10 | 3 |
| Changing provider identity | 11 | 6 |
| Accepting stale worker result | 11 | 7 |

The six-event provider counterexample was `submit → publish → deliver → crash →
expire_lease → deliver`. The broker adapter retains the unacknowledged delivery across
the crash, so another publish event is unnecessary in the reduced sequence. With the
faulty provider identity adapter, provider storage contains two successful results;
the correct implementation preserves a single provider effect.

## Boundaries

The existing upstream Starlette/HTTPX test-client deprecation warning remains. No
application dependency upgrade was made to hide it. Jenkins configuration was updated,
but the existing Jenkins controller was not rebuilt and its new pipeline was not run.
The existing Compose/kind deployments were not replaced. Real PostgreSQL concurrency
tests were not rerun for this feature; SQLite/controlled broker results do not replace
them. Browser checks cover Chromium on the two stated viewports.
