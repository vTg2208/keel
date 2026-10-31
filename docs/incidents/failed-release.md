# Failed Kubernetes release and automatic restoration

Local lab date: 31 October 2026 (Asia/Calcutta).

A validated `payops:verified-002` release was deployed to the local `payops` kind cluster. The test then built `payops:broken-001` with `Dockerfile.broken`, which deliberately raises an exception when the API module imports. The database migration command still works, isolating the failure to the application rollout.

Command: `python ops.py deploy --tag broken-001 --monitoring --logging`.

The new API pod entered `CrashLoopBackOff` and never passed readiness. The previous ready API pod remained available during the attempted rolling update. The deployment command reached its 120-second rollout timeout, restored the validated manifest from the cluster's `payops-release` ConfigMap, waited for all four application deployments, and ran the full payment smoke test against the restored API.

All five scenarios passed after restoration: success, business rejection, one transient retry, bounded timeout exhaustion, and replay of a provider success after response loss. The deployment command exited nonzero as intended; the release record continued to identify `verified-002` as validated. A successful restoration does not turn a failed release into a successful build.

Evidence: `.local/kind-rollback.log`, `.local/kind-deploy.log`, the `payops-release` ConfigMap, and Kubernetes deployment/pod events. No schema or data rollback was attempted. Future database migrations must remain compatible with the previous application version for this restoration method to work.
