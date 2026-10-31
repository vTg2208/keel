import hashlib
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from payops.models import Event, Outbox, Payment, identifier, utcnow

TERMINAL = {"succeeded", "rejected", "failed", "unknown"}


class IdempotencyConflict(Exception):
    pass


def fingerprint(request):
    return hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True).encode()).hexdigest()


def enqueue(db, payment, route="work", available_at=None):
    db.add(
        Outbox(
            payment_id=payment.id,
            route=route,
            payload={"payment_id": payment.id, "reason": payment.last_error},
            available_at=available_at or utcnow(),
        )
    )


def history(db, payment, kind, detail=""):
    db.add(Event(payment_id=payment.id, kind=kind, detail=detail))


def create_payment(sessions, key, request):
    digest = fingerprint(request)
    try:
        with sessions.begin() as db:
            payment = Payment(
                id=identifier(), idempotency_key=key, request_hash=digest, **request.model_dump()
            )
            db.add(payment)
            db.flush()
            enqueue(db, payment)
            history(db, payment, "created")
        return payment, True
    except IntegrityError:
        # A concurrent insert waits for the unique constraint owner to commit.
        with sessions() as db:
            payment = db.scalar(select(Payment).where(Payment.idempotency_key == key))
            if payment is None:
                raise
            if payment.request_hash != digest:
                raise IdempotencyConflict from None
            return payment, False


def claim_payment(sessions, payment_id, max_attempts, lease_seconds):
    with sessions.begin() as db:
        payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        now = utcnow()
        if (
            payment is None
            or payment.status in TERMINAL
            or payment.status == "processing"
            or payment.next_attempt_at > now
        ):
            return None
        if payment.attempts >= max_attempts:
            return None
        payment.status = "processing"
        payment.attempts += 1
        payment.lease_token = identifier()
        payment.lease_until = now + timedelta(seconds=lease_seconds)
        payment.updated_at = now
        history(db, payment, "processing", f"attempt {payment.attempts}")
    return payment


def retry_or_fail(db, payment, max_attempts, retry_seconds, error):
    payment.last_error = error
    payment.lease_until = None
    payment.lease_token = None
    if payment.attempts >= max_attempts:
        payment.status = "failed"
        history(db, payment, "failed", error)
        enqueue(db, payment, "dead")
    else:
        payment.status = "retrying"
        payment.next_attempt_at = utcnow() + timedelta(seconds=retry_seconds)
        history(db, payment, "retry_scheduled", error)
        enqueue(db, payment, available_at=payment.next_attempt_at)


def complete_payment(sessions, payment_id, token, outcome, detail, max_attempts, retry_seconds):
    with sessions.begin() as db:
        payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None or payment.status != "processing" or payment.lease_token != token:
            return False
        payment.updated_at = utcnow()
        if outcome == "retry":
            retry_or_fail(db, payment, max_attempts, retry_seconds, detail)
        elif outcome in {"succeeded", "rejected"}:
            payment.status = outcome
            payment.lease_until = None
            payment.lease_token = None
            if outcome == "succeeded":
                payment.provider_reference = detail
                payment.last_error = None
            else:
                payment.last_error = detail
            history(db, payment, outcome, detail)
        else:
            raise ValueError(f"Unknown provider outcome: {outcome}")
    return True


def recover_expired(sessions, max_attempts):
    with sessions.begin() as db:
        payments = db.scalars(
            select(Payment)
            .where(Payment.status == "processing", Payment.lease_until < utcnow())
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for payment in payments:
            payment.updated_at = utcnow()
            history(db, payment, "lease_expired", "Worker lost; provider outcome may be unknown")
            if payment.attempts >= max_attempts:
                mark_unknown(db, payment)
            else:
                retry_or_fail(db, payment, max_attempts, 0, "processing lease expired")
        return len(payments)


def mark_unknown(db, payment):
    payment.status = "unknown"
    payment.last_error = "provider outcome unknown after final processing lease expired"
    payment.lease_until = None
    payment.lease_token = None
    history(db, payment, "reconciliation_required", payment.last_error)
    enqueue(db, payment, "dead")
