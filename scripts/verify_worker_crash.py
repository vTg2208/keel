"""Kill a worker during a provider call and verify lease-based recovery."""

import json
import time
from uuid import uuid4

import httpx

import ops
from scripts.verify_restore import wait_for


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        response = client.post(
            "/payments",
            json={"amount_minor": 100, "currency": "INR", "scenario": "timeout_after_success"},
            headers={"Idempotency-Key": f"worker-crash-{uuid4()}"},
        )
        response.raise_for_status()
        payment_id = response.json()["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if client.get(f"/payments/{payment_id}").json()["status"] == "processing":
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("Never observed a processing payment")
        try:
            ops.compose("kill", "-s", "SIGKILL", "worker")
        finally:
            ops.compose("start", "worker")
        payment = wait_for(client, payment_id, "succeeded")
        events = client.get(f"/payments/{payment_id}/events").json()
        assert any(event["kind"] == "lease_expired" for event in events), events
        assert payment["attempts"] == 2, payment
        result = {
            "exercise": "worker crash during provider call",
            "payment_id": payment_id,
            "attempts": payment["attempts"],
            "status": payment["status"],
            "lease_recovered": True,
        }
        (ops.LOCAL / "worker-crash-results.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == "__main__":
    main()
