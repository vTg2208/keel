# Operations and incident exercises

All commands assume the project virtual environment is active. Substitute its Python path on Windows. Store evidence in `.local`; redact credentials before sharing it.

## First checks

1. `python ops.py doctor`: verify Docker engine, Compose, kind, kubectl.
2. `python ops.py status`: inspect Compose containers, health, restart counts.
3. `python ops.py logs`: inspect the payment ID across structured application logs.
4. GET `/readyz`, payment state, and `/payments/{id}/events`.
5. Check Prometheus Targets and Alertmanager before relying on dashboard graphs.

In kind use the dedicated context: `kubectl --kubeconfig .local/kubeconfig --context kind-payops -n payops ...`. `describe pod` and `get events --sort-by=.lastTimestamp` reveal image, resource, probe, PVC, and scheduling failures.

## Worker outage

Run `python experiments.py --pause 55`. Expected: API remains responsive, payment stays pending, queue grows, worker/down/backlog alerts appear, restarting the worker drains work. A duplicate-safe worker then ignores five duplicate messages. Inspect `.local/experiment-results.json` for recovery duration and unchanged attempt count/reference. Use `--target kind` for a scale-to-zero Kubernetes exercise.

## Worker crash during processing

Submit `timeout_after_success`. While the payment is `processing`, kill the worker (`docker compose kill -s SIGKILL worker`) and restart it. The provider may already have committed a result. The publisher waits for lease expiry, records `lease_expired`, and schedules a new attempt. The simulator returns its durable original reference. An old worker result with a stale token cannot change the payment. Killing the last permitted attempt instead ends in `unknown` with a `reconciliation_required` event and requires inspection of `provider_results` before manual reconciliation.

## Database or broker outage

Stop RabbitMQ with `docker compose stop rabbitmq`. Submit a payment and inspect the increasing outbox gauge. Restart RabbitMQ; the publisher reconnects and drains confirmed deliveries. Never delete its volume to simulate a process outage.

Stop PostgreSQL to observe readiness failures and stalled worker/publisher heartbeats. Restore it and watch reconnect/recovery. There is no successful submission guarantee for a request whose database transaction did not commit; retry with the same idempotency key.

## Timeout and dead letters

Submit scenario `timeout` or run the full smoke command. After exactly three attempts it becomes `failed`, with three processing history events and one failed event. The publisher sends its terminal event to `payops.dead`. Run `docker compose exec -T api python -m payops.exercises queues` to inspect ready message counts. `poison` sends malformed work, which the worker rejects into the same dead queue. Preserve dead-letter evidence; do not blindly replay it.

## Failed release and restoration

Create a healthy release first. In Jenkins run `PayOps` once normally, then run it with `BROKEN_RELEASE=true`. Expected: API rollout never becomes ready, the deployment command restores the previous validated manifest, and the CI build remains failed. Inspect deployment images and the API readiness/smoke result after restoration.

Manual equivalent:

```bash
python ops.py build --tag good-001
python ops.py deploy --tag good-001
docker build --build-arg BASE=payops:good-001 -f Dockerfile.broken -t payops:broken-001 .
python ops.py deploy --tag broken-001
# This command must exit nonzero after restoring good-001.
python ops.py forward --service api
# In another terminal:
python ops.py smoke
```

The initial install has no prior release; on failure its application deployments are removed and database volumes are preserved. Validated current/previous snapshots and used tags live in the cluster's `payops-release` ConfigMap, so a new Jenkins workspace can restore a manually deployed version. Local snapshot files are convenience copies. Application images must remain available in kind; use a fresh immutable tag for each validated release. Schema changes and data are not reverted by application rollback.

## Storage and backups

Compose: `python ops.py backup --file .local/backups/before.dump`. Verify the dump directory with `docker compose exec -T postgres pg_restore --list` using stdin redirection appropriate to your shell, or restore into a separate scratch database. `python ops.py restore --file ... --confirm` performs a single-transaction restore while applications are stopped.

kind: use a binary-safe subprocess to stream `kubectl exec -n payops postgres-0 -- pg_dump -U payops -d payops -Fc` to a file; PowerShell text redirection can corrupt binary dumps on older versions. Scale API, worker, publisher, and simulator to zero before replacing their database. The Compose backup helper deliberately uses binary streams. Backups contain lab state and should be kept private.

## Evidence-based incident report

Copy this template for each observed exercise; fill measured values only:

```text
Date/time (UTC):
Environment, image tag, hardware:
Injected failure and exact command:
Expected behavior:
Observed payment ID and event sequence:
Detection signal and time:
Recovery action and duration:
Data integrity check (payments, provider references, attempts, outbox/DLQ):
Evidence files/screenshots:
Limitations and follow-up:
```
