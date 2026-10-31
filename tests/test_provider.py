from fastapi.testclient import TestClient
from sqlalchemy import func, select

from payops.models import ProviderResult
from payops.simulator import create_app


def payload(scenario="success", attempt=1):
    return {
        "payment_id": "p-1",
        "amount_minor": 100,
        "currency": "INR",
        "scenario": scenario,
        "attempt": attempt,
    }


def test_provider_replay_returns_same_charge(sessions):
    with TestClient(create_app(sessions, delay=0)) as client:
        first = client.post("/charge", json=payload()).json()
        second = client.post("/charge", json=payload(attempt=2)).json()
        assert first == second
        assert first["outcome"] == "succeeded"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(ProviderResult)) == 1


def test_provider_lost_response_replays_durable_success(sessions):
    with TestClient(create_app(sessions, delay=0)) as client:
        first = client.post("/charge", json=payload("timeout_after_success")).json()
        second = client.post("/charge", json=payload("timeout_after_success", 2)).json()
        assert second == first
        assert second["outcome"] == "succeeded"


def test_provider_flaky_is_retryable_then_succeeds(sessions):
    with TestClient(create_app(sessions, delay=0)) as client:
        assert client.post("/charge", json=payload("flaky")).status_code == 503
        assert client.post("/charge", json=payload("flaky", 2)).json()["outcome"] == "succeeded"


def test_provider_conflicting_reuse_rejected(sessions):
    with TestClient(create_app(sessions, delay=0)) as client:
        client.post("/charge", json=payload())
        assert client.post("/charge", json=payload() | {"amount_minor": 101}).status_code == 409
