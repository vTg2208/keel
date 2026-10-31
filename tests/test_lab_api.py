import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from payops.api import create_app
from payops.lab import routes
from payops.models import Payment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def lab_binary(tmp_path_factory):
    if not shutil.which("go"):
        pytest.skip("Go 1.25+ required for the cross-language integration suite")
    target = tmp_path_factory.mktemp("go") / ("keel-lab.exe" if os.name == "nt" else "keel-lab")
    subprocess.run(["go", "build", "-o", str(target), "./cmd/keel-lab"], cwd=ROOT, check=True)
    return target


@pytest.fixture
def lab_client(sessions, lab_binary, monkeypatch):
    monkeypatch.setenv("KEEL_LAB_BINARY", str(lab_binary))
    with TestClient(create_app(sessions)) as client:
        yield client


def campaign(client):
    response = client.post(
        "/api/lab/campaigns",
        json={
            "seed": 42,
            "budget": 4,
            "mutations": [
                "omit_outbox",
                "ack_before_commit",
                "unstable_provider_key",
                "accept_stale_result",
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_real_go_python_campaign_persists_and_reduces_all_faults(lab_client, sessions):
    from payops.lab.replay import replay_trace

    report = campaign(lab_client)
    assert report["killed"] == report["total"] == 4
    assert lab_client.get(f"/api/lab/campaigns/{report['id']}").json() == report
    assert lab_client.get("/api/lab/campaigns").json()[0]["id"] == report["id"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 0
    for finding in report["findings"]:
        assert finding["status"] == "killed"
        assert finding["one_minimal"] is True
        assert finding["baseline"]["violations"] == []
        invariant = finding["minimal"]["violations"][0]["invariant"]
        trace = finding["minimal_trace"]
        for index in range(len(trace)):
            result = replay_trace(trace[:index] + trace[index + 1 :], finding["mutation"])
            assert invariant not in [v["invariant"] for v in result["violations"]]


def test_downloaded_regressions_pass_baseline_and_fail_mutants(lab_client, tmp_path):
    report = campaign(lab_client)
    base = f"/api/lab/campaigns/{report['id']}/artifacts"
    assert lab_client.get(base + "/json").json() == report
    markdown = lab_client.get(base + "/markdown")
    assert markdown.status_code == 200
    assert "1-minimal" in markdown.text
    exported = lab_client.get(base + "/pytest")
    assert "attachment" in exported.headers["content-disposition"]
    path = tmp_path / "test_keel_regression.py"
    path.write_text(exported.text, encoding="utf-8")
    env = os.environ | {"PYTHONPATH": str(ROOT)}
    env.pop("KEEL_MUTATION", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for mutation in [f["mutation"] for f in report["findings"]]:
        broken = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "-k", mutation],
            cwd=ROOT,
            env=env | {"KEEL_MUTATION": mutation},
            capture_output=True,
            text=True,
        )
        assert broken.returncode == 1, broken.stdout + broken.stderr
        assert "AssertionError" in broken.stdout


@pytest.mark.parametrize(
    "body",
    [
        {"budget": 0},
        {"budget": 33},
        {"seed": -1},
        {"seed": 1.5},
        {"mutations": []},
        {"mutations": ["shell"]},
        {"mutations": ["omit_outbox", "omit_outbox"]},
        {"unexpected": True},
    ],
)
def test_request_limits_are_enforced_without_starting_a_campaign(lab_client, body):
    assert lab_client.post("/api/lab/campaigns", json=body).status_code == 422


def test_replay_endpoint_and_missing_artifacts(lab_client):
    result = lab_client.post(
        "/api/lab/replay",
        json={
            "mutation": "omit_outbox",
            "actions": ["submit"],
        },
    )
    assert result.status_code == 200
    assert result.json()["violations"][0]["invariant"] == "durable_intent"
    assert (
        lab_client.post(
            "/api/lab/replay",
            json={
                "mutation": "omit_outbox",
                "actions": ["unknown"],
            },
        ).status_code
        == 422
    )
    assert (
        lab_client.get("/api/lab/campaigns/00000000-0000-0000-0000-000000000000").status_code == 404
    )


def test_busy_campaign_returns_actionable_error(lab_client):
    assert routes.CAMPAIGN_SLOT.acquire(blocking=False)
    try:
        result = lab_client.post("/api/lab/campaigns", json={})
        assert result.status_code == 429
    finally:
        routes.CAMPAIGN_SLOT.release()


def test_missing_controller_returns_setup_instructions(lab_client, monkeypatch, tmp_path):
    monkeypatch.setenv("KEEL_LAB_BINARY", str(tmp_path / "missing-controller"))
    response = lab_client.post("/api/lab/campaigns", json={})
    assert response.status_code == 503
    assert "python -m payops.lab build" in response.json()["detail"]
    assert lab_client.get("/api/lab/campaigns").json() == []
    assert lab_client.get("/api/lab/catalog").json()["controller_ready"] is False


@pytest.mark.parametrize(
    ("mutation", "exit_code"),
    [
        ("omit_outbox", 0),
        ("unstable_provider_key", 1),
    ],
)
def test_cli_require_all_preserves_evidence_and_sets_ci_exit_status(
    lab_binary,
    tmp_path,
    mutation,
    exit_code,
):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "payops.lab",
            "run",
            "--seed",
            "42",
            "--budget",
            "1",
            "--mutation",
            mutation,
            "--require-all",
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=os.environ | {"KEEL_LAB_BINARY": str(lab_binary)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    reports = list(tmp_path.glob("*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["findings"][0]["status"] == ("killed" if exit_code == 0 else "survived")


def test_bridge_protocol_handles_invalid_and_multiple_requests():
    requests = [
        {"protocol": 9, "mutation": "baseline", "actions": []},
        {"protocol": 1, "mutation": "omit_outbox", "actions": ["submit"]},
        {"protocol": 1, "mutation": "baseline", "actions": ["submit"]},
    ]
    result = subprocess.run(
        [sys.executable, "-m", "payops.lab.bridge"],
        input="\n".join(json.dumps(r) for r in requests) + "\n",
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 3
    assert "error" in replies[0]
    assert replies[1]["result"]["violations"]
    assert replies[2]["result"]["violations"] == []
