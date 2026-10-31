"""Broker-level probes, run inside the API container with its local credentials."""

import argparse
from uuid import uuid4

from payops.broker import DEAD_QUEUE, EXCHANGE, WORK_QUEUE, connect, publish
from payops.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["duplicate", "poison", "queues"])
    parser.add_argument("--payment-id")
    args = parser.parse_args()
    connection, channel = connect(settings().rabbitmq_url)
    try:
        if args.command == "duplicate":
            if not args.payment_id:
                parser.error("--payment-id required")
            for _ in range(5):
                publish(channel, str(uuid4()), {"payment_id": args.payment_id})
            print("Published five duplicate work messages")
        elif args.command == "poison":
            import pika

            channel.basic_publish(
                exchange=EXCHANGE,
                routing_key="work",
                body=b"not-json",
                mandatory=True,
                properties=pika.BasicProperties(delivery_mode=2),
            )
            print("Published malformed work for dead-letter validation")
        else:
            for queue in (WORK_QUEUE, DEAD_QUEUE):
                result = channel.queue_declare(queue=queue, passive=True)
                print(f"{queue}: ready={result.method.message_count}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
