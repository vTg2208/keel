"""Explicit database recovery operations; application processes must be stopped."""

from sqlalchemy import select

from payops.config import settings
from payops.db import make_sessions
from payops.domain import TERMINAL, enqueue, history, mark_unknown
from payops.models import Payment, utcnow


def requeue_restored(sessions, max_attempts):
    with sessions.begin() as db:
        payments = db.scalars(
            select(Payment).where(Payment.status.not_in(TERMINAL)).with_for_update()
        ).all()
        for payment in payments:
            payment.lease_token = None
            payment.lease_until = None
            payment.updated_at = utcnow()
            if payment.attempts >= max_attempts:
                mark_unknown(db, payment)
            else:
                payment.status = "retrying" if payment.attempts else "pending"
                payment.next_attempt_at = utcnow()
                history(
                    db, payment, "restore_requeued", "Fresh durable work after database restore"
                )
                enqueue(db, payment)
        return len(payments)


if __name__ == "__main__":
    count = requeue_restored(make_sessions(), settings().max_attempts)
    print(f"Reconciled {count} nonterminal payments after restore")
