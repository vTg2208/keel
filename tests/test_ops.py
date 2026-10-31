import json
import sys
from contextlib import nullcontext
from subprocess import CompletedProcess

import pytest

import ops


def test_hyphenated_install_tools_command_dispatches(monkeypatch, tmp_path):
    result = tmp_path / "installed"
    monkeypatch.setattr(ops, "install_tools", lambda: result.write_text("installed"))
    monkeypatch.setattr(sys, "argv", ["ops.py", "install-tools"])
    ops.main()
    assert result.read_text() == "installed"


def test_forward_refuses_occupied_port_before_starting_kubectl():
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="occupied"):
            ops.forward("api", listener.getsockname()[1], 8000).__enter__()


def test_image_loader_exports_node_platform_and_cleans_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "LOCAL", tmp_path)
    monkeypatch.setattr(ops, "tool", lambda name: name)
    imported = []

    def execute(args, **kwargs):
        if args[1:5] == ["exec", "payops-control-plane", "crictl", "inspecti"]:
            return CompletedProcess(args, 0, "already cached, possibly an earlier failed build", "")
        if args[1:] == ["image", "save", "--help"]:
            return CompletedProcess(args, 0, "--platform", "")
        if args[1] == "version":
            return CompletedProcess(args, 0, "linux/amd64\n", "")
        if args[1:3] == ["image", "save"]:
            assert args[args.index("--platform") + 1] == "linux/amd64"
            from pathlib import Path

            Path(args[args.index("-o") + 1]).write_bytes(b"selected-platform-archive")
        if args[1:3] == ["load", "image-archive"]:
            from pathlib import Path

            imported.append(Path(args[3]).read_bytes())
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(ops, "run", execute)
    ops.load_images(["payops:test"])
    assert imported == [b"selected-platform-archive"]
    assert list(tmp_path.glob("*.tar")) == []


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "LOCAL", tmp_path)
    (tmp_path / "kubeconfig").touch()
    monkeypatch.setattr(
        ops, "credentials", lambda: {"POSTGRES_PASSWORD": "test", "RABBITMQ_PASSWORD": "test"}
    )
    monkeypatch.setattr(ops, "tool", lambda name: name)
    monkeypatch.setattr(ops, "forward", lambda *_: nullcontext())
    monkeypatch.setattr(ops, "smoke", lambda *_: [])
    monkeypatch.setattr(ops, "run", lambda *args, **kwargs: CompletedProcess([], 0, "", ""))
    return tmp_path


def test_failed_release_restores_cluster_history_in_fresh_workspace(monkeypatch, deployment):
    previous = '{"kind":"List","items":[]}'
    applied = []

    def kube(*args, **kwargs):
        if args[0] == "get":
            return CompletedProcess(
                args, 0, json.dumps({"data": {"current": previous, "tags": '["good"]'}}), ""
            )
        if args[:2] == ("apply", "-f"):
            applied.append(kwargs["data"])
        if args[:3] == ("rollout", "status", "statefulset/postgres"):
            raise RuntimeError("candidate failed")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(ops, "kubectl", kube)
    with pytest.raises(RuntimeError, match="candidate failed"):
        ops.deploy("broken", monitoring=False, logging=False)
    assert applied[-1] == previous


def test_reused_release_tag_is_rejected_before_mutation(monkeypatch, deployment):
    mutations = []

    def kube(*args, **kwargs):
        if args[0] == "get":
            return CompletedProcess(
                args, 0, json.dumps({"data": {"current": "{}", "tags": '["dev"]'}}), ""
            )
        mutations.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(ops, "kubectl", kube)
    with pytest.raises(RuntimeError, match="already validated"):
        ops.deploy("dev", monitoring=False, logging=False)
    assert mutations == []


def test_initial_failed_release_removes_candidate_applications(monkeypatch, deployment):
    deleted = []

    def kube(*args, **kwargs):
        if args[0] == "get":
            return CompletedProcess(args, 0, "", "")
        if args[:3] == ("rollout", "status", "statefulset/postgres"):
            raise RuntimeError("initial failure")
        if args[:2] == ("delete", "deployment"):
            deleted.extend(args[2:6])
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(ops, "kubectl", kube)
    with pytest.raises(RuntimeError, match="initial failure"):
        ops.deploy("bad-first", monitoring=False, logging=False)
    assert set(deleted) == {"api", "worker", "publisher", "simulator"}
