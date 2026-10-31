from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from payops.api import create_app
from payops.domain import claim_payment, create_payment, recover_expired
from payops.models import Outbox, Payment, ProviderResult, utcnow
from payops.schemas import PaymentRequest
from payops.telemetry import REQUESTS


def test_final_attempt_response_loss_preserves_unknown_outcome(sessions):
    payment, _ = create_payment(
        sessions, "ambiguous", PaymentRequest(amount_minor=100, currency="INR")
    )
    claim_payment(sessions, payment.id, 1, 30)
    with sessions.begin() as db:
        db.add(
            ProviderResult(
                payment_id=payment.id,
                request_hash=payment.request_hash,
                outcome="succeeded",
                reference="provider-committed",
            )
        )
        db.get(Payment, payment.id).lease_until = utcnow() - timedelta(seconds=1)
    recover_expired(sessions, 1)
    with sessions() as db:
        assert db.get(Payment, payment.id).status == "unknown"
        assert "unknown" in db.get(Payment, payment.id).last_error
        assert db.scalar(select(Outbox).where(Outbox.route == "dead")) is not None
        assert db.get(ProviderResult, payment.id).outcome == "succeeded"


def test_unhandled_database_errors_count_as_server_errors(sessions):
    app = create_app(sessions)
    metric = REQUESTS.labels("POST", "/payments", "500")
    before = metric._value.get()

    def fail(*_):
        raise OperationalError("database unavailable", {}, Exception("offline"))

    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/payments",
                json={"amount_minor": 100, "currency": "INR"},
                headers={"Idempotency-Key": "offline"},
            )
            assert response.status_code == 500
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert metric._value.get() - before == 1


def test_restore_regenerates_work_for_published_pending_payment(sessions):
    from payops.maintenance import requeue_restored

    payment, _ = create_payment(
        sessions, "restored", PaymentRequest(amount_minor=100, currency="INR")
    )
    with sessions.begin() as db:
        db.scalar(select(Outbox)).published_at = utcnow()
    assert requeue_restored(sessions, 3) == 1
    with sessions() as db:
        rows = db.scalars(select(Outbox).where(Outbox.published_at.is_(None))).all()
        assert len(rows) == 1 and rows[0].payment_id == payment.id
    assert claim_payment(sessions, payment.id, 3, 30) is not None
