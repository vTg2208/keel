"""Destructive-to-lab-data restore verification. Uses only the local synthetic Compose lab."""

import time
from uuid import uuid4

import httpx

import ops


def wait_for(client, payment_id, status):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            result = client.get(f"/payments/{payment_id}")
        except httpx.HTTPError:
            time.sleep(0.5)
            continue
        if result.status_code == 200 and result.json()["status"] == status:
            return result.json()
        time.sleep(0.5)
    raise RuntimeError(f"Payment {payment_id} did not reach {status}")


def main():
    # Reproduce the lost-message restore bug: the backup has a pending payment
    # whose message will be consumed before the backup is restored.
    ops.compose("stop", "worker")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
            response = client.post(
                "/payments",
                json={"amount_minor": 100, "currency": "INR"},
                headers={"Idempotency-Key": f"restore-{uuid4()}"},
            )
            response.raise_for_status()
            payment_id = response.json()["id"]
            time.sleep(3)
            ops.backup(ops.LOCAL / "backups" / "restore-exercise.dump")
            ops.compose("start", "worker")
            wait_for(client, payment_id, "succeeded")
    finally:
        ops.compose("start", "worker")
    ops.run(
        [
            ops.sys.executable,
            "ops.py",
            "restore",
            "--file",
            ops.LOCAL / "backups" / "restore-exercise.dump",
            "--confirm",
        ]
    )
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        result = wait_for(client, payment_id, "succeeded")
        assert result["attempts"] == 1
        events = client.get(f"/payments/{payment_id}/events").json()
        assert any(event["kind"] == "restore_requeued" for event in events)
    print(f"Restore recovery passed: {payment_id}; attempts=1; restore_requeued present")


if __name__ == "__main__":
    main()
