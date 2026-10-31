from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scenario = Literal["success", "decline", "timeout", "flaky", "timeout_after_success"]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_minor: int = Field(strict=True, gt=0, le=100_000_000)
    currency: Literal["INR", "USD", "EUR"]
    scenario: Scenario = "success"


class PaymentResponse(PaymentRequest):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    attempts: int
    provider_reference: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    detail: str
    created_at: datetime


class ProviderRequest(PaymentRequest):
    payment_id: str = Field(min_length=1, max_length=36)
    attempt: int = Field(ge=1, le=10)
