import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from payops.db import make_sessions
from payops.domain import IdempotencyConflict, create_payment
from payops.models import Event, Payment
from payops.schemas import EventResponse, PaymentRequest, PaymentResponse
from payops.telemetry import LATENCY, REQUESTS, configure_logging, log


def create_app(sessions=None):
    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        app.state.sessions = sessions or make_sessions()
        yield
        if sessions is None:
            app.state.sessions.kw["bind"].dispose()

    app = FastAPI(
        title="PayOps · Local Payment Reliability Lab", version="0.1.0", lifespan=lifespan
    )
    static = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def metrics(request, call_next):
        start = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_name = route.path if route else "unmatched"
            if route_name not in {"/metrics", "/healthz", "/readyz"}:
                REQUESTS.labels(request.method, route_name, status).inc()
                LATENCY.labels(route_name).observe(time.monotonic() - start)
                log("http_response", method=request.method, route=route_name, status=status)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            with app.state.sessions() as db:
                db.execute(text("SELECT 1 FROM payments LIMIT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Database or schema unavailable") from None
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def prometheus():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/payments", response_model=PaymentResponse, status_code=202)
    def submit(
        body: PaymentRequest,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ):
        if not idempotency_key.strip() or idempotency_key != idempotency_key.strip():
            raise HTTPException(
                422, "Idempotency-Key must be nonblank and have no outer whitespace"
            )
        try:
            payment, created = create_payment(app.state.sessions, idempotency_key, body)
        except IdempotencyConflict:
            raise HTTPException(409, "Idempotency-Key already used with different input") from None
        response.status_code = 202 if created else 200
        response.headers["Location"] = f"/payments/{payment.id}"
        return payment

    @app.get("/payments", response_model=list[PaymentResponse])
    def payments():
        with app.state.sessions() as db:
            return db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(100)).all()

    @app.get("/payments/{payment_id}", response_model=PaymentResponse)
    def payment(payment_id: str):
        with app.state.sessions() as db:
            result = db.get(Payment, payment_id)
            if result is None:
                raise HTTPException(404, "Payment not found")
            return result

    @app.get("/payments/{payment_id}/events", response_model=list[EventResponse])
    def events(payment_id: str):
        with app.state.sessions() as db:
            if db.get(Payment, payment_id) is None:
                raise HTTPException(404, "Payment not found")
            return db.scalars(
                select(Event).where(Event.payment_id == payment_id).order_by(Event.id)
            ).all()

    return app


app = create_app()
