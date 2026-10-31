"""Execute bounded schedules against the real domain and provider in isolated SQLite.

Only broker delivery, process crashes and lease expiry are controlled by the harness.
Mutants are explicit faulty adapters, never global patches to application code.
"""

from collections import deque
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from payops.domain import claim_payment, complete_payment, create_payment, recover_expired
from payops.models import Base, Event, Outbox, Payment, ProviderResult, identifier, utcnow
from payops.publisher import publish_batch
from payops.schemas import PaymentRequest
from payops.simulator import create_app

ACTIONS = {
    "submit",
    "publish",
    "deliver",
    "lose_response",
    "commit",
    "ack",
    "crash",
    "expire_lease",
    "late_response",
    "duplicate",
    "observe",
}
MUTATIONS = {
    "omit_outbox": {
        "title": "Lost processing intent",
        "description": "Accept a payment but omit its durable outbox record.",
        "invariant": "durable_intent",
        "boundary": "Database / publisher",
    },
    "ack_before_commit": {
        "title": "Premature acknowledgement",
        "description": "Acknowledge broker delivery before committing the provider result.",
        "invariant": "commit_before_ack",
        "boundary": "Broker / worker",
    },
    "unstable_provider_key": {
        "title": "Changing provider identity",
        "description": "Use a fresh provider idempotency key for every processing attempt.",
        "invariant": "single_provider_effect",
        "boundary": "Worker / provider",
    },
    "accept_stale_result": {
        "title": "Unfenced worker result",
        "description": "Allow an expired worker to complete a newer worker's claim.",
        "invariant": "stale_result_fenced",
        "boundary": "Worker / database",
    },
}
INVARIANTS = {
    "durable_intent": "An accepted, waiting payment retains durable processing intent.",
    "commit_before_ack": "A claimed delivery is acknowledged only after its result commits.",
    "single_provider_effect": "One logical payment has at most one successful provider effect.",
    "stale_result_fenced": "An expired worker cannot commit a result for a newer claim.",
}


class Replay:
    def __init__(self, sessions, provider, mutation):
        self.sessions, self.provider, self.mutation = sessions, provider, mutation
        self.payment_id = None
        self.ready = deque()
        self.current = None
        self.orphan = None
        self.last_message = None
        self.violations = []
        self.note = ""

    def violation(self, name, actual):
        self.violations.append(
            {
                "invariant": name,
                "expected": INVARIANTS[name],
                "actual": actual,
            }
        )

    def send(self, event_id, payload, route):
        if route == "work":
            self.last_message = {"event_id": event_id, "payment_id": payload["payment_id"]}
            self.ready.append(self.last_message.copy())

    def snapshot(self):
        with self.sessions() as db:
            payment = db.get(Payment, self.payment_id) if self.payment_id else None
            pending = db.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.published_at.is_(None), Outbox.route == "work")
            )
            effects = db.scalar(
                select(func.count())
                .select_from(ProviderResult)
                .where(ProviderResult.outcome == "succeeded")
            )
            events = db.scalars(select(Event.kind).order_by(Event.id)).all()
            return {
                "payment": None
                if payment is None
                else {
                    "status": payment.status,
                    "attempts": payment.attempts,
                    "has_lease": payment.lease_token is not None,
                    "has_provider_reference": payment.provider_reference is not None,
                },
                "outbox_pending": pending,
                "queue_ready": len(self.ready),
                "in_flight": self.current is not None,
                "delivery_acknowledged": bool(self.current and self.current["acknowledged"]),
                "result_committed": bool(self.current and self.current["committed"]),
                "provider_effects": effects,
                "events": list(events),
            }

    def check(self, state):
        payment = state["payment"]
        if state["delivery_acknowledged"] and not state["result_committed"]:
            self.violation(
                "commit_before_ack", "Delivery was acknowledged while its result is uncommitted."
            )
        if (
            payment
            and payment["status"] in {"pending", "retrying"}
            and not state["outbox_pending"]
            and not state["queue_ready"]
            and not state["in_flight"]
        ):
            self.violation("durable_intent", "Payment is waiting with no outbox or broker work.")
        if state["provider_effects"] > 1:
            self.violation(
                "single_provider_effect",
                f"Provider storage contains {state['provider_effects']} successes.",
            )

    def apply(self, action):
        self.note = "Preconditions absent; event had no effect."
        method = getattr(self, f"on_{action}")
        applied = method()
        return bool(applied)

    def on_submit(self):
        if self.payment_id:
            return False
        payment, _ = create_payment(
            self.sessions,
            "keel-experiment",
            PaymentRequest(amount_minor=12500, currency="INR", scenario="success"),
        )
        self.payment_id = payment.id
        if self.mutation == "omit_outbox":
            with self.sessions.begin() as db:
                db.execute(delete(Outbox).where(Outbox.payment_id == payment.id))
        self.note = "Real create_payment transaction accepted a synthetic payment."
        return True

    def on_publish(self):
        count = publish_batch(self.sessions, self.send)
        self.note = f"Real outbox publisher confirmed {count} event(s) to the in-memory broker."
        return count > 0

    def on_deliver(self):
        if self.current or not self.ready:
            return False
        message = self.ready.popleft()
        claim = claim_payment(self.sessions, message["payment_id"], 3, 30)
        if claim is None:
            self.note = "Duplicate or ineligible delivery was ignored by the real state machine."
            return True
        provider_key = identifier() if self.mutation == "unstable_provider_key" else claim.id
        response = self.provider.post(
            "/charge",
            json={
                "payment_id": provider_key,
                "amount_minor": claim.amount_minor,
                "currency": claim.currency,
                "scenario": claim.scenario,
                "attempt": claim.attempts,
            },
        )
        response.raise_for_status()
        result = response.json()
        self.current = {
            "message": message,
            "claim": claim,
            "outcome": result["outcome"],
            "detail": result["reference"],
            "committed": False,
            "acknowledged": self.mutation == "ack_before_commit",
        }
        self.note = "Worker claimed a lease; the real simulator persisted its provider decision."
        if self.mutation == "ack_before_commit":
            self.note += " Faulty adapter acknowledged the delivery immediately."
        return True

    def on_lose_response(self):
        if not self.current or self.current["committed"]:
            return False
        self.current.update(outcome="retry", detail="response lost after provider success")
        self.note = "Provider decision remains stored, but its response is lost to the worker."
        return True

    def on_commit(self):
        if not self.current or self.current["committed"]:
            return False
        claim = self.current["claim"]
        applied = complete_payment(
            self.sessions,
            claim.id,
            claim.lease_token,
            self.current["outcome"],
            self.current["detail"],
            3,
            0,
        )
        self.current["committed"] = applied
        self.note = f"Real complete_payment returned {applied}; retry delay is zero in the lab."
        return applied

    def on_ack(self):
        if not self.current or not self.current["committed"]:
            return False
        self.current = None
        self.note = "Broker delivery acknowledged after the committed result."
        return True

    def on_crash(self):
        if not self.current:
            return False
        self.orphan = self.current
        self.ready.appendleft(self.current["message"].copy())
        self.current = None
        self.note = "Worker lost; unacknowledged message redelivered, response retained as stale."
        return True

    def on_expire_lease(self):
        if not self.payment_id:
            return False
        with self.sessions.begin() as db:
            payment = db.get(Payment, self.payment_id)
            if payment.status != "processing" or self.current:
                return False
            payment.lease_until = utcnow() - timedelta(seconds=1)
        count = recover_expired(self.sessions, 3)
        self.note = f"Controlled lease expiry; real recovery recovered {count} payment(s)."
        return count > 0

    def on_late_response(self):
        if not self.orphan or not self.current or self.current["committed"]:
            return False
        old = self.orphan["claim"]
        with self.sessions.begin() as db:
            payment = db.get(Payment, old.id)
            if payment.lease_token == old.lease_token or payment.status != "processing":
                return False
            if self.mutation == "accept_stale_result":
                # Explicit faulty adapter: impersonate the old ownership before completing.
                payment.lease_token = old.lease_token
        accepted = complete_payment(
            self.sessions,
            old.id,
            old.lease_token,
            self.orphan["outcome"],
            self.orphan["detail"],
            3,
            0,
        )
        if accepted:
            self.violation("stale_result_fenced", "An expired worker committed over a newer lease.")
        self.note = f"Stale completion submitted to real domain code; accepted={accepted}."
        return True

    def on_duplicate(self):
        if not self.last_message:
            return False
        self.ready.append(self.last_message.copy())
        self.note = "Broker delivered another copy of an already published event."
        return True

    def on_observe(self):
        self.note = "Read-only observation; no payment state changed."
        return True


def replay_trace(actions, mutation="baseline"):
    if mutation not in {"baseline", *MUTATIONS}:
        raise ValueError("Unknown mutation")
    if (
        not isinstance(actions, list)
        or len(actions) > 32
        or any(not isinstance(a, str) or a not in ACTIONS for a in actions)
    ):
        raise ValueError("Trace must contain at most 32 known actions")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    steps = []
    try:
        with TestClient(create_app(sessions, delay=0)) as provider:
            replay = Replay(sessions, provider, mutation)
            for index, action in enumerate(actions):
                applied = replay.apply(action)
                state = replay.snapshot()
                replay.check(state)
                steps.append(
                    {
                        "index": index,
                        "action": action,
                        "applied": applied,
                        "note": replay.note,
                        "state": state,
                    }
                )
                if replay.violations:
                    break
            return {"violations": replay.violations, "steps": steps, "state": replay.snapshot()}
    finally:
        engine.dispose()
