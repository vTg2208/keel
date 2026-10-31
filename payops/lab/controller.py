"""Invoke the Go controller without shell interpolation or live service credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ControllerUnavailable(RuntimeError):
    pass


def binary_path():
    suffix = ".exe" if os.name == "nt" else ""
    return Path(os.environ.get("KEEL_LAB_BINARY", ROOT / ".local/bin" / f"keel-lab{suffix}"))


def run_campaign(request):
    binary = binary_path()
    if not binary.is_file():
        raise ControllerUnavailable("Build the Go controller with: python -m payops.lab build")
    env = os.environ.copy()
    # The replay worker never needs the application's connection strings.
    for name in ("DATABASE_URL", "RABBITMQ_URL", "PROVIDER_URL"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [str(binary.resolve()), "--python", sys.executable],
            input=json.dumps({"protocol": 1, **request}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            env=env,
            timeout=85,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ControllerUnavailable("Campaign exceeded its deadline; try a smaller budget") from exc
    except OSError as exc:
        raise ControllerUnavailable(
            "Cannot start the Go controller; rebuild it for this platform"
        ) from exc
    if result.returncode:
        raise ControllerUnavailable("Campaign failed; replay worker error: " + result.stderr[-600:])
    if len(result.stdout) > 2_000_000:
        raise ControllerUnavailable("Campaign report exceeded its size limit")
    try:
        report = json.loads(result.stdout)
        if report["protocol"] != 1 or not isinstance(report["findings"], list):
            raise ValueError("Invalid report")
    except (ValueError, KeyError, TypeError) as exc:
        raise ControllerUnavailable("Controller returned an invalid report") from exc
    return report
