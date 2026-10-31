"""Run with PAYOPS_TEST_DATABASE_URL set to a dedicated PostgreSQL test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from payops.domain import claim_payment, create_payment
from payops.models import Base, Outbox, Payment
from payops.schemas import PaymentRequest

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres():
    url = os.getenv("PAYOPS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PAYOPS_TEST_DATABASE_URL to a dedicated PostgreSQL database")
    engine = create_engine(url, pool_size=12)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_concurrent_idempotency_and_worker_claim(postgres):
    key = f"concurrency-{uuid4()}"
    body = PaymentRequest(amount_minor=250, currency="USD")
    with ThreadPoolExecutor(max_workers=8) as pool:
        payments = list(pool.map(lambda _: create_payment(postgres, key, body), range(8)))
    assert len({p.id for p, _ in payments}) == 1
    assert sum(created for _, created in payments) == 1
    payment_id = payments[0][0].id
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: claim_payment(postgres, payment_id, 3, 30), range(8)))
    assert sum(p is not None for p in claims) == 1
    with postgres() as db:
        assert db.get(Payment, payment_id).attempts == 1
        assert (
            db.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.payment_id == payment_id)
            )
            == 1
        )


def test_failed_outbox_insert_rolls_back_payment(postgres):
    key = f"atomicity-{uuid4()}"
    engine = postgres.kw["bind"]

    def fail_outbox(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO outbox"):
            raise RuntimeError("injected outbox storage failure")

    event.listen(engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            create_payment(postgres, key, PaymentRequest(amount_minor=250, currency="USD"))
    finally:
        event.remove(engine, "before_cursor_execute", fail_outbox)
    with postgres() as db:
        assert db.scalar(select(Payment).where(Payment.idempotency_key == key)) is None
