# PayOps local reliability lab

The supplied proposal and architecture are the implementation specification. Build a simulated payment system entirely on local infrastructure, using Python/FastAPI, PostgreSQL, RabbitMQ, Docker Compose, kind, Jenkins, Prometheus, Grafana, Alertmanager, Loki, Alloy, and Locust. No cloud account or real payment provider is involved.

## Approach

Use one Python package/image with separate API, publisher, worker, and simulator entry points. Compose is the development entry point; Kubernetes runs the same image and configuration. A Python operations CLI provides portable commands on Windows and Linux/WSL, wrapped by Make. Jenkins runs outside kind and invokes the same commands. This avoids divergent deployment implementations. A microservice repository per component would add coordination without improving this single-machine lab.

## Reliability contract

Amounts are positive integer minor units. API idempotency keys are unique; reusing a key with different normalized input returns 409. Payment and outbox insertion share a database transaction. Publisher uses row locks, durable messages, mandatory routing, and publisher confirms. Publishing is at least once; worker duplicates are safe. Worker leases and fencing tokens prevent stale workers from overwriting newer results. Retries use durable scheduled outbox rows and a fixed attempt bound. Terminal processing failures generate a durable dead-letter message. Business rejection is terminal without retry. Provider simulator stores its own idempotent result to model a response lost after a successful charge. Event history explains every transition.

## Operations and boundaries

Generate development secrets into ignored files; bind host ports to loopback. Persistent database/broker volumes survive pod/container restart. Cluster deletion does not preserve volumes. Backup/restore is explicit. Jenkins Docker access is trusted-host access and stays local. Terraform owns only an optional separate namespace and quota. Monitor API latency/errors, backlog, failures/retries, process health, and CPU/memory; collect structured logs. Include deterministic failure exercises and release rollback; schema rollback is not implied.

## Verification

Test idempotency, concurrency on PostgreSQL, transaction atomicity, duplicate delivery, retry exhaustion, lease recovery/fencing, provider response loss, DLQ routing, API validation, and error health checks. Exercise actual Compose services and kind when the host runtime permits. Record any runtime limitations rather than claiming unexecuted deployment checks.
