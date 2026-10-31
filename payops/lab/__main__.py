"""Build, run, or serve the self-contained failure-discovery workbench."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from payops.lab.artifacts import markdown_report, regression_tests
from payops.lab.controller import ROOT, binary_path, run_campaign
from payops.lab.replay import MUTATIONS
from payops.lab.routes import CampaignRequest
from payops.models import identifier, utcnow


def main():
    parser = argparse.ArgumentParser(description="Keel payment-recovery failure discovery")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="Build the Go controller into .local/bin")
    run = commands.add_parser("run", help="Discover failures and export evidence")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--budget", type=int, default=8)
    run.add_argument("--mutation", choices=list(MUTATIONS), action="append")
    run.add_argument("--output", type=Path, default=ROOT / ".local/lab-artifacts")
    run.add_argument(
        "--require-all",
        action="store_true",
        help="Exit with failure if any selected known fault survives",
    )
    serve = commands.add_parser("serve", help="Serve the workbench with separate local history")
    serve.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    if args.command == "build":
        binary = binary_path()
        binary.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["go", "build", "-trimpath", "-o", str(binary), "./cmd/keel-lab"], cwd=ROOT, check=True
        )
        print(f"Built {binary}")
    elif args.command == "run":
        request = CampaignRequest(
            seed=args.seed, budget=args.budget, mutations=args.mutation or list(MUTATIONS)
        )
        report = run_campaign(request.model_dump())
        report.update(id=identifier(), created_at=utcnow().isoformat() + "Z")
        target = args.output / report["id"]
        target.mkdir(parents=True, exist_ok=False)
        (target / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (target / "report.md").write_text(markdown_report(report), encoding="utf-8")
        (target / "test_regression.py").write_text(regression_tests(report), encoding="utf-8")
        print(
            f"Detected {report['killed']}/{report['total']} faults; {report['evaluations']} replays"
        )
        print(f"Artifacts: {target}")
        if args.require_all and report["killed"] != report["total"]:
            sys.exit(1)
    else:
        import uvicorn

        from payops.api import create_app
        from payops.db import make_sessions
        from payops.models import Base

        local = ROOT / ".local"
        local.mkdir(exist_ok=True)
        sessions = make_sessions("sqlite:///" + (local / "lab-history.db").as_posix())
        Base.metadata.create_all(sessions.kw["bind"])
        app = create_app(sessions)
        print(f"Keel workbench: http://127.0.0.1:{args.port}/lab", flush=True)
        print("Standalone experiments only; live payment workers are not started.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
