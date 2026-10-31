import pytest
from sqlalchemy import select

from payops.config import Settings
from payops.domain import create_payment
from payops.models import Outbox, Payment
from payops.publisher import publish_batch
from payops.schemas import PaymentRequest
from payops.worker import call_provider, process_message


@pytest.mark.parametrize(
    "response",
    [[], None, 1, {"outcome": []}, {"outcome": {}}, {"outcome": "succeeded", "reference": None}],
)
def test_malformed_provider_response_is_retryable(sessions, response):
    import httpx

    payment, _ = create_payment(
        sessions, "malformed", PaymentRequest(amount_minor=100, currency="INR")
    )
    with httpx.Client(
        base_url="http://provider",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    ) as client:
        assert call_provider(client, payment)[0] == "retry"


def test_broker_failure_leaves_outbox_unpublished(sessions):
    create_payment(sessions, "key", PaymentRequest(amount_minor=100, currency="INR"))

    def unavailable(*_):
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        publish_batch(sessions, unavailable)
    with sessions() as db:
        assert db.scalar(select(Outbox)).published_at is None
    delivered = []
    assert publish_batch(sessions, lambda *args: delivered.append(args)) == 1
    assert publish_batch(sessions, lambda *args: delivered.append(args)) == 0
    assert len(delivered) == 1


def test_worker_handles_response_loss_and_duplicate(sessions):
    import httpx

    payment, _ = create_payment(sessions, "key", PaymentRequest(amount_minor=100, currency="INR"))
    config = Settings(retry_seconds=0)
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(200, json={"outcome": "succeeded", "reference": "same-charge"})

    with httpx.Client(
        base_url="http://provider", transport=httpx.MockTransport(provider)
    ) as client:
        assert process_message(sessions, client, {"payment_id": payment.id}, config) == "retry"
        assert process_message(sessions, client, {"payment_id": payment.id}, config) == "succeeded"
        assert process_message(sessions, client, {"payment_id": payment.id}, config) == "duplicate"
    with sessions() as db:
        assert db.get(Payment, payment.id).attempts == 2
        assert db.get(Payment, payment.id).provider_reference == "same-charge"
