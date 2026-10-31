import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from payops.db import make_sessions
from payops.domain import fingerprint
from payops.models import ProviderResult, identifier
from payops.schemas import PaymentRequest, ProviderRequest
from payops.telemetry import configure_logging, log


def create_app(sessions=None, delay=3):
    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        app.state.sessions = sessions or make_sessions()
        yield
        if sessions is None:
            app.state.sessions.kw["bind"].dispose()

    app = FastAPI(title="PayOps synthetic provider", lifespan=lifespan)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            with app.state.sessions() as db:
                db.execute(text("SELECT 1 FROM provider_results LIMIT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Provider storage unavailable") from None
        return {"status": "ready"}

    @app.post("/charge")
    async def charge(body: ProviderRequest):
        digest = fingerprint(PaymentRequest(**body.model_dump(exclude={"payment_id", "attempt"})))
        factory = app.state.sessions
        with factory() as db:
            existing = db.get(ProviderResult, body.payment_id)
        if existing:
            if existing.request_hash != digest:
                raise HTTPException(409, "Provider idempotency conflict")
            return {"outcome": existing.outcome, "reference": existing.reference}
        if body.scenario == "timeout":
            await asyncio.sleep(delay)
            raise HTTPException(504, "Simulated provider timeout")
        if body.scenario == "flaky" and body.attempt == 1:
            raise HTTPException(503, "Simulated temporary outage")
        outcome = "rejected" if body.scenario == "decline" else "succeeded"
        try:
            with factory.begin() as db:
                result = ProviderResult(
                    payment_id=body.payment_id,
                    request_hash=digest,
                    outcome=outcome,
                    reference=f"sim-{identifier()}",
                )
                db.add(result)
        except IntegrityError:
            with factory() as db:
                result = db.scalar(
                    select(ProviderResult).where(ProviderResult.payment_id == body.payment_id)
                )
            if result is None or result.request_hash != digest:
                raise HTTPException(409, "Provider idempotency conflict") from None
        log("provider_result", payment_id=body.payment_id, outcome=result.outcome)
        if body.scenario == "timeout_after_success" and body.attempt == 1:
            await asyncio.sleep(delay)
        return {"outcome": result.outcome, "reference": result.reference}

    return app


app = create_app()
