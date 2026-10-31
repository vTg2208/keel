from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from payops.api import create_app
from payops.domain import (
    IdempotencyConflict,
    claim_payment,
    complete_payment,
    create_payment,
    recover_expired,
)
from payops.models import Event, Outbox, Payment, utcnow
from payops.schemas import PaymentRequest


def request(scenario="success"):
    return PaymentRequest(amount_minor=12500, currency="INR", scenario=scenario)


def submit(sessions, key="test-key", scenario="success"):
    return create_payment(sessions, key, request(scenario))[0]


def test_idempotency_replays_same_payment_and_single_outbox(sessions):
    first, created = create_payment(sessions, "same-key", request())
    second, replay_created = create_payment(sessions, "same-key", request())
    assert created is True
    assert replay_created is False
    assert first.id == second.id
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 1
        assert db.scalar(select(func.count()).select_from(Outbox)) == 1
        assert db.scalar(select(func.count()).select_from(Event)) == 1


def test_idempotency_conflict_does_not_insert(sessions):
    submit(sessions)
    with pytest.raises(IdempotencyConflict):
        create_payment(sessions, "test-key", request("decline"))
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Outbox)) == 1


def test_success_and_duplicate_delivery_are_terminal(sessions):
    payment = submit(sessions)
    claim = claim_payment(sessions, payment.id, max_attempts=3, lease_seconds=30)
    assert claim.attempts == 1
    assert claim_payment(sessions, payment.id, 3, 30) is None
    assert complete_payment(sessions, payment.id, claim.lease_token, "succeeded", "ref-1", 3, 0)
    assert claim_payment(sessions, payment.id, 3, 30) is None
    with sessions() as db:
        saved = db.get(Payment, payment.id)
        assert saved.status == "succeeded"
        assert saved.provider_reference == "ref-1"
        assert saved.attempts == 1


def test_retries_are_bounded_and_create_dead_letter(sessions):
    payment = submit(sessions, scenario="timeout")
    for attempt in range(1, 4):
        claim = claim_payment(sessions, payment.id, 3, 30)
        assert claim.attempts == attempt
        complete_payment(sessions, payment.id, claim.lease_token, "retry", "timeout", 3, 0)
    with sessions() as db:
        assert db.get(Payment, payment.id).status == "failed"
        assert (
            db.scalar(select(func.count()).select_from(Outbox).where(Outbox.route == "dead")) == 1
        )
    assert claim_payment(sessions, payment.id, 3, 30) is None


def test_business_rejection_does_not_retry(sessions):
    payment = submit(sessions, scenario="decline")
    claim = claim_payment(sessions, payment.id, 3, 30)
    complete_payment(sessions, payment.id, claim.lease_token, "rejected", "declined", 3, 0)
    with sessions() as db:
        assert db.get(Payment, payment.id).status == "rejected"
        assert db.scalar(select(func.count()).select_from(Outbox)) == 1


def test_expired_lease_is_recovered_and_stale_result_is_fenced(sessions):
    payment = submit(sessions)
    first = claim_payment(sessions, payment.id, 3, 30)
    with sessions.begin() as db:
        db.get(Payment, payment.id).lease_until = utcnow() - timedelta(seconds=1)
    assert recover_expired(sessions, 3) == 1
    second = claim_payment(sessions, payment.id, 3, 30)
    assert second.lease_token != first.lease_token
    assert not complete_payment(sessions, payment.id, first.lease_token, "rejected", "old", 3, 0)
    assert complete_payment(sessions, payment.id, second.lease_token, "succeeded", "new", 3, 0)
    with sessions() as db:
        assert db.get(Payment, payment.id).provider_reference == "new"


def test_last_attempt_crash_goes_to_dead_letter(sessions):
    payment = submit(sessions)
    claim_payment(sessions, payment.id, 1, 30)
    with sessions.begin() as db:
        db.get(Payment, payment.id).lease_until = utcnow() - timedelta(seconds=1)
    recover_expired(sessions, 1)
    with sessions() as db:
        assert db.get(Payment, payment.id).status == "unknown"
        assert db.scalar(select(Outbox).where(Outbox.route == "dead")) is not None


def test_api_contract_history_replay_conflict_and_missing(sessions):
    with TestClient(create_app(sessions)) as client:
        data = request().model_dump()
        response = client.post("/payments", json=data, headers={"Idempotency-Key": "api-key"})
        assert response.status_code == 202
        payment_id = response.json()["id"]
        replay = client.post("/payments", json=data, headers={"Idempotency-Key": "api-key"})
        assert replay.status_code == 200
        assert replay.json()["id"] == payment_id
        assert client.get(f"/payments/{payment_id}/events").json()[0]["kind"] == "created"
        data["amount_minor"] = 1
        assert (
            client.post("/payments", json=data, headers={"Idempotency-Key": "api-key"}).status_code
            == 409
        )
        assert client.get("/payments/missing").status_code == 404
        assert client.get("/readyz").status_code == 200
        assert client.get("/metrics").status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": 0},
        {"amount_minor": -1},
        {"amount_minor": 1.1},
        {"amount_minor": True},
        {"currency": "XXX"},
        {"scenario": "invalid"},
        {"card_number": "never-accept-card-data"},
    ],
)
def test_api_rejects_invalid_payments(sessions, change):
    with TestClient(create_app(sessions)) as client:
        data = request().model_dump() | change
        assert (
            client.post("/payments", json=data, headers={"Idempotency-Key": "key"}).status_code
            == 422
        )


def test_api_requires_nonblank_bounded_idempotency_key(sessions):
    with TestClient(create_app(sessions)) as client:
        for headers in ({}, {"Idempotency-Key": " "}, {"Idempotency-Key": "x" * 201}):
            assert (
                client.post("/payments", json=request().model_dump(), headers=headers).status_code
                == 422
            )
