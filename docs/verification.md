# Verification

Executed on 31 October 2026 in Asia/Calcutta (logs use UTC). Host: Windows, 16 GB physical RAM, Docker Desktop Linux engine 28.5.2, approximately 7.62 GiB available to Docker, kind 0.30.0, Kubernetes 1.34.0. The application image runs Python 3.11; Jenkins uses Python 3.13.

| Check | Observed result | Evidence |
|---|---|---|
| Unit/API/domain/provider/delivery/recovery/operations suite | 38 passed; two integration tests explicitly skip without their database URL | `.local/unit-tests.log` |
| Dedicated real PostgreSQL integration suite | 2 passed: concurrent idempotency/claiming and payment/outbox atomicity | `.local/integration-final.log` |
| Ruff | Passed | `python ops.py lint` |
| Application image | Built; all four process entry points imported successfully | `.local/build-final.log` |
| Compose smoke | All five provider scenarios reached expected state and attempt count; replay/conflict checks passed | `.local/smoke-final.log` |
| Worker outage and duplicate messages | Payment stayed pending for 65 seconds; recovered with one attempt; five duplicates preserved provider reference | `.local/alert-experiment.log` |
| Broker outage | API accepted work while RabbitMQ was stopped; completed with one attempt after restart | `.local/broker-recovery-results.json` |
| Worker crash during provider call | `SIGKILL`, expired lease recovered, payment succeeded on attempt two | `.local/worker-crash-results.json` |
| PostgreSQL backup/restore | Binary dump restored; previously published pending payment requeued and completed with one attempt | `.local/restore-test.log` |
| Compose metrics and dashboard | Four targets up; 13 provisioned panels; durable payment metrics present | `.local/observability-results.json` |
| Alerts | Dead-letter, process-down, and queue-backlog alerts observed locally | `.local/outage-alerts.json` |
| Configuration validators | Promtool: seven rules valid; amtool: valid; both Alloy configs valid | Executed inside their actual images |
| Centralized logs | Loki returned application log streams from Alloy | `.local/loki-verification.txt` |
| Kubernetes manifests | All 33 resources accepted by API server dry run | `.local/kubernetes-validation.log` |
| kind deployment | Schema job and all application rollouts passed; full five-scenario smoke passed | `.local/kind-deploy.log` |
| Failed Kubernetes release | Broken API failed rollout; previous validated release restored; all five smoke scenarios passed afterward; command remained failed | `.local/kind-rollback.log` |
| kind monitoring/logging | Five targets up including authenticated cAdvisor; container-memory series present; 13 panels; API log streams present | `.local/kind-observability-results.json` |
| kind persistence | PostgreSQL pod deleted/recreated; complete successful payment response remained identical | `.local/kind-persistence-results.json` |

The unit run emits one upstream Starlette warning about its HTTPX test-client integration; it does not fail. The independent PostgreSQL run executes the two tests skipped by the ordinary unit command.

The Jenkins controller, generated admin account, and PayOps pipeline initialized successfully. Build 1 completed checkout, Linux lint/tests, image build, kind deployment, all five payment smoke scenarios, and artifact archival with `SUCCESS`. Build 2 deliberately broke the API, ended `FAILURE`, restored `payops:build-1`, and passed all five recovery smoke scenarios. Evidence: `.local/jenkins-results.json`, `.local/jenkins-build-1.log`, and `.local/jenkins-build-2.log`. Installed plugin versions are recorded in `.local/jenkins-plugin-versions.json`.

After refreshing the pipeline's Terraform-state/cache exclusions, build 3 also completed with `SUCCESS`. The live kind application now runs `payops:build-3`; all application and observability pods are ready. The Jenkins workspace was checked to confirm that the host's Terraform state was excluded. Evidence: `.local/jenkins-final-verification.log` and `.local/jenkins-build-3.log`. Compose remains available separately on the documented loopback URLs; its database is independent from kind.

## Small load exercise

Locust ran with five users, spawn rate one user/second, and a requested 15-second duration. It completed 249 HTTP requests with zero failures: observed aggregate 18.73 requests/second, median 14 ms, approximate p95 130 ms. Requests create, replay, and read payments; they do not wait for terminal processing. This is a small local HTTP exercise under concurrent setup activity, **not a payment-processing capacity benchmark**. Raw data: `.local/load_stats.csv` and `.local/load.log`.

## Boundaries

Terraform 1.13.5 with Kubernetes provider 2.38.0 passed formatting, initialization, and validation. Its saved plan created exactly the separate `payops-practice` namespace and resource quota. A subsequent detailed plan returned exit code zero with no changes. Evidence: `.local/terraform-apply.log` and `.local/terraform-results.json`. Provider selections are recorded in `infra/terraform/.terraform.lock.hcl`; local state stays ignored.

Application rollback does not roll back schema or data. No independent-machine failure, production security certification, real payment provider, or cloud deployment was tested.

Filled incident reports: [worker outage](incidents/worker-outage.md) and [failed release](incidents/failed-release.md). All local evidence is generated from actual runs; it is ignored by Git so credentials and transient lab state are not accidentally published.
