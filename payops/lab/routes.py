import threading
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from payops.lab.artifacts import markdown_report, regression_tests
from payops.lab.controller import ControllerUnavailable, binary_path, run_campaign
from payops.lab.replay import ACTIONS, INVARIANTS, MUTATIONS, replay_trace
from payops.models import LabRun, identifier, utcnow

router = APIRouter()
CAMPAIGN_SLOT = threading.BoundedSemaphore(1)


class CampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(default=42, strict=True, ge=0, le=2_147_483_647)
    budget: int = Field(default=8, strict=True, ge=1, le=32)
    mutations: list[str] = Field(
        default_factory=lambda: list(MUTATIONS), min_length=1, max_length=4
    )

    @field_validator("mutations")
    @classmethod
    def known_mutations(cls, values):
        if len(set(values)) != len(values) or any(v not in MUTATIONS for v in values):
            raise ValueError("Select distinct known mutations")
        return values


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[str] = Field(max_length=32)
    mutation: str = "baseline"

    @field_validator("actions")
    @classmethod
    def known_actions(cls, values):
        if any(v not in ACTIONS for v in values):
            raise ValueError("Trace contains unknown actions")
        return values

    @field_validator("mutation")
    @classmethod
    def known_mutation(cls, value):
        if value not in {"baseline", *MUTATIONS}:
            raise ValueError("Unknown mutation")
        return value


@router.get("/lab", include_in_schema=False)
def workbench():
    return FileResponse(
        Path(__file__).resolve().parents[1] / "static/lab.html",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/lab/catalog")
def catalog():
    return {
        "protocol": 1,
        "mutations": MUTATIONS,
        "invariants": INVARIANTS,
        "actions": sorted(ACTIONS),
        "controller_ready": binary_path().is_file(),
    }


@router.post("/api/lab/campaigns", status_code=201)
def campaign(body: CampaignRequest, request: Request):
    if not CAMPAIGN_SLOT.acquire(blocking=False):
        raise HTTPException(429, "Another campaign is running. Wait for it to finish.")
    try:
        # Verify history storage before spending time on a campaign.
        with request.app.state.sessions() as db:
            db.execute(select(LabRun.id).limit(1))
        report = run_campaign(body.model_dump())
        report.update(id=identifier(), created_at=utcnow().isoformat() + "Z")
        with request.app.state.sessions.begin() as db:
            db.add(LabRun(id=report["id"], report=report))
        return report
    except ControllerUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(
            503, "History storage unavailable. Run the schema migration first."
        ) from None
    finally:
        CAMPAIGN_SLOT.release()


@router.get("/api/lab/campaigns")
def campaigns(request: Request):
    try:
        with request.app.state.sessions() as db:
            rows = db.scalars(select(LabRun).order_by(LabRun.created_at.desc()).limit(30)).all()
            return [
                {key: row.report[key] for key in ("id", "created_at", "seed", "killed", "total")}
                for row in rows
            ]
    except SQLAlchemyError:
        raise HTTPException(
            503, "History storage unavailable. Run the schema migration first."
        ) from None


def saved_report(request, campaign_id):
    try:
        with request.app.state.sessions() as db:
            row = db.get(LabRun, str(campaign_id))
            if row is None:
                raise HTTPException(404, "Campaign not found")
            return row.report
    except SQLAlchemyError:
        raise HTTPException(503, "History storage unavailable") from None


@router.get("/api/lab/campaigns/{campaign_id}")
def get_campaign(campaign_id: UUID, request: Request):
    return saved_report(request, campaign_id)


@router.get("/api/lab/campaigns/{campaign_id}/artifacts/{kind}")
def artifact(campaign_id: UUID, kind: Literal["json", "markdown", "pytest"], request: Request):
    import json

    report = saved_report(request, campaign_id)
    if kind == "json":
        content, media, suffix = json.dumps(report, indent=2), "application/json", "json"
    elif kind == "markdown":
        content, media, suffix = markdown_report(report), "text/markdown", "md"
    else:
        content, media, suffix = regression_tests(report), "text/x-python", "py"
    name = f"test_keel_{campaign_id}.py" if kind == "pytest" else f"keel-{campaign_id}.{suffix}"
    return Response(
        content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.post("/api/lab/replay")
def replay(body: ReplayRequest):
    if not CAMPAIGN_SLOT.acquire(blocking=False):
        raise HTTPException(429, "A campaign or replay is already running.")
    try:
        return replay_trace(body.actions, body.mutation)
    finally:
        CAMPAIGN_SLOT.release()
