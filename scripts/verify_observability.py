"""Verify live Compose targets, provisioned dashboard, and locally visible alerts."""

import json
import time

import httpx

import ops


def main():
    creds = ops.credentials()
    with httpx.Client(timeout=10) as client:
        deadline = time.monotonic() + 90
        while True:
            try:
                health = client.get("http://127.0.0.1:3000/api/health")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Grafana did not become ready")
            time.sleep(1)
        targets = client.get("http://127.0.0.1:9090/api/v1/targets").json()["data"]["activeTargets"]
        assert len(targets) == 4, targets
        assert all(target["health"] == "up" for target in targets), targets
        dashboard = client.get(
            "http://127.0.0.1:3000/api/dashboards/uid/payops",
            auth=("admin", creds["GRAFANA_PASSWORD"]),
        )
        dashboard.raise_for_status()
        panels = dashboard.json()["dashboard"]["panels"]
        assert len(panels) == 13
        query = client.get(
            "http://127.0.0.1:9090/api/v1/query", params={"query": "payops_payments"}
        )
        assert query.json()["data"]["result"]
        alerts = client.get("http://127.0.0.1:9093/api/v2/alerts")
        alerts.raise_for_status()
        result = {
            "targets": {target["labels"]["job"]: target["health"] for target in targets},
            "dashboard_panels": len(panels),
            "alerts": sorted({alert["labels"]["alertname"] for alert in alerts.json()}),
        }
        (ops.LOCAL / "observability-results.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
