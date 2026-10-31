"""Render native Kubernetes resources without a template engine or Helm dependency."""

import json


def resource(kind, name, **spec):
    api = "apps/v1" if kind in {"Deployment", "StatefulSet"} else "v1"
    return {
        "apiVersion": api,
        "kind": kind,
        "metadata": {"name": name, "namespace": "payops"},
        **spec,
    }


def service(name, ports):
    return resource(
        "Service",
        name,
        spec={
            "selector": {"app": name},
            "ports": [{"name": f"port-{port}", "port": port, "targetPort": port} for port in ports],
        },
    )


def configmap(name, data):
    return resource("ConfigMap", name, data=data)


def secret_env(name, key):
    return {"name": name, "valueFrom": {"secretKeyRef": {"name": "payops", "key": key}}}


def workload(
    name,
    image,
    ports,
    *,
    command=None,
    env=None,
    mounts=None,
    volumes=None,
    persistent=None,
    probe=None,
    liveness_probe=None,
    memory="256Mi",
    cpu="500m",
    user=10001,
    service_account=None,
):
    container = {
        "name": name,
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "ports": [{"containerPort": p, "name": f"port-{p}"} for p in ports],
        "resources": {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": cpu, "memory": memory},
        },
        "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
    }
    if command:
        container["command"] = command
    if env:
        container["env"] = env
    if mounts:
        container["volumeMounts"] = mounts
    if probe:
        container["readinessProbe"] = probe | {"periodSeconds": 5, "failureThreshold": 6}
        container["livenessProbe"] = (liveness_probe or probe) | {
            "periodSeconds": 10,
            "failureThreshold": 6,
        }
        container["startupProbe"] = probe | {"periodSeconds": 5, "failureThreshold": 60}
    pod = {
        "containers": [container],
        "terminationGracePeriodSeconds": 30,
        "automountServiceAccountToken": bool(service_account),
        "securityContext": {
            "runAsUser": user,
            "runAsGroup": user,
            "fsGroup": user,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }
    if service_account:
        pod["serviceAccountName"] = service_account
    if volumes:
        pod["volumes"] = volumes
    spec = {
        "replicas": 1,
        "selector": {"matchLabels": {"app": name}},
        "template": {"metadata": {"labels": {"app": name}}, "spec": pod},
    }
    if persistent:
        spec["serviceName"] = name
        spec["volumeClaimTemplates"] = [
            {
                "metadata": {"name": "data"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": persistent}},
                },
            }
        ]
    else:
        spec["strategy"] = {"type": "Recreate"} if mounts else {"type": "RollingUpdate"}
    return resource("StatefulSet" if persistent else "Deployment", name, spec=spec)


def app_env():
    return [
        secret_env("DATABASE_URL", "DATABASE_URL"),
        secret_env("RABBITMQ_URL", "RABBITMQ_URL"),
        {"name": "PROVIDER_URL", "value": "http://simulator:8001"},
    ]


def migration_job(tag):
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "payops-migrate", "namespace": "payops"},
        "spec": {
            "backoffLimit": 3,
            "activeDeadlineSeconds": 120,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "migrate",
                            "image": f"payops:{tag}",
                            "imagePullPolicy": "Never",
                            "env": app_env(),
                            "command": ["python", "-m", "payops.db"],
                        }
                    ],
                }
            },
        },
    }


def cm_volume(name, config):
    return {"name": name, "configMap": {"name": config}}


def mount(name, path, subpath=None):
    value = {"name": name, "mountPath": path}
    if subpath:
        value["subPath"] = subpath
    return value


def manifests(root, tag, monitoring=True, logging=True):
    items = []
    # Database and broker own persistent volumes. Stable pod/host names preserve broker identity.
    items += [
        service("postgres", [5432]),
        workload(
            "postgres",
            "postgres:17.6-bookworm",
            [5432],
            user=999,
            persistent="2Gi",
            memory="384Mi",
            env=[
                {"name": "POSTGRES_USER", "value": "payops"},
                {"name": "POSTGRES_DB", "value": "payops"},
                {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
                secret_env("POSTGRES_PASSWORD", "POSTGRES_PASSWORD"),
            ],
            mounts=[mount("data", "/var/lib/postgresql/data")],
            probe={"exec": {"command": ["pg_isready", "-U", "payops", "-d", "payops"]}},
        ),
    ]
    items += [
        configmap(
            "rabbitmq-config",
            {"enabled_plugins": (root / "infra/rabbitmq/enabled_plugins").read_text()},
        ),
        service("rabbitmq", [5672, 15672, 15692]),
        workload(
            "rabbitmq",
            "rabbitmq:4.1.4-management",
            [5672, 15672, 15692],
            user=999,
            persistent="1Gi",
            memory="512Mi",
            env=[
                {"name": "RABBITMQ_DEFAULT_USER", "value": "payops"},
                secret_env("RABBITMQ_DEFAULT_PASS", "RABBITMQ_PASSWORD"),
                {"name": "RABBITMQ_NODENAME", "value": "rabbit@rabbitmq-0"},
                {
                    "name": "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS",
                    "value": "-rabbitmq_prometheus return_per_object_metrics true",
                },
            ],
            mounts=[
                mount("data", "/var/lib/rabbitmq"),
                mount("config", "/etc/rabbitmq/enabled_plugins", "enabled_plugins"),
            ],
            volumes=[cm_volume("config", "rabbitmq-config")],
            probe={"tcpSocket": {"port": 5672}, "timeoutSeconds": 3},
        ),
    ]
    for name, port, command in [
        ("api", 8000, ["uvicorn", "payops.api:app", "--host", "0.0.0.0", "--port", "8000"]),
        (
            "simulator",
            8001,
            ["uvicorn", "payops.simulator:app", "--host", "0.0.0.0", "--port", "8001"],
        ),
        ("publisher", 8002, ["python", "-m", "payops.publisher"]),
        ("worker", 8002, ["python", "-m", "payops.worker"]),
    ]:
        probe = (
            {"httpGet": {"path": "/readyz", "port": port}}
            if name in {"api", "simulator"}
            else {"httpGet": {"path": "/", "port": port}}
        )
        items += [
            service(name, [port]),
            workload(
                name,
                f"payops:{tag}",
                [port],
                command=command,
                env=app_env(),
                probe=probe,
                liveness_probe=(
                    {"httpGet": {"path": "/healthz", "port": port}}
                    if name in {"api", "simulator"}
                    else None
                ),
            ),
        ]
        items[-1]["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] = "Never"
    if monitoring:
        directory = root / "infra/monitoring"
        prometheus_config = (directory / "prometheus.yml").read_text()
        # cAdvisor through authenticated kubelet proxy supplies container CPU/memory metrics.
        prometheus_config += """
  - job_name: kubelet-cadvisor
    scheme: https
    tls_config:
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
    metrics_path: /api/v1/nodes/payops-control-plane/proxy/metrics/cadvisor
    static_configs:
      - targets: ['kubernetes.default.svc:443']
"""
        items += [
            configmap(
                "prometheus-config",
                {
                    "prometheus.yml": prometheus_config,
                    "alerts.yml": (directory / "alerts.yml").read_text(),
                },
            ),
            resource("ServiceAccount", "prometheus"),
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRole",
                "metadata": {"name": "payops-prometheus"},
                "rules": [{"apiGroups": [""], "resources": ["nodes/proxy"], "verbs": ["get"]}],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {"name": "payops-prometheus"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": "payops-prometheus",
                },
                "subjects": [
                    {"kind": "ServiceAccount", "name": "prometheus", "namespace": "payops"}
                ],
            },
        ]
        items += [
            service("prometheus", [9090]),
            workload(
                "prometheus",
                "prom/prometheus:v3.6.0",
                [9090],
                user=65534,
                memory="384Mi",
                persistent="1Gi",
                command=[
                    "/bin/prometheus",
                    "--config.file=/etc/prometheus/prometheus.yml",
                    "--storage.tsdb.path=/prometheus",
                    "--storage.tsdb.retention.time=3d",
                    "--storage.tsdb.retention.size=512MB",
                ],
                mounts=[mount("config", "/etc/prometheus"), mount("data", "/prometheus")],
                volumes=[cm_volume("config", "prometheus-config")],
                service_account="prometheus",
                probe={"httpGet": {"path": "/-/ready", "port": 9090}},
            ),
        ]
        items += [
            configmap(
                "alertmanager-config",
                {"alertmanager.yml": (directory / "alertmanager.yml").read_text()},
            ),
            service("alertmanager", [9093]),
            workload(
                "alertmanager",
                "prom/alertmanager:v0.28.1",
                [9093],
                user=65534,
                memory="128Mi",
                persistent="256Mi",
                command=[
                    "/bin/alertmanager",
                    "--config.file=/etc/alertmanager/alertmanager.yml",
                    "--storage.path=/alertmanager",
                ],
                mounts=[mount("config", "/etc/alertmanager"), mount("data", "/alertmanager")],
                volumes=[cm_volume("config", "alertmanager-config")],
                probe={"httpGet": {"path": "/-/ready", "port": 9093}},
            ),
        ]
        items += [
            configmap(
                "grafana-config",
                {
                    "datasources.yml": (
                        directory / "grafana/provisioning/datasources/default.yml"
                    ).read_text(),
                    "dashboards.yml": (
                        directory / "grafana/provisioning/dashboards/default.yml"
                    ).read_text(),
                    "payops.json": (directory / "grafana/dashboards/payops.json").read_text(),
                },
            ),
            service("grafana", [3000]),
            workload(
                "grafana",
                "grafana/grafana:12.2.0",
                [3000],
                user=472,
                persistent="512Mi",
                env=[
                    secret_env("GF_SECURITY_ADMIN_PASSWORD", "GRAFANA_PASSWORD"),
                    {"name": "GF_USERS_ALLOW_SIGN_UP", "value": "false"},
                ],
                mounts=[
                    mount("data", "/var/lib/grafana"),
                    mount(
                        "config",
                        "/etc/grafana/provisioning/datasources/default.yml",
                        "datasources.yml",
                    ),
                    mount(
                        "config",
                        "/etc/grafana/provisioning/dashboards/default.yml",
                        "dashboards.yml",
                    ),
                    mount("config", "/var/lib/grafana/dashboards/payops.json", "payops.json"),
                ],
                volumes=[cm_volume("config", "grafana-config")],
                probe={"httpGet": {"path": "/api/health", "port": 3000}},
            ),
        ]
    if logging:
        directory = root / "infra/monitoring"
        items += [
            configmap("loki-config", {"config.yaml": (directory / "loki.yaml").read_text()}),
            service("loki", [3100]),
            workload(
                "loki",
                "grafana/loki:3.5.5",
                [3100],
                user=10001,
                memory="384Mi",
                persistent="1Gi",
                command=["/usr/bin/loki", "-config.file=/etc/loki/config.yaml"],
                mounts=[mount("data", "/loki"), mount("config", "/etc/loki")],
                volumes=[cm_volume("config", "loki-config")],
                probe={"httpGet": {"path": "/ready", "port": 3100}},
            ),
            configmap(
                "alloy-config", {"config.alloy": (directory / "kubernetes.alloy").read_text()}
            ),
            resource("ServiceAccount", "alloy"),
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": "alloy", "namespace": "payops"},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods", "pods/log"],
                        "verbs": ["get", "list", "watch"],
                    }
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": "alloy", "namespace": "payops"},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "alloy",
                },
                "subjects": [{"kind": "ServiceAccount", "name": "alloy", "namespace": "payops"}],
            },
            workload(
                "alloy",
                "grafana/alloy:v1.11.0",
                [12345],
                user=10001,
                memory="192Mi",
                command=[
                    "/bin/alloy",
                    "run",
                    "--storage.path=/tmp/alloy",
                    "/etc/alloy/config.alloy",
                ],
                mounts=[mount("config", "/etc/alloy")],
                volumes=[cm_volume("config", "alloy-config")],
                service_account="alloy",
            ),
        ]
    return items


if __name__ == "__main__":
    from pathlib import Path

    print(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "List",
                "items": manifests(Path(__file__).resolve().parents[1], "dev"),
            },
            indent=2,
        )
    )
