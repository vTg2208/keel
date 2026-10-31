import json
import signal
import time

import httpx
from prometheus_client import start_http_server

from payops.broker import WORK_QUEUE, connect
from payops.config import settings
from payops.db import make_sessions
from payops.domain import claim_payment, complete_payment
from payops.models import utcnow
from payops.telemetry import (
    COMPLETION_TIME,
    COMPLETIONS,
    HEARTBEAT,
    configure_logging,
    log,
)


def call_provider(client, payment):
    try:
        response = client.post(
            "/charge",
            json={
                "payment_id": payment.id,
                "amount_minor": payment.amount_minor,
                "currency": payment.currency,
                "scenario": payment.scenario,
                "attempt": payment.attempts,
            },
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("outcome") not in ("succeeded", "rejected"):
            return "retry", "invalid provider outcome"
        reference = result.get("reference")
        if not isinstance(reference, str) or not 1 <= len(reference) <= 100:
            return "retry", "invalid provider reference"
        return result["outcome"], reference
    except (httpx.HTTPError, ValueError):
        return "retry", "provider unavailable or response invalid"


def process_message(sessions, client, payload, config):
    payment_id = payload["payment_id"]
    payment = claim_payment(sessions, payment_id, config.max_attempts, config.lease_seconds)
    if payment is None:
        return "duplicate"
    outcome, detail = call_provider(client, payment)
    applied = complete_payment(
        sessions,
        payment.id,
        payment.lease_token,
        outcome,
        detail,
        config.max_attempts,
        config.retry_seconds * 2 ** (payment.attempts - 1),
    )
    if applied:
        COMPLETIONS.labels(outcome).inc()
        if outcome in {"succeeded", "rejected"} or payment.attempts >= config.max_attempts:
            COMPLETION_TIME.observe((utcnow() - payment.created_at).total_seconds())
    log(
        "payment_processed",
        payment_id=payment.id,
        attempt=payment.attempts,
        outcome=outcome,
        applied=applied,
    )
    return outcome


def main():
    configure_logging()
    config = settings()
    sessions = make_sessions()
    start_http_server(config.metrics_port)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        connection = None
        try:
            connection, channel = connect(config.rabbitmq_url)
            with httpx.Client(
                base_url=config.provider_url, timeout=config.provider_timeout
            ) as client:
                while running:
                    method, properties, body = channel.basic_get(WORK_QUEUE, auto_ack=False)
                    if method:
                        try:
                            payload = json.loads(body)
                            if (
                                not isinstance(payload, dict)
                                or not isinstance(payload.get("payment_id"), str)
                                or not 1 <= len(payload["payment_id"]) <= 36
                            ):
                                raise ValueError("Invalid event")
                        except (ValueError, UnicodeDecodeError):
                            channel.basic_reject(method.delivery_tag, requeue=False)
                            log("invalid_message_dead_lettered")
                            continue
                        process_message(sessions, client, payload, config)
                        # Commit result + next outbox before acknowledging the delivery.
                        channel.basic_ack(method.delivery_tag)
                    HEARTBEAT.labels("worker").set(time.time())
                    connection.process_data_events(time_limit=0.1 if method else 0.5)
        except Exception as exc:
            log("worker_error", error=type(exc).__name__)
            time.sleep(2)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
