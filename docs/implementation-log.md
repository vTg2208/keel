# Implementation record

- Supplied proposal is the accepted scope; user requests implementation end to end. Routine implementation choices are delegated by that request.
- Empty workspace, Python 3.11 available. Docker client installed; engine initially stopped. Ubuntu WSL2 present.
- Implement inline. No Git repository existed, so no branch/worktree or automatic commits are needed.
- Verification evidence and runtime constraints will be recorded here as work progresses.
- Application/domain/provider/reliability implemented. Unit and API suite green; real PostgreSQL concurrency and outbox-atomicity tests green.
- Compose live smoke: success, decline, flaky retry, timeout exhaustion, and provider response loss all reached expected states and attempt counts.
- Live worker outage + five duplicate messages passed. A 65-second outage triggered PayOpsProcessDown and PayOpsBacklog, then recovered with one attempt.
- Live broker outage passed: API accepted durable work while RabbitMQ was stopped; payment completed after restart.
- Live worker SIGKILL during a provider call passed: lease_expired recorded, succeeded on attempt two.
- Binary PostgreSQL backup/restore passed, including a previously published pending payment whose broker message had already been consumed. Restore requeued it durably.
- Live Compose monitoring: four targets up, 13 dashboard panels provisioned, dead-letter and outage alerts observed. Promtool, amtool, Docker Alloy config, and Kubernetes Alloy config validated. Loki returned API log streams.
- Locust: 5 users over a 15-second requested run, 249 HTTP requests, 0 failures, observed aggregate 18.73 requests/second, median 14 ms, approximate p95 130 ms. This measures this small local HTTP run, not payment throughput capacity.
- Reviewer findings fixed with regressions: restore stranding, workspace-dependent rollback, mutable validated release tags, missing 500 metrics, and ambiguous final-attempt outcome. Final-attempt crashes now become unknown/reconciliation_required with a durable dead letter.
- Extra validation fixed malformed provider JSON handling and occupied port-forward validation.
- kind created successfully with Kubernetes v1.34.0; server-side dry run accepted all 33 resources. Standard multi-platform image loading hit the known containerd digest issue; single-platform archive loading verified and implemented, with cached node-image checks and archive cleanup.
- Kubernetes RabbitMQ exec probes exceeded their default one-second timeout under CPU limits; changed to TCP probes and restarted deployment validation.
- Jenkins build initially selected vulnerable transitive plugins on the old core; upgraded to the current LTS 2.580.2 and rebuilding with Docker CLI 28. Final CI execution remains in progress.
- Kubernetes full deployment and five-scenario smoke passed. The deliberately broken API image failed rollout; automatic restoration returned to verified-002 and all five scenarios passed again. Command failed as intended while preserving the validated release record.
- Kubernetes observability passed: all five targets including kubelet/cAdvisor up, 16 container-memory series observed, dashboard has 13 panels, and Loki returned API logs through Alloy.
- PostgreSQL pod deletion/recreation in kind preserved the complete successful payment response, including provider reference and attempt count.
- Jenkins default geographic plugin mirror repeatedly returned NoHttpResponseException. Verified the official archives endpoint responds, then configured plugin-manager's supported download URL override to use it with normal checksum verification.
- Further investigation found the upstream installer downloads 64 plugins concurrently and stages the whole set before installing it. Truncated responses prevented installation. Resolved its 59-plugin dependency graph, pinned every version and official SHA-256 checksum in plugins.lock.json, and added a tested two-request downloader with per-file retries and a persistent verified cache. The image build now uses this lock instead of repeated all-or-nothing downloads.
- Archive downloads were also slow for larger files. Tested mirrors from Jenkins' official mirror list: Singapore and XMission both delivered the same 1.77 MB artifact in about seven seconds with the expected SHA-256. The downloader now prefers Singapore and falls back to XMission and the official archive; custom test endpoints never contact external fallbacks.
- Jenkins image completed: all 59 checksum-verified plugins installed in about 74 seconds with the targeted downloader. Controller/account/job initialized successfully. Jenkins build 1 passed source snapshot, Linux lint/tests, image build, kind deployment, all five smoke scenarios, and artifact archival. Build 2 is exercising deliberate rollout failure and restoration.
- Terraform optional practice verified with local Terraform 1.13.5 and Kubernetes provider 2.38.0: validate/plan/apply passed, exactly two separately owned resources created, subsequent detailed plan exit code 0 (no drift). State and provider caches excluded from source snapshots/build contexts; provider lock included.
- Jenkins build 2 failed as intended, restored build-1, passed recovery smoke, and archived results. After refreshing the pipeline exclusions, build 3 succeeded through every stage; verified that Terraform state was absent from the Jenkins source snapshot. Final kind application release is build-3, all pods ready; Compose services also healthy.
- Final local suite: 38 passed, two PostgreSQL tests skipped by the ordinary command and separately executed successfully (2 passed). Ruff passed. One upstream Starlette/HTTPX test-client deprecation warning remains, without test failures.
- All requested phases, optional local Terraform practice, actual incident reports, setup/runbooks, and verification evidence are delivered. No remote repository, cloud resources, paid accounts, or real payment provider was created.

## Payment console · 31 October 2026

- Added a plain payment ledger at `/`, served by FastAPI with locally bundled assets and font. No frontend build step or separate server is needed. The API reference remains at `/docs`.
- Submission supports exact decimal-to-minor-unit conversion, all three currencies and five provider scenarios, generated or custom idempotency keys, and clear replay/conflict outcomes. The ledger and selected payment's event history poll real API data every three seconds; polling can be paused.
- Details preserve unknown/reconciliation status accurately. Mobile shows ID, amount, and status in the ledger, with the remaining fields in the accessible modal panel. Loading, empty search, API outage, stale data, validation, and submission errors have explicit states.
- Independent review identified slow-poll starvation, lost keyboard focus, and an overly long submission lock. Fixed all three; added a concurrency regression and verified focus restoration with Escape in the browser.
- Verification: 40 Python tests passed, two optional PostgreSQL tests skipped by the standard suite; four JavaScript tests passed; Ruff and JavaScript syntax checks passed. Docker image and Python wheel built; wheel inspection confirmed all seven static assets including the font/license.
- Live frontend: a ₹125 temporary-failure payment succeeded on attempt two, duplicate replay returned the original payment, changed input returned a conflict, and invalid decimals were rejected. During a controlled API outage, the form preserved its amount and request key; retry after recovery succeeded. All Compose services were healthy afterward.
- Five-scenario smoke passed against the updated API. Desktop and 390px mobile screens, search/status filters, event history, and browser console were checked. Compose API runs the frontend image; the independently deployed kind release remains build-3.
- Visual fidelity: retained the design reference's flat ledger, restrained navy/semantic colors, Plex typography, fine rules, and whitespace. Actual API rows replace illustrative data; mobile reduces columns and uses a full-width detail panel.
