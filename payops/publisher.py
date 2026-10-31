import signal
import time
from functools import partial

from prometheus_client import start_http_server
from sqlalchemy import func, select

from payops.broker import connect, publish
from payops.config import settings
from payops.db import make_sessions
from payops.domain import recover_expired
from payops.models import Outbox, Payment, utcnow
from payops.telemetry import HEARTBEAT, OUTBOX, PAYMENTS, configure_logging, log


def publish_batch(sessions, send, limit=50):
    count = 0
    # Never mark an event sent until the broker confirms. A crash before commit
    # may deliver it twice; the payment state machine absorbs the duplicate.
    with sessions.begin() as db:
        rows = db.scalars(
            select(Outbox)
            .where(Outbox.published_at.is_(None), Outbox.available_at <= utcnow())
            .order_by(Outbox.available_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for row in rows:
            send(row.id, row.payload, row.route)
            row.published_at = utcnow()
            count += 1
    return count


def update_metrics(sessions):
    with sessions() as db:
        OUTBOX.set(
            db.scalar(select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None)))
        )
        counts = dict(
            db.execute(select(Payment.status, func.count()).group_by(Payment.status)).all()
        )
        for status in (
            "pending",
            "processing",
            "retrying",
            "succeeded",
            "rejected",
            "failed",
            "unknown",
        ):
            PAYMENTS.labels(status).set(counts.get(status, 0))


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
            while running:
                recovered = recover_expired(sessions, config.max_attempts)
                count = publish_batch(sessions, partial(publish, channel))
                update_metrics(sessions)
                HEARTBEAT.labels("publisher").set(time.time())
                if count or recovered:
                    log("outbox_published", count=count, recovered=recovered)
                connection.process_data_events(time_limit=0.5)
        except Exception as exc:
            log("publisher_error", error=type(exc).__name__)
            time.sleep(2)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
