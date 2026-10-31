"""Verify the API accepts durable work during a local RabbitMQ process outage."""

import json
import time
from uuid import uuid4

import httpx

import ops
from scripts.verify_restore import wait_for


def main():
    ops.compose("stop", "rabbitmq")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
            response = client.post(
                "/payments",
                json={"amount_minor": 100, "currency": "INR"},
                headers={"Idempotency-Key": f"broker-outage-{uuid4()}"},
            )
            response.raise_for_status()
            payment_id = response.json()["id"]
            time.sleep(3)
            assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"
    finally:
        ops.compose("start", "rabbitmq")
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        payment = wait_for(client, payment_id, "succeeded")
    result = {
        "exercise": "broker outage",
        "payment_id": payment_id,
        "status": payment["status"],
        "attempts": payment["attempts"],
    }
    (ops.LOCAL / "broker-recovery-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
