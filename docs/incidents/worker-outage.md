# Worker outage and duplicate delivery

Local lab date: 31 October 2026 (Asia/Calcutta). Payment created at 2026-10-30 19:34:30 UTC.

The worker was stopped for 65 seconds using `python experiments.py --pause 65`. Payment `f2bd44a5-4885-4168-8cea-6be453c07493` was accepted and remained pending throughout the planned outage. Prometheus and Alertmanager exposed `PayOpsProcessDown` and `PayOpsBacklog`; `PayOpsDeadLetters` was already active from the intentional timeout smoke test.

Restarting the worker drained the work. The payment reached `succeeded` with one processing attempt. The exercise then published five duplicate messages. The worker preserved the existing provider reference and attempt count, demonstrating duplicate-safe handling after recovery.

Evidence: `.local/alert-experiment.log`, `.local/outage-alerts.json`, the payment's `/events` response, and `.local/experiment-results.json`. The original exercise's recovery duration included the duplicate-check wait; the current script measures recovery immediately when the payment reaches succeeded. Do not use the original duration as a precise processing latency benchmark.

The cause was an intentionally unavailable worker process. PostgreSQL/outbox persistence and the durable broker queue retained accepted work. This verifies process recovery on one computer; it does not test machine or availability-zone failure.
