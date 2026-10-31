"""Reproducible worker outage and duplicate-delivery exercises, with saved evidence."""

import argparse
import json
import time
from uuid import uuid4

import httpx

import ops


def exercise(target, base_url, pause):
    def worker(action):
        if target == "compose":
            ops.compose("stop" if action == "stop" else "start", "worker")
        else:
            ops.kubectl(
                "scale",
                "deployment/worker",
                "--replicas=" + ("0" if action == "stop" else "1"),
                "-n",
                "payops",
            )
            if action == "stop":
                ops.kubectl(
                    "wait",
                    "--for=delete",
                    "pod",
                    "-l",
                    "app=worker",
                    "-n",
                    "payops",
                    "--timeout=60s",
                )

    with httpx.Client(base_url=base_url, timeout=10) as client:
        worker("stop")
        started = time.monotonic()
        try:
            response = client.post(
                "/payments",
                json={"amount_minor": 100, "currency": "INR"},
                headers={"Idempotency-Key": f"outage-{uuid4()}"},
            )
            response.raise_for_status()
            payment_id = response.json()["id"]
            print(f"Worker stopped; payment {payment_id} must remain pending for {pause}s")
            while time.monotonic() - started < pause:
                payment = client.get(f"/payments/{payment_id}").json()
                assert payment["status"] == "pending", payment
                time.sleep(1)
        finally:
            worker("start")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            payment = client.get(f"/payments/{payment_id}").json()
            if payment["status"] == "succeeded":
                break
            time.sleep(0.5)
        assert payment["status"] == "succeeded", payment
        recovery_seconds = round(time.monotonic() - started - pause, 2)
        if target == "compose":
            ops.compose(
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "payops.exercises",
                "duplicate",
                "--payment-id",
                payment_id,
            )
        else:
            ops.kubectl(
                "exec",
                "deployment/api",
                "-n",
                "payops",
                "--",
                "python",
                "-m",
                "payops.exercises",
                "duplicate",
                "--payment-id",
                payment_id,
            )
        time.sleep(3)
        after = client.get(f"/payments/{payment_id}").json()
        assert (
            after["attempts"] == 1 and after["provider_reference"] == payment["provider_reference"]
        )
        result = {
            "exercise": "worker outage and duplicate delivery",
            "target": target,
            "payment_id": payment_id,
            "outage_seconds": pause,
            "attempts": after["attempts"],
            "recovery_seconds": recovery_seconds,
            "status": "passed",
        }
        ops.LOCAL.mkdir(exist_ok=True)
        (ops.LOCAL / "experiment-results.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["compose", "kind"], default="compose")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--pause", type=int, default=55, help="55s allows backlog/down alerts to fire"
    )
    args = parser.parse_args()
    if args.pause < 1:
        parser.error("pause must be positive")
    exercise(args.target, args.base_url, args.pause)
