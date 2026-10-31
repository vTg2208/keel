from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    # Naive UTC in storage keeps SQLite unit tests and PostgreSQL semantics identical.
    return datetime.now(UTC).replace(tzinfo=None)


def identifier():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    scenario: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    provider_reference: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"))
    route: Mapped[str] = mapped_column(String(8), default="work")
    payload: Mapped[dict] = mapped_column(JSON)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (Index("outbox_due", "published_at", "available_at"),)


class ProviderResult(Base):
    __tablename__ = "provider_results"
    payment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(100))


class LabRun(Base):
    __tablename__ = "lab_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    report: Mapped[dict] = mapped_column(JSON)
