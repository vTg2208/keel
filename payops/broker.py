import json

import pika

EXCHANGE = "payops"
WORK_QUEUE = "payops.payments"
DEAD_QUEUE = "payops.dead"


def connect(url):
    parameters = pika.URLParameters(url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 5
    parameters.socket_timeout = 5
    parameters.stack_timeout = 10
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(queue=DEAD_QUEUE, durable=True, arguments={"x-queue-type": "quorum"})
    channel.queue_bind(queue=DEAD_QUEUE, exchange=EXCHANGE, routing_key="dead")
    channel.queue_declare(
        queue=WORK_QUEUE,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": "dead",
            "x-delivery-limit": 20,
            "x-overflow": "reject-publish",
            "x-dead-letter-strategy": "at-least-once",
        },
    )
    channel.queue_bind(queue=WORK_QUEUE, exchange=EXCHANGE, routing_key="work")
    channel.basic_qos(prefetch_count=1)
    channel.confirm_delivery()
    return connection, channel


def publish(channel, event_id, payload, route="work"):
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=route,
        body=json.dumps(payload).encode(),
        mandatory=True,
        properties=pika.BasicProperties(
            delivery_mode=2, content_type="application/json", message_id=event_id
        ),
    )
