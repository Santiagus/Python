#!/usr/bin/env python3
"""SRE Operational Tool: Dead Letter Queue (DLQ) Message Replayer.

Consumes quarantined poison-pill or transient-failure messages from a DLQ and
re-publishes them to a target AMQP exchange for re-processing, maintaining audit headers.

Usage:
    python3 scripts/replay_dlq.py --dlq fraud.screening.dlq --target-exchange fraud.direct
    python3 scripts/replay_dlq.py --dlq fraud.screening.dlq --limit 10 --dry-run
"""

import argparse
import logging
import os
import sys

from kombu import Connection, Exchange, Producer, Queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("replay_dlq")


def replay_messages(
    broker_url: str,
    dlq_name: str,
    target_exchange_name: str,
    default_routing_key: str = "fraud.screening.critical",
    limit: int = 100,
    dry_run: bool = False,
) -> int:
    """Consume messages from DLQ and republish to the target exchange.

    Args:
        broker_url: AMQP connection URI.
        dlq_name: Source dead-letter queue name.
        target_exchange_name: Destination AMQP exchange name.
        default_routing_key: Fallback routing key if not present in x-death.
        limit: Maximum number of messages to replay.
        dry_run: If True, inspects and logs without republishing or acknowledging.

    Returns:
        int: Number of messages replayed.
    """
    replayed_count = 0

    with Connection(broker_url) as conn:
        with conn.channel() as channel:
            dlq = Queue(dlq_name, channel=channel)
            target_exchange = Exchange(target_exchange_name, type="direct", channel=channel)
            producer = Producer(channel)

            while replayed_count < limit:
                msg = dlq.get(no_ack=False)
                if msg is None:
                    break

                try:
                    payload = msg.decode()
                except Exception:
                    payload = msg.body

                headers = dict(msg.headers or {})
                delivery_info = msg.delivery_info or {}

                # Determine destination routing key (from x-death or fallback)
                routing_key = default_routing_key
                if "x-death" in headers and headers["x-death"]:
                    routing_key = headers["x-death"][0].get("routing-keys", [default_routing_key])[
                        0
                    ]
                elif delivery_info.get("routing_key"):
                    routing_key = delivery_info["routing_key"]

                # Add replay tracking header
                headers["x-replayed-by"] = "sre-replay-dlq"
                headers["x-replayed-from"] = dlq_name

                if dry_run:
                    logger.info(
                        f"[DRY-RUN] Would replay message {msg.properties.get('message_id')} "
                        f"to exchange '{target_exchange_name}' with routing key '{routing_key}'"
                    )
                    msg.requeue()
                else:
                    # 1. Publish to target exchange
                    producer.publish(
                        payload,
                        exchange=target_exchange,
                        routing_key=routing_key,
                        headers=headers,
                        properties=msg.properties,
                        content_type=msg.content_type,
                        content_encoding=msg.content_encoding,
                    )
                    # 2. Acknowledge and remove from DLQ
                    msg.ack()
                    logger.info(
                        f"Replayed message {msg.properties.get('message_id')} "
                        f"-> {target_exchange_name} [{routing_key}]"
                    )

                replayed_count += 1

    return replayed_count


def main() -> int:
    """CLI entry point for DLQ replayer."""
    parser = argparse.ArgumentParser(
        description="Replay dead-letter queue messages back into primary processing exchanges."
    )
    parser.add_argument(
        "--broker",
        default=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
        help="AMQP broker connection URL",
    )
    parser.add_argument(
        "--dlq",
        default="fraud.screening.dlq",
        help="Source dead-letter queue name",
    )
    parser.add_argument(
        "--target-exchange",
        default="fraud.direct",
        help="Target AMQP exchange to publish replayed messages to",
    )
    parser.add_argument(
        "--routing-key",
        default="fraud.screening.critical",
        help="Default routing key to apply during replay",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of messages to replay",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate replay without moving messages or acknowledging",
    )

    args = parser.parse_args()

    try:
        count = replay_messages(
            broker_url=args.broker,
            dlq_name=args.dlq,
            target_exchange_name=args.target_exchange,
            default_routing_key=args.routing_key,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        mode_str = "[DRY-RUN] Inspected" if args.dry_run else "Successfully replayed"
        print(f"\n✅ {mode_str} {count} message(s) from '{args.dlq}' to '{args.target_exchange}'.")
        return 0
    except Exception as exc:
        logger.error(f"DLQ replay operation failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
