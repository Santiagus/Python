#!/usr/bin/env python3
"""SRE Operational Tool: Dead Letter Queue (DLQ) Message Inspector.

Inspects unacknowledged dead-letter messages in Kombu AMQP queues without destructive
consumption, extracting error headers, retry counts, x-death metadata, and original payloads.

Usage:
    python3 scripts/inspect_dlq.py --queue fraud.screening.dlq --count 5
    python3 scripts/inspect_dlq.py --help
"""

import argparse
import json
import logging
import os
import sys
from typing import Any

from kombu import Connection, Queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inspect_dlq")


def inspect_messages(
    broker_url: str,
    queue_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Peek into a dead-letter queue and extract message metadata.

    Args:
        broker_url: AMQP connection URI.
        queue_name: Name of the AMQP DLQ to inspect.
        limit: Maximum number of messages to inspect.

    Returns:
        list[dict[str, Any]]: Inspected message envelopes with metadata and payloads.
    """
    inspected: list[dict[str, Any]] = []

    # 1. Establish connection to AMQP broker
    with Connection(broker_url) as conn:
        with conn.channel() as channel:
            # 2. Declare queue passively to verify existence without modifying attributes
            queue = Queue(queue_name, channel=channel)
            queue.declare(passive=True)

            # 3. Peek messages using basic_get (re-queue immediately to prevent data loss)
            messages_found = 0
            while messages_found < limit:
                msg = queue.get(no_ack=False)
                if msg is None:
                    break

                try:
                    payload = msg.decode()
                except Exception:
                    payload = str(msg.body)

                headers = msg.headers or {}
                properties = msg.properties or {}
                delivery_info = msg.delivery_info or {}

                inspected.append(
                    {
                        "message_id": properties.get("correlation_id")
                        or properties.get("message_id", "unknown"),
                        "routing_key": delivery_info.get("routing_key", ""),
                        "exchange": delivery_info.get("exchange", ""),
                        "headers": headers,
                        "x_death": headers.get("x-death", []),
                        "payload": payload,
                    }
                )

                # 4. Reject and requeue so messages remain intact for later replay
                msg.requeue()
                messages_found += 1

    return inspected


def main() -> int:
    """CLI entry point for DLQ inspector."""
    parser = argparse.ArgumentParser(
        description="Inspect dead-letter queue messages without data loss."
    )
    parser.add_argument(
        "--broker",
        default=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
        help="AMQP broker connection URL",
    )
    parser.add_argument(
        "--queue",
        default="fraud.screening.dlq",
        help="Name of the DLQ to inspect",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Maximum number of messages to inspect",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as structured JSON",
    )

    args = parser.parse_args()

    try:
        results = inspect_messages(args.broker, args.queue, limit=args.count)
    except Exception as exc:
        logger.error(f"Failed to inspect DLQ '{args.queue}': {exc}")
        return 1

    if args.json:
        print(json.dumps(results, indent=2, default=str))
        return 0

    print("\n======================================================================")
    print(f"📦 DLQ INSPECTION: {args.queue} ({len(results)} message(s) inspected)")
    print("======================================================================\n")

    if not results:
        print("Queue is empty. Zero dead-letter messages present.")
        return 0

    for idx, item in enumerate(results, start=1):
        print(f"--- Message #{idx} [ID: {item['message_id']}] ---")
        print(f"  Exchange    : {item['exchange']}")
        print(f"  Routing Key : {item['routing_key']}")
        print(f"  x-death     : {item['x_death']}")
        print(f"  Headers     : {item['headers']}")
        print(f"  Payload     : {item['payload']}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
