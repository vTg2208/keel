FROM golang:1.25.6-bookworm AS lab-build
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -o /keel-lab ./cmd/keel-lab

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    KEEL_LAB_BINARY=/usr/local/bin/keel-lab
WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock && useradd --uid 10001 --create-home app
COPY pyproject.toml .
COPY payops ./payops
COPY --from=lab-build /keel-lab /usr/local/bin/keel-lab
RUN mkdir -p /app/.local && chown app:app /app/.local
USER app
EXPOSE 8000 8001 8002
CMD ["uvicorn", "payops.api:app", "--host", "0.0.0.0", "--port", "8000"]
