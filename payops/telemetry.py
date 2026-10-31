import json
import logging
import sys
import time

from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter("payops_http_requests_total", "API responses", ["method", "route", "status"])
LATENCY = Histogram("payops_http_request_seconds", "API latency", ["route"])
COMPLETIONS = Counter("payops_worker_results_total", "Worker results", ["outcome"])
COMPLETION_TIME = Histogram("payops_payment_completion_seconds", "Creation to terminal result")
HEARTBEAT = Gauge("payops_heartbeat_timestamp", "Last successful loop", ["role"])
OUTBOX = Gauge("payops_outbox_pending", "Unpublished outbox rows")
PAYMENTS = Gauge("payops_payments", "Payments by durable state", ["status"])


def configure_logging():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log(event, **values):
    logging.getLogger("payops").info(json.dumps({"event": event, "time": time.time(), **values}))
