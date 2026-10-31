"""Portable local operations. Run `python ops.py --help`. No shell interpolation."""

import argparse
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / ".local"


def run(args, *, data=None, capture=False, check=True, env=None):
    return subprocess.run(
        [str(a) for a in args],
        cwd=ROOT,
        input=data,
        text=True,
        capture_output=capture,
        check=check,
        env=env,
    )


def tool(name):
    suffix = ".exe" if os.name == "nt" else ""
    local = LOCAL / "bin" / (name + suffix)
    found = str(local) if local.exists() else shutil.which(name)
    if not found:
        raise RuntimeError(
            f"Missing {name}. Run python ops.py install-tools (kind) or install {name}."
        )
    return found


def compose(*args, **kwargs):
    return run([tool("docker"), "compose", *args], **kwargs)


def init():
    LOCAL.mkdir(exist_ok=True)
    target = ROOT / ".env"
    existing = target.read_text() if target.exists() else ""
    keys = {line.split("=", 1)[0] for line in existing.splitlines() if "=" in line}
    missing = [
        key
        for key in (
            "POSTGRES_PASSWORD",
            "RABBITMQ_PASSWORD",
            "GRAFANA_PASSWORD",
            "JENKINS_PASSWORD",
        )
        if key not in keys
    ]
    if missing:
        target.write_text(
            existing
            + ("\n" if existing and not existing.endswith("\n") else "")
            + "".join(f"{key}={secrets.token_hex(24)}\n" for key in missing)
        )
        if os.name != "nt":
            target.chmod(0o600)
        print("Generated .env. Existing credentials are preserved on subsequent runs.")


def credentials():
    init()
    return dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if line and not line.startswith("#")
    )


def install_tools():
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "amd64"
    directory = LOCAL / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    target = directory / f"kind{suffix}"
    url = f"https://kind.sigs.k8s.io/dl/v0.30.0/kind-{system}-{arch}"
    print(f"Downloading kind v0.30.0 into {directory}")
    urllib.request.urlretrieve(url, target)
    # Verify the release checksum before executing the downloaded binary.
    import hashlib

    with urllib.request.urlopen(url + ".sha256sum") as response:
        expected = response.read().decode().split()[0]
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        target.unlink()
        raise RuntimeError("kind checksum mismatch")
    target.chmod(0o755)


def doctor():
    print(f"Python {platform.python_version()}; platform {platform.system()}")
    run(
        [
            tool("docker"),
            "info",
            "--format",
            "Engine {{.ServerVersion}}; memory {{.MemTotal}} bytes",
        ]
    )
    run([tool("docker"), "compose", "version"])
    for name in ("kind", "kubectl"):
        try:
            print(f"{name}: {tool(name)}")
        except RuntimeError as exc:
            print(exc)


def bootstrap():
    init()
    run([tool("docker"), "info"], capture=True)
    kind = tool("kind")
    clusters = run([kind, "get", "clusters"], capture=True).stdout.splitlines()
    if "payops" not in clusters:
        run(
            [
                kind,
                "create",
                "cluster",
                "--name",
                "payops",
                "--config",
                "infra/kind.yaml",
                "--kubeconfig",
                LOCAL / "kubeconfig",
            ]
        )
    else:
        run(
            [kind, "export", "kubeconfig", "--name", "payops", "--kubeconfig", LOCAL / "kubeconfig"]
        )


def kubectl(*args, **kwargs):
    return run(
        [tool("kubectl"), "--kubeconfig", LOCAL / "kubeconfig", "--context", "kind-payops", *args],
        **kwargs,
    )


def smoke(base="http://127.0.0.1:8000"):
    import httpx

    results = []
    with httpx.Client(base_url=base, timeout=5) as client:
        for scenario, want, attempts in [
            ("success", "succeeded", 1),
            ("decline", "rejected", 1),
            ("flaky", "succeeded", 2),
            ("timeout", "failed", 3),
            ("timeout_after_success", "succeeded", 2),
        ]:
            key = f"smoke-{uuid4()}"
            body = {"amount_minor": 12500, "currency": "INR", "scenario": scenario}
            response = client.post("/payments", json=body, headers={"Idempotency-Key": key})
            response.raise_for_status()
            payment_id = response.json()["id"]
            replay = client.post("/payments", json=body, headers={"Idempotency-Key": key})
            assert replay.status_code == 200 and replay.json()["id"] == payment_id
            conflict = client.post(
                "/payments", json=body | {"amount_minor": 1}, headers={"Idempotency-Key": key}
            )
            assert conflict.status_code == 409
            deadline = time.monotonic() + 90
            while True:
                status = client.get(f"/payments/{payment_id}")
                status.raise_for_status()
                payment = status.json()
                if payment["status"] in {"succeeded", "rejected", "failed"}:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Payment {payment_id} stuck in {payment['status']}")
                time.sleep(0.3)
            assert payment["status"] == want, payment
            assert payment["attempts"] == attempts, payment
            events = client.get(f"/payments/{payment_id}/events").json()
            result = {
                "scenario": scenario,
                "id": payment_id,
                "status": payment["status"],
                "attempts": payment["attempts"],
                "events": len(events),
            }
            print(json.dumps(result))
            results.append(result)
    LOCAL.mkdir(exist_ok=True)
    (LOCAL / "smoke-results.json").write_text(json.dumps(results, indent=2))
    return results


def render(tag, monitoring=True, logging=True):
    from infra.manifests import manifests

    return json.dumps(
        {"apiVersion": "v1", "kind": "List", "items": manifests(ROOT, tag, monitoring, logging)}
    )


def release_history():
    result = kubectl(
        "get",
        "configmap",
        "payops-release",
        "-n",
        "payops",
        "-o",
        "json",
        "--ignore-not-found=true",
        capture=True,
    )
    return json.loads(result.stdout).get("data", {}) if result.stdout.strip() else {}


def save_release(current, previous, tags):
    state = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "payops-release", "namespace": "payops"},
        "data": {"current": current, "previous": previous or "", "tags": json.dumps(tags)},
    }
    kubectl("apply", "-f", "-", data=json.dumps(state), capture=True)
    (LOCAL / "current-release.json").write_text(current)
    if previous:
        (LOCAL / "previous-release.json").write_text(previous)


def load_images(images):
    docker, kind = tool("docker"), tool("kind")
    images = [
        image
        for image in images
        if image.startswith("payops:")
        or run(
            [docker, "exec", "payops-control-plane", "crictl", "inspecti", image],
            capture=True,
            check=False,
        ).returncode
        != 0
    ]
    if not images:
        return
    options = run([docker, "image", "save", "--help"], capture=True).stdout
    if "--platform" not in options:
        run([kind, "load", "docker-image", *images, "--name", "payops"])
        return
    node_platform = run(
        [docker, "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], capture=True
    ).stdout.strip()
    archive = LOCAL / f"kind-images-{uuid4()}.tar"
    try:
        run([docker, "image", "save", "--platform", node_platform, "-o", archive, *images])
        run([kind, "load", "image-archive", archive, "--name", "payops"])
    finally:
        archive.unlink(missing_ok=True)


def deploy(tag, *, monitoring=True, logging=True):
    creds = credentials()
    kubeconfig = LOCAL / "kubeconfig"
    if not kubeconfig.exists():
        raise RuntimeError("Run python ops.py bootstrap first")
    state = release_history()
    tags = json.loads(state.get("tags", "[]"))
    if tag in tags:
        raise RuntimeError(f"Tag {tag!r} was already validated. Build a new immutable release tag.")
    namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "payops"}}
    kubectl("apply", "-f", "-", data=json.dumps(namespace), capture=True)
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "payops", "namespace": "payops"},
        "stringData": creds
        | {
            "DATABASE_URL": f"postgresql+psycopg://payops:{creds['POSTGRES_PASSWORD']}@postgres:5432/payops",
            "RABBITMQ_URL": f"amqp://payops:{creds['RABBITMQ_PASSWORD']}@rabbitmq:5672/%2F",
        },
    }
    kubectl("apply", "-f", "-", data=json.dumps(secret), capture=True)
    previous = state.get("current") or None
    candidate = render(tag, monitoring, logging)
    # Reuse Compose images when present rather than downloading them again inside kind.
    support_images = set()
    for item in json.loads(candidate)["items"]:
        for container in (
            item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        ):
            image = container["image"]
            if (
                not image.startswith("payops:")
                and run(
                    [tool("docker"), "image", "inspect", image], capture=True, check=False
                ).returncode
                == 0
            ):
                support_images.add(image)
    load_images([f"payops:{tag}", *sorted(support_images)])
    try:
        kubectl("apply", "-f", "-", data=candidate)
        for service in ("postgres", "rabbitmq"):
            kubectl("rollout", "status", f"statefulset/{service}", "-n", "payops", "--timeout=180s")
        kubectl("delete", "job", "payops-migrate", "-n", "payops", "--ignore-not-found=true")
        from infra.manifests import migration_job

        kubectl("apply", "-f", "-", data=json.dumps(migration_job(tag)))
        kubectl(
            "wait",
            "--for=condition=complete",
            "job/payops-migrate",
            "-n",
            "payops",
            "--timeout=120s",
        )
        for service in ("api", "simulator", "publisher", "worker"):
            kubectl("rollout", "status", f"deployment/{service}", "-n", "payops", "--timeout=120s")
        with forward("api", 18000, 8000):
            smoke("http://127.0.0.1:18000")
        save_release(candidate, previous, tags + [tag])
    except Exception:
        if previous:
            print("Deployment validation failed; restoring previous release.")
            kubectl("apply", "-f", "-", data=previous)
            for service in ("api", "simulator", "publisher", "worker"):
                kubectl(
                    "rollout", "status", f"deployment/{service}", "-n", "payops", "--timeout=120s"
                )
            with forward("api", 18000, 8000):
                smoke("http://127.0.0.1:18000")
        else:
            print("Initial deployment failed; removing candidate application deployments.")
            kubectl(
                "delete",
                "deployment",
                "api",
                "worker",
                "publisher",
                "simulator",
                "-n",
                "payops",
                "--ignore-not-found=true",
            )
        raise
    print(f"Validated release payops:{tag}")


class forward:
    def __init__(self, service, local_port, remote_port):
        self.service, self.local_port, self.remote_port = service, local_port, remote_port

    def __enter__(self):
        import socket

        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.local_port))
            except OSError:
                raise RuntimeError(
                    f"Port {self.local_port} is occupied; choose a free port."
                ) from None
        self.process = subprocess.Popen(
            [
                tool("kubectl"),
                "--kubeconfig",
                str(LOCAL / "kubeconfig"),
                "--context",
                "kind-payops",
                "-n",
                "payops",
                "port-forward",
                f"service/{self.service}",
                f"{self.local_port}:{self.remote_port}",
                "--address=127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=ROOT,
        )
        for _ in range(50):
            if self.process.poll() is not None:
                raise RuntimeError("Port-forward exited. Check for an occupied local port.")
            try:
                with socket.create_connection(("127.0.0.1", self.local_port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.2)
        self.process.terminate()
        self.process.wait(timeout=10)
        raise RuntimeError("Port-forward did not become ready")

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=10)


def backup(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        subprocess.run(
            [
                tool("docker"),
                "compose",
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "payops",
                "-d",
                "payops",
                "-Fc",
            ],
            cwd=ROOT,
            stdout=stream,
            check=True,
        )
    print(f"Backup written to {path}")


def integration():
    creds = credentials()
    compose("-f", "compose.yaml", "-f", "compose.test.yaml", "up", "-d", "--wait", "postgres")
    try:
        exists = compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "payops",
            "-d",
            "payops",
            "-tAc",
            "SELECT 1 FROM pg_database WHERE datname='payops_test'",
            capture=True,
        )
        if not exists.stdout.strip():
            compose("exec", "-T", "postgres", "createdb", "-U", "payops", "payops_test")
        env = os.environ.copy()
        env["PAYOPS_TEST_DATABASE_URL"] = (
            f"postgresql+psycopg://payops:{creds['POSTGRES_PASSWORD']}@127.0.0.1:15432/payops_test"
        )
        run([sys.executable, "-m", "pytest", "tests/test_postgres.py", "-q"], env=env)
    finally:
        compose("up", "-d", "--wait", "postgres")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "doctor",
            "install-tools",
            "bootstrap",
            "build",
            "up",
            "down",
            "test",
            "lint",
            "smoke",
            "demo",
            "deploy",
            "render",
            "teardown",
            "backup",
            "restore",
            "logs",
            "status",
            "jenkins",
            "forward",
            "rollback",
            "integration",
        ],
    )
    parser.add_argument("--tag", default="dev")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--monitoring", action="store_true")
    parser.add_argument("--logging", action="store_true")
    parser.add_argument("--file", type=Path, default=LOCAL / "backups" / "payops.dump")
    parser.add_argument(
        "--confirm", action="store_true", help="Required for destructive restore/teardown"
    )
    parser.add_argument(
        "--service",
        default="api",
        choices=["api", "grafana", "prometheus", "alertmanager", "rabbitmq"],
    )
    args = parser.parse_args()
    command = args.command
    if command in {"init", "doctor", "install-tools", "bootstrap", "integration"}:
        globals()[command.replace("-", "_")]()
    elif command == "build":
        run([tool("docker"), "build", "-t", f"payops:{args.tag}", "."])
    elif command == "up":
        init()
        profiles = ["--profile", "monitoring"] if args.monitoring else []
        profiles += ["--profile", "logging"] if args.logging else []
        compose(*profiles, "up", "-d", "--build", "--wait", "--wait-timeout", "180")
    elif command == "down":
        compose("--profile", "monitoring", "--profile", "logging", "down")
    elif command in {"test", "lint"}:
        run(
            [sys.executable, "-m", "pytest", "-q"]
            if command == "test"
            else [sys.executable, "-m", "ruff", "check", "."]
        )
    elif command in {"smoke", "demo"}:
        smoke(args.base_url)
    elif command == "render":
        print(render(args.tag, args.monitoring, args.logging))
    elif command == "deploy":
        deploy(args.tag, monitoring=args.monitoring, logging=args.logging)
    elif command == "rollback":
        state = release_history()
        candidate = state.get("previous")
        if not candidate:
            raise RuntimeError("No previous release snapshot")
        kubectl("apply", "-f", "-", data=candidate)
        for service in ("api", "simulator", "publisher", "worker"):
            kubectl("rollout", "status", f"deployment/{service}", "-n", "payops", "--timeout=120s")
        with forward("api", 18000, 8000):
            smoke("http://127.0.0.1:18000")
        save_release(candidate, state["current"], json.loads(state.get("tags", "[]")))
    elif command == "teardown":
        if not args.confirm:
            raise RuntimeError(
                "Cluster deletion loses its local volumes. Pass --confirm to proceed."
            )
        run([tool("kind"), "delete", "cluster", "--name", "payops"])
    elif command == "backup":
        backup(args.file.resolve())
    elif command == "restore":
        if not args.confirm:
            raise RuntimeError("Restore replaces lab data. Pass --confirm after making a backup.")
        compose("stop", "api", "worker", "publisher", "simulator")
        try:
            with args.file.open("rb") as stream:
                subprocess.run(
                    [
                        tool("docker"),
                        "compose",
                        "exec",
                        "-T",
                        "postgres",
                        "pg_restore",
                        "-U",
                        "payops",
                        "-d",
                        "payops",
                        "--clean",
                        "--if-exists",
                        "--no-owner",
                        "--single-transaction",
                    ],
                    cwd=ROOT,
                    stdin=stream,
                    check=True,
                )
            compose("run", "--rm", "--no-deps", "migrate", "python", "-m", "payops.maintenance")
        finally:
            compose("start", "api", "worker", "publisher", "simulator")
    elif command == "logs":
        compose("logs", "--tail=100", "-f", "api", "publisher", "worker", "simulator")
    elif command == "status":
        compose("--profile", "monitoring", "--profile", "logging", "ps")
    elif command == "jenkins":
        init()
        compose("--env-file", ".env", "-f", "infra/jenkins/compose.yaml", "up", "-d", "--build")
    elif command == "forward":
        ports = {
            "api": (8000, 8000),
            "grafana": (3000, 3000),
            "prometheus": (9090, 9090),
            "alertmanager": (9093, 9093),
            "rabbitmq": (15672, 15672),
        }
        with forward(args.service, *ports[args.service]):
            print(
                f"Forwarding {args.service} on http://127.0.0.1:{ports[args.service][0]}; "
                "Ctrl+C to stop"
            )
            while True:
                time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
