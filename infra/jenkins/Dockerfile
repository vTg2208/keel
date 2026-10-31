FROM jenkins/jenkins:2.580.2-lts-jdk21
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl ca-certificates docker.io && rm -rf /var/lib/apt/lists/*
ARG TARGETARCH
RUN arch=${TARGETARCH:-amd64}; curl --retry 5 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-$arch -o /usr/local/bin/kind && chmod +x /usr/local/bin/kind && curl --retry 5 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL https://dl.k8s.io/release/v1.34.1/bin/linux/$arch/kubectl -o /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl
COPY plugins.lock.json download_plugins.py /opt/payops-plugins/
RUN --mount=type=cache,id=payops-jenkins-archives,target=/tmp/payops-plugin-archives \
    python3 /opt/payops-plugins/download_plugins.py /opt/payops-plugins/plugins.lock.json
COPY --from=docker:28.5.2-cli /usr/local/bin/docker /usr/local/bin/docker
USER jenkins
