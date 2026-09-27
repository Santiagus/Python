"""Unit tests for SRE DLQ tools: inspect_dlq.py and replay_dlq.py (TC-22)."""

import json
from unittest.mock import MagicMock, patch

from scripts.inspect_dlq import inspect_messages
from scripts.inspect_dlq import main as inspect_main
from scripts.replay_dlq import main as replay_main
from scripts.replay_dlq import replay_messages


def test_inspect_messages_with_data() -> None:
    """Verify inspect_messages peeks messages, parses headers/payload, and requeues."""
    with patch("scripts.inspect_dlq.Connection") as mock_conn_cls:
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.channel.return_value.__enter__.return_value = mock_channel
        mock_conn_cls.return_value = mock_conn

        with patch("scripts.inspect_dlq.Queue") as mock_queue_cls:
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue

            # 1st message: decoded cleanly
            msg1 = MagicMock()
            msg1.decode.return_value = {"task": "scoring", "amount": 100}
            msg1.headers = {"x-death": [{"queue": "fraud.screening.critical", "count": 1}]}
            msg1.properties = {"message_id": "msg-1234"}
            msg1.delivery_info = {"routing_key": "fraud.screening.dlq", "exchange": "fraud.dlx"}

            # 2nd message: decode error fallback
            msg2 = MagicMock()
            msg2.decode.side_effect = ValueError("Corrupt JSON")
            msg2.body = b"raw binary payload"
            msg2.headers = None
            msg2.properties = {}
            msg2.delivery_info = None

            mock_queue.get.side_effect = [msg1, msg2, None]

            results = inspect_messages(
                broker_url="amqp://test",
                queue_name="fraud.screening.dlq",
                limit=5,
            )

            assert len(results) == 2
            assert results[0]["message_id"] == "msg-1234"
            assert results[0]["x_death"][0]["queue"] == "fraud.screening.critical"
            assert results[1]["payload"] == "b'raw binary payload'"
            assert results[1]["message_id"] == "unknown"

            # Verify messages were non-destructively requeued
            msg1.requeue.assert_called_once()
            msg2.requeue.assert_called_once()


def test_inspect_messages_empty_queue() -> None:
    """Verify inspect_messages returns empty list when queue has no messages."""
    with patch("scripts.inspect_dlq.Connection") as mock_conn_cls:
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_channel = MagicMock()
        mock_conn.channel.return_value.__enter__.return_value = mock_channel
        mock_conn_cls.return_value = mock_conn

        with patch("scripts.inspect_dlq.Queue") as mock_queue_cls:
            mock_queue = MagicMock()
            mock_queue.get.return_value = None
            mock_queue_cls.return_value = mock_queue

            results = inspect_messages("amqp://test", "fraud.screening.dlq")
            assert results == []


def test_inspect_main_cli_output(capsys) -> None:
    """Verify CLI main() in inspect_dlq formats output and handles --json flag."""
    sample = [
        {
            "message_id": "tx-1",
            "routing_key": "dlq",
            "exchange": "fraud.dlx",
            "headers": {},
            "x_death": [],
            "payload": {"status": "poison"},
        }
    ]

    with patch("scripts.inspect_dlq.inspect_messages", return_value=sample):
        with patch("sys.argv", ["inspect_dlq.py", "--queue", "test.dlq", "--count", "1"]):
            ret = inspect_main()
            assert ret == 0
            captured = capsys.readouterr()
            assert "DLQ INSPECTION: test.dlq" in captured.out
            assert "tx-1" in captured.out

        # JSON mode
        with patch("sys.argv", ["inspect_dlq.py", "--json"]):
            ret = inspect_main()
            assert ret == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert len(data) == 1
            assert data[0]["message_id"] == "tx-1"

    # Empty queue output
    with patch("scripts.inspect_dlq.inspect_messages", return_value=[]):
        with patch("sys.argv", ["inspect_dlq.py"]):
            ret = inspect_main()
            assert ret == 0
            captured = capsys.readouterr()
            assert "Queue is empty." in captured.out

    # Error handling branch
    with patch("scripts.inspect_dlq.inspect_messages", side_effect=RuntimeError("Broker down")):
        with patch("sys.argv", ["inspect_dlq.py"]):
            ret = inspect_main()
            assert ret == 1


def test_replay_messages_success() -> None:
    """Verify replay_messages republishes to target exchange and acknowledges from DLQ."""
    with patch("scripts.replay_dlq.Connection") as mock_conn_cls:
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_channel = MagicMock()
        mock_conn.channel.return_value.__enter__.return_value = mock_channel
        mock_conn_cls.return_value = mock_conn

        with (
            patch("scripts.replay_dlq.Queue") as mock_queue_cls,
            patch("scripts.replay_dlq.Producer") as mock_producer_cls,
        ):
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue
            mock_producer = MagicMock()
            mock_producer_cls.return_value = mock_producer

            msg = MagicMock()
            msg.decode.return_value = {"retry_item": 1}
            msg.headers = {"x-death": [{"routing-keys": ["fraud.screening.critical"]}]}
            msg.delivery_info = {"routing_key": "fraud.screening.dlq"}
            msg.properties = {"message_id": "msg-replayed-1"}
            msg.content_type = "application/json"
            msg.content_encoding = "utf-8"

            mock_queue.get.side_effect = [msg, None]

            count = replay_messages(
                broker_url="amqp://test",
                dlq_name="fraud.screening.dlq",
                target_exchange_name="fraud.direct",
                limit=10,
                dry_run=False,
            )

            assert count == 1
            mock_producer.publish.assert_called_once()
            call_kwargs = mock_producer.publish.call_args.kwargs
            assert call_kwargs["routing_key"] == "fraud.screening.critical"
            assert call_kwargs["headers"]["x-replayed-by"] == "sre-replay-dlq"
            msg.ack.assert_called_once()


def test_replay_messages_dry_run_and_decode_error() -> None:
    """Verify dry_run mode requeues without publishing, and decode error fallback works."""
    with patch("scripts.replay_dlq.Connection") as mock_conn_cls:
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_channel = MagicMock()
        mock_conn.channel.return_value.__enter__.return_value = mock_channel
        mock_conn_cls.return_value = mock_conn

        with (
            patch("scripts.replay_dlq.Queue") as mock_queue_cls,
            patch("scripts.replay_dlq.Producer") as mock_producer_cls,
        ):
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue
            mock_producer = MagicMock()
            mock_producer_cls.return_value = mock_producer

            msg = MagicMock()
            msg.decode.side_effect = ValueError("Decoding error")
            msg.body = b"binary"
            msg.headers = {}
            msg.delivery_info = {"routing_key": "fallback.rk"}
            msg.properties = {"message_id": "msg-dry-run"}

            mock_queue.get.side_effect = [msg, None]

            count = replay_messages(
                broker_url="amqp://test",
                dlq_name="fraud.screening.dlq",
                target_exchange_name="fraud.direct",
                limit=10,
                dry_run=True,
            )

            assert count == 1
            mock_producer.publish.assert_not_called()
            msg.ack.assert_not_called()
            msg.requeue.assert_called_once()


def test_replay_main_cli(capsys) -> None:
    """Verify replay_dlq CLI main() flags, formatting, and error handling."""
    with patch("scripts.replay_dlq.replay_messages", return_value=3):
        with patch("sys.argv", ["replay_dlq.py", "--dlq", "test.dlq", "--dry-run"]):
            ret = replay_main()
            assert ret == 0
            captured = capsys.readouterr()
            assert "[DRY-RUN] Inspected 3 message(s)" in captured.out

        with patch("sys.argv", ["replay_dlq.py"]):
            ret = replay_main()
            assert ret == 0
            captured = capsys.readouterr()
            assert "Successfully replayed 3 message(s)" in captured.out

    with patch("scripts.replay_dlq.replay_messages", side_effect=RuntimeError("AMQP Error")):
        with patch("sys.argv", ["replay_dlq.py"]):
            ret = replay_main()
            assert ret == 1
