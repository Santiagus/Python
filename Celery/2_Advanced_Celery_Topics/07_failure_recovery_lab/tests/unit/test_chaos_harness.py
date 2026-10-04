"""Unit tests for the automated chaos injection harness (scripts/chaos_harness.py).

Validates CLI argument parsing, container fault injection helpers, process signal handling,
relational ledger parity auditing, wire status polling, DLQ inspection, and experiment execution.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.chaos_harness import (
    ChaosHarness,
    ExperimentResult,
    ExperimentStatus,
    LedgerAuditResult,
    build_arg_parser,
    main,
    run_cli,
)
from shared.models import WireStatus

# -----------------------------------------------------------------------------
# CLI Argument Parser Tests
# -----------------------------------------------------------------------------


def test_build_arg_parser_defaults() -> None:
    """Verify that build_arg_parser supplies expected default values."""
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.experiment == "all"
    assert args.api_url == "http://localhost:8000"
    assert args.bank_url == "http://localhost:8010"
    assert args.broker_url == "amqp://guest:guest@localhost:5672//"
    assert "postgresql+asyncpg" in args.db_url
    assert args.compose_file == "docker-compose.yml"
    assert args.output_json == "reports/experiments/latest_experiment_log.json"
    assert args.output_markdown == "docs/EXPERIMENT_LOG.md"


def test_build_arg_parser_custom_values() -> None:
    """Verify that build_arg_parser parses custom arguments correctly."""
    parser = build_arg_parser()
    args = parser.parse_args([
        "-e", "EXP-01",
        "--api-url", "http://api.test:8000",
        "--bank-url", "http://bank.test:8010",
        "--broker-url", "amqp://user:pass@broker:5672//",
        "--db-url", "postgresql+asyncpg://user:pass@db:5432/test",
        "--compose-file", "docker-compose.override.yml",
        "--output-json", "test_report.json",
        "--output-markdown", "test_report.md",
    ])
    assert args.experiment == "EXP-01"
    assert args.api_url == "http://api.test:8000"
    assert args.bank_url == "http://bank.test:8010"
    assert args.broker_url == "amqp://user:pass@broker:5672//"
    assert args.db_url == "postgresql+asyncpg://user:pass@db:5432/test"
    assert args.compose_file == "docker-compose.override.yml"
    assert args.output_json == "test_report.json"
    assert args.output_markdown == "test_report.md"


# -----------------------------------------------------------------------------
# Harness Initialization & Lifecycle Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chaos_harness_init_and_dispose() -> None:
    """Verify initialization, session factory caching, and engine disposal."""
    harness = ChaosHarness(
        api_url="http://test-api:8000/",
        bank_url="http://test-bank:8010/",
        broker_url="amqp://test:5672//",
        db_url="postgresql+asyncpg://test:test@localhost:5432/db",
    )
    assert harness.api_url == "http://test-api:8000"
    assert harness.bank_url == "http://test-bank:8010"

    # 1. Session factory initializes internal engine
    factory = harness.get_session_factory()
    assert factory is not None
    # Cached access returns same factory
    assert harness.get_session_factory() is factory

    # 2. Engine disposal
    await harness.dispose()
    assert harness._engine is None
    assert harness._session_factory is None

    # Redundant dispose does not raise
    await harness.dispose()


# -----------------------------------------------------------------------------
# Fault Injection Primitives Tests
# -----------------------------------------------------------------------------


def test_execute_docker_command() -> None:
    """Verify docker command execution via subprocess."""
    harness = ChaosHarness(compose_file="docker-compose.test.yml")
    with patch("scripts.chaos_harness.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["docker", "compose"], returncode=0, stdout="done"
        )
        res = harness.execute_docker_command(["ps"])
        mock_run.assert_called_once_with(
            ["docker", "compose", "-f", "docker-compose.test.yml", "ps"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0


def test_container_lifecycle_commands() -> None:
    """Verify container kill, stop, start, restart, pause, and unpause helpers."""
    harness = ChaosHarness()

    with patch.object(harness, "execute_docker_command") as mock_exec:
        # 1. Kill container
        mock_exec.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert harness.kill_container("worker_1", "SIGKILL") is True
        mock_exec.assert_called_with(["kill", "-s", "SIGKILL", "worker_1"])

        # 2. Stop container
        assert harness.stop_container("rabbitmq", timeout=5) is True
        mock_exec.assert_called_with(["stop", "-t", "5", "rabbitmq"])

        # 3. Start container
        assert harness.start_container("rabbitmq") is True
        mock_exec.assert_called_with(["start", "rabbitmq"])

        # 4. Restart container
        assert harness.restart_container("worker_2", timeout=3) is True
        mock_exec.assert_called_with(["restart", "-t", "3", "worker_2"])

        # 5. Pause container
        assert harness.pause_container("worker_1") is True
        mock_exec.assert_called_with(["pause", "worker_1"])

        # 6. Unpause container
        assert harness.unpause_container("worker_1") is True
        mock_exec.assert_called_with(["unpause", "worker_1"])


def test_container_commands_failure_handling() -> None:
    """Verify that container fault helpers catch subprocess errors cleanly."""
    harness = ChaosHarness()
    with patch.object(harness, "execute_docker_command", side_effect=subprocess.SubprocessError("Docker down")):
        assert harness.kill_container("worker_1") is False
        assert harness.stop_container("rabbitmq") is False
        assert harness.start_container("rabbitmq") is False
        assert harness.restart_container("worker_2") is False
        assert harness.pause_container("worker_1") is False
        assert harness.unpause_container("worker_1") is False


def test_kill_process() -> None:
    """Verify local OS process signaling helper."""
    harness = ChaosHarness()

    # 1. Success case
    with patch("scripts.chaos_harness.os.kill") as mock_kill:
        assert harness.kill_process(12345, signal.SIGKILL) is True
        mock_kill.assert_called_once_with(12345, signal.SIGKILL)

    # 2. ProcessLookupError case
    with patch("scripts.chaos_harness.os.kill", side_effect=ProcessLookupError()):
        assert harness.kill_process(99999) is False

    # 3. PermissionError case
    with patch("scripts.chaos_harness.os.kill", side_effect=PermissionError()):
        assert harness.kill_process(1) is False


# -----------------------------------------------------------------------------
# Ledger & State Auditing Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_ledger_parity_balanced() -> None:
    """Verify ledger audit logic when journal entries are exactly balanced."""
    harness = ChaosHarness()
    session = AsyncMock(spec=AsyncSession)

    # 1. Mock query results: debits=500000, credits=500000, settled=2, unique_keys=2
    mock_debits_res = MagicMock()
    mock_debits_res.scalar_one.return_value = 500000

    mock_credits_res = MagicMock()
    mock_credits_res.scalar_one.return_value = 500000

    mock_wires_res = MagicMock()
    mock_wires_res.one.return_value = (2, 2)

    session.execute.side_effect = [mock_debits_res, mock_credits_res, mock_wires_res]

    result = await harness.audit_ledger_parity(session=session)
    assert result.total_debits_cents == 500000
    assert result.total_credits_cents == 500000
    assert result.drift_cents == 0
    assert result.settled_wires_count == 2
    assert result.unique_idempotency_keys_count == 2
    assert result.double_disbursements_count == 0
    assert result.is_balanced is True


@pytest.mark.asyncio
async def test_audit_ledger_parity_imbalanced_and_owned_session() -> None:
    """Verify ledger audit detection of financial drift and duplicate disbursements."""
    harness = ChaosHarness()

    mock_session = AsyncMock(spec=AsyncSession)
    mock_debits_res = MagicMock()
    mock_debits_res.scalar_one.return_value = 600000

    mock_credits_res = MagicMock()
    mock_credits_res.scalar_one.return_value = 500000

    mock_wires_res = MagicMock()
    mock_wires_res.one.return_value = (3, 2)  # 3 settled, only 2 unique keys -> 1 duplicate payout!

    mock_session.execute.side_effect = [mock_debits_res, mock_credits_res, mock_wires_res]

    # Test with owned session factory
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    with patch.object(harness, "get_session_factory", return_value=mock_factory):
        result = await harness.audit_ledger_parity()
        assert result.drift_cents == 100000
        assert result.double_disbursements_count == 1
        assert result.is_balanced is False


@pytest.mark.asyncio
async def test_audit_wire_status_success() -> None:
    """Verify polling wire status until settled state is reached."""
    harness = ChaosHarness(api_url="http://test-api:8000")
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # First call returns processing, second returns settled
    resp_pending = MagicMock(spec=httpx.Response)
    resp_pending.status_code = 200
    resp_pending.json.return_value = {"wire_id": "w1", "status": "processing"}

    resp_settled = MagicMock(spec=httpx.Response)
    resp_settled.status_code = 200
    resp_settled.json.return_value = {"wire_id": "w1", "status": WireStatus.SETTLED.value}

    mock_client.get.side_effect = [resp_pending, resp_settled]

    data = await harness.audit_wire_status("w1", timeout=2.0, poll_interval=0.01, client=mock_client)
    assert data["status"] == WireStatus.SETTLED.value


@pytest.mark.asyncio
async def test_audit_wire_status_timeout() -> None:
    """Verify TimeoutError raised when wire does not reach terminal status."""
    harness = ChaosHarness(api_url="http://test-api:8000")
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    resp_pending = MagicMock(spec=httpx.Response)
    resp_pending.status_code = 200
    resp_pending.json.return_value = {"wire_id": "w1", "status": "processing"}
    mock_client.get.return_value = resp_pending

    with pytest.raises(TimeoutError, match="Wire did not reach terminal state"):
        await harness.audit_wire_status("w1", timeout=0.05, poll_interval=0.01, client=mock_client)


@pytest.mark.asyncio
async def test_audit_wire_status_owned_client() -> None:
    """Verify wire status polling using internally created HTTP client."""
    harness = ChaosHarness()

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"wire_id": "w2", "status": WireStatus.SETTLED.value}

    with patch("scripts.chaos_harness.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.get.return_value = mock_resp
        mock_cls.return_value.__aenter__.return_value = instance
        mock_cls.return_value.__aexit__.return_value = None

        data = await harness.audit_wire_status("w2", timeout=1.0, poll_interval=0.01)
        assert data["status"] == WireStatus.SETTLED.value


def test_audit_dlq_messages() -> None:
    """Verify inspection and decoding of messages from wire.settlement.dlq."""
    harness = ChaosHarness()
    mock_conn = MagicMock()
    mock_channel = MagicMock()
    mock_conn.channel.return_value.__enter__.return_value = mock_channel

    mock_msg1 = MagicMock()
    mock_msg1.decode.return_value = {"bad_field": "123"}
    mock_msg1.headers = {"x-death": [{"reason": "rejected"}]}
    mock_msg1.delivery_info = {"routing_key": "wire.settlement.dlq"}

    mock_msg2 = MagicMock()
    mock_msg2.decode.return_value = {"bad_field": "456"}
    mock_msg2.headers = {}
    mock_msg2.delivery_info = {}

    with patch("scripts.chaos_harness.wire_dlq_queue") as mock_queue_fn:
        mock_q = MagicMock()
        mock_queue_fn.return_value = mock_q
        mock_q.get.side_effect = [mock_msg1, mock_msg2, None]

        # 1. Inspect with requeue=True
        msgs = harness.audit_dlq_messages(max_messages=5, connection=mock_conn, requeue=True)
        assert len(msgs) == 2
        mock_msg1.requeue.assert_called_once()
        mock_msg2.requeue.assert_called_once()

        # 2. Inspect with requeue=False (ACK)
        mock_q.get.side_effect = [mock_msg1, None]
        msgs_ack = harness.audit_dlq_messages(max_messages=1, connection=mock_conn, requeue=False)
        assert len(msgs_ack) == 1
        mock_msg1.ack.assert_called_once()


# -----------------------------------------------------------------------------
# Core Chaos Experiment Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_experiment_1_worker_sigkill_passed() -> None:
    """Verify Experiment 1 happy path execution and verification."""
    harness = ChaosHarness()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # 1. Mock wire ingestion response
    post_resp = MagicMock(spec=httpx.Response)
    post_resp.status_code = 202
    post_resp.json.return_value = {"wire_id": "00000000-0000-0000-0000-000000000001", "status": "processing"}
    mock_client.post.return_value = post_resp

    # 2. Mock container kill
    with patch.object(harness, "kill_container", return_value=True) as mock_kill, \
         patch.object(harness, "audit_wire_status", return_value={"status": "settled", "redelivered_flag": True}), \
         patch.object(harness, "audit_ledger_parity", return_value=LedgerAuditResult(
             total_debits_cents=10000000,
             total_credits_cents=10000000,
             drift_cents=0,
             settled_wires_count=1,
             unique_idempotency_keys_count=1,
             is_balanced=True,
             double_disbursements_count=0,
         )):

        result = await harness.run_experiment_1_worker_sigkill(client=mock_client)
        assert result.experiment_id == "EXP-01"
        assert result.status == ExperimentStatus.PASSED
        assert result.error_message is None
        mock_kill.assert_called_once_with("worker_1", "SIGKILL")


@pytest.mark.asyncio
async def test_run_experiment_1_worker_sigkill_failed() -> None:
    """Verify Experiment 1 catches failures (e.g., HTTP 500 on ingestion)."""
    harness = ChaosHarness()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    post_resp = MagicMock(spec=httpx.Response)
    post_resp.status_code = 500
    post_resp.text = "Internal error"
    mock_client.post.return_value = post_resp

    result = await harness.run_experiment_1_worker_sigkill(client=mock_client)
    assert result.experiment_id == "EXP-01"
    assert result.status == ExperimentStatus.FAILED
    assert "Wire ingestion failed" in str(result.error_message)


@pytest.mark.asyncio
async def test_run_experiment_1_ledger_imbalance_failure() -> None:
    """Verify Experiment 1 fails if ledger imbalance is detected."""
    harness = ChaosHarness()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    post_resp = MagicMock(spec=httpx.Response)
    post_resp.status_code = 202
    post_resp.json.return_value = {"wire_id": "w1", "status": "processing"}
    mock_client.post.return_value = post_resp

    with patch.object(harness, "kill_container", return_value=True), \
         patch.object(harness, "audit_wire_status", return_value={"status": "settled"}), \
         patch.object(harness, "audit_ledger_parity", return_value=LedgerAuditResult(
             total_debits_cents=100,
             total_credits_cents=50,
             drift_cents=50,
             settled_wires_count=1,
             unique_idempotency_keys_count=1,
             is_balanced=False,
             double_disbursements_count=0,
         )):
        result = await harness.run_experiment_1_worker_sigkill(client=mock_client)
        assert result.status == ExperimentStatus.FAILED
        assert "Ledger imbalance detected" in str(result.error_message)


@pytest.mark.asyncio
async def test_run_experiment_2_ack_modes_passed_and_failed() -> None:
    """Verify Experiment 2 early vs late ack verification."""
    harness = ChaosHarness()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # 1. Passed case
    post_resp = MagicMock(spec=httpx.Response)
    post_resp.status_code = 202
    post_resp.json.return_value = {"wire_id": "w2"}
    mock_client.post.return_value = post_resp

    with patch.object(harness, "audit_wire_status", return_value={"status": "settled"}):
        res_pass = await harness.run_experiment_2_ack_modes(client=mock_client)
        assert res_pass.experiment_id == "EXP-02"
        assert res_pass.status == ExperimentStatus.PASSED

    # 2. Failed case
    post_fail = MagicMock(spec=httpx.Response)
    post_fail.status_code = 400
    post_fail.text = "Bad Request"
    mock_client.post.return_value = post_fail

    res_fail = await harness.run_experiment_2_ack_modes(client=mock_client)
    assert res_fail.experiment_id == "EXP-02"
    assert res_fail.status == ExperimentStatus.FAILED


@pytest.mark.asyncio
async def test_run_experiment_3_broker_outage_passed_and_failed() -> None:
    """Verify Experiment 3 broker crash and recovery."""
    harness = ChaosHarness()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    # 1. Passed case
    post_resp = MagicMock(spec=httpx.Response)
    post_resp.status_code = 202
    post_resp.json.return_value = {"wire_id": "w3"}
    mock_client.post.return_value = post_resp

    with patch.object(harness, "stop_container", return_value=True) as mock_stop, \
         patch.object(harness, "start_container", return_value=True) as mock_start, \
         patch.object(harness, "audit_wire_status", return_value={"status": "settled"}):

        res_pass = await harness.run_experiment_3_broker_outage(client=mock_client, downtime_seconds=0.01)
        assert res_pass.experiment_id == "EXP-03"
        assert res_pass.status == ExperimentStatus.PASSED
        mock_stop.assert_called_once_with("rabbitmq", timeout=2)
        mock_start.assert_called_once_with("rabbitmq")

    # 2. Failed case
    post_fail = MagicMock(spec=httpx.Response)
    post_fail.status_code = 503
    post_fail.text = "Service unavailable"
    mock_client.post.return_value = post_fail

    res_fail = await harness.run_experiment_3_broker_outage(client=mock_client, downtime_seconds=0.01)
    assert res_fail.status == ExperimentStatus.FAILED


def test_run_experiment_4_poison_pill_passed_and_failed() -> None:
    """Verify Experiment 4 poison pill dispatch to DLQ."""
    harness = ChaosHarness()
    mock_conn = MagicMock()
    mock_channel = MagicMock()
    mock_conn.channel.return_value.__enter__.return_value = mock_channel

    # 1. Passed case
    with patch("scripts.chaos_harness.wire_critical_queue") as mock_q_fn:
        mock_q = MagicMock()
        mock_q_fn.return_value = mock_q
        res_pass = harness.run_experiment_4_poison_pill(connection=mock_conn)
        assert res_pass.experiment_id == "EXP-04"
        assert res_pass.status == ExperimentStatus.PASSED
        mock_channel.basic_publish.assert_called_once()

    # 2. Failed case
    mock_conn_err = MagicMock()
    mock_conn_err.channel.side_effect = RuntimeError("Broker connection dropped")
    res_fail = harness.run_experiment_4_poison_pill(connection=mock_conn_err)
    assert res_fail.experiment_id == "EXP-04"
    assert res_fail.status == ExperimentStatus.FAILED

    # 3. Connection is None default initialization
    with patch("scripts.chaos_harness.Connection") as mock_conn_cls, \
         patch("scripts.chaos_harness.wire_critical_queue") as mock_q_fn:
        conn_inst = MagicMock()
        conn_inst.channel.return_value.__enter__.return_value = mock_channel
        mock_conn_cls.return_value = conn_inst
        mock_q_fn.return_value = MagicMock()
        res_none = harness.run_experiment_4_poison_pill(connection=None)
        assert res_none.status == ExperimentStatus.PASSED
        conn_inst.connect.assert_called_once()


@pytest.mark.asyncio
async def test_run_experiment_5_mttr_benchmarks_passed_and_failed() -> None:
    """Verify Experiment 5 compound chaos MTTR benchmarking."""
    harness = ChaosHarness()

    balanced_audit = LedgerAuditResult(
        total_debits_cents=1000,
        total_credits_cents=1000,
        drift_cents=0,
        settled_wires_count=1,
        unique_idempotency_keys_count=1,
        is_balanced=True,
        double_disbursements_count=0,
    )

    imbalanced_audit = LedgerAuditResult(
        total_debits_cents=1000,
        total_credits_cents=800,
        drift_cents=200,
        settled_wires_count=1,
        unique_idempotency_keys_count=1,
        is_balanced=False,
        double_disbursements_count=0,
    )

    # 1. Passed case
    with patch.object(harness, "audit_ledger_parity", side_effect=[balanced_audit, balanced_audit]), \
         patch.object(harness, "kill_container", return_value=True), \
         patch.object(harness, "start_container", return_value=True):
        res_pass = await harness.run_experiment_5_mttr_benchmarks()
        assert res_pass.experiment_id == "EXP-05"
        assert res_pass.status == ExperimentStatus.PASSED

    # 2. Drift failure case
    with patch.object(harness, "audit_ledger_parity", side_effect=[balanced_audit, imbalanced_audit]), \
         patch.object(harness, "kill_container", return_value=True), \
         patch.object(harness, "start_container", return_value=True):
        res_fail = await harness.run_experiment_5_mttr_benchmarks()
        assert res_fail.experiment_id == "EXP-05"
        assert res_fail.status == ExperimentStatus.FAILED
        assert "Mathematical drift detected" in str(res_fail.error_message)


@pytest.mark.asyncio
async def test_run_all_experiments() -> None:
    """Verify sequential execution of all five experiments."""
    harness = ChaosHarness()
    mock_res = ExperimentResult(
        experiment_id="TEST",
        name="Test",
        status=ExperimentStatus.PASSED,
        mttr_ms=10.0,
        started_at="",
        finished_at="",
    )

    with patch.object(harness, "run_experiment_1_worker_sigkill", return_value=mock_res), \
         patch.object(harness, "run_experiment_2_ack_modes", return_value=mock_res), \
         patch.object(harness, "run_experiment_3_broker_outage", return_value=mock_res), \
         patch.object(harness, "run_experiment_4_poison_pill", return_value=mock_res), \
         patch.object(harness, "run_experiment_5_mttr_benchmarks", return_value=mock_res):

        results = await harness.run_all_experiments()
        assert len(results) == 5


# -----------------------------------------------------------------------------
# Reporting & File Persistence Tests
# -----------------------------------------------------------------------------


def test_reporting_and_persistence(tmp_path: Path) -> None:
    """Verify JSON report generation, Markdown rendering, and disk persistence."""
    harness = ChaosHarness()
    results = [
        ExperimentResult(
            experiment_id="EXP-01",
            name="Worker SIGKILL",
            status=ExperimentStatus.PASSED,
            mttr_ms=150.0,
            started_at="2026-10-04T12:00:00Z",
            finished_at="2026-10-04T12:00:01Z",
        ),
        ExperimentResult(
            experiment_id="EXP-02",
            name="Early vs Late Ack",
            status=ExperimentStatus.FAILED,
            mttr_ms=250.0,
            started_at="2026-10-04T12:00:01Z",
            finished_at="2026-10-04T12:00:02Z",
            error_message="Simulated failure",
        ),
    ]

    # 1. Generate JSON report
    report_data = harness.generate_report(results)
    assert report_data["summary"]["total_experiments"] == 2
    assert report_data["summary"]["passed"] == 1
    assert report_data["summary"]["failed"] == 1
    assert report_data["summary"]["average_mttr_ms"] == 200.0

    # Test empty results list
    empty_report = harness.generate_report([])
    assert empty_report["summary"]["average_mttr_ms"] == 0.0

    # 2. Save JSON report to disk
    json_path = tmp_path / "reports" / "report.json"
    saved_json = harness.save_json_report(report_data, json_path)
    assert saved_json.exists()
    loaded_data = json.loads(saved_json.read_text(encoding="utf-8"))
    assert loaded_data["summary"]["total_experiments"] == 2

    # 3. Render Markdown report
    md_content = harness.render_markdown_report(report_data)
    assert "# Chaos Engineering & Failure Recovery Experiment Log" in md_content
    assert "Worker SIGKILL" in md_content
    assert "Simulated failure" in md_content

    # 4. Save Markdown report to disk
    md_path = tmp_path / "docs" / "log.md"
    saved_md = harness.save_markdown_report(md_content, md_path)
    assert saved_md.exists()
    assert "# Chaos Engineering" in saved_md.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# CLI Execution & main() Entrypoint Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cli_subcommands(tmp_path: Path) -> None:
    """Verify run_cli routing for single experiment and all experiments."""
    json_path = str(tmp_path / "report.json")
    md_path = str(tmp_path / "report.md")

    mock_res_pass = ExperimentResult(
        experiment_id="EXP-TEST",
        name="Test",
        status=ExperimentStatus.PASSED,
        mttr_ms=5.0,
        started_at="",
        finished_at="",
    )

    # 1. EXP-01
    args_exp1 = argparse.Namespace(
        experiment="EXP-01",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_experiment_1_worker_sigkill", return_value=mock_res_pass):
        assert await run_cli(args_exp1) == 0

    # 2. EXP-02
    args_exp2 = argparse.Namespace(
        experiment="EXP-02",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_experiment_2_ack_modes", return_value=mock_res_pass):
        assert await run_cli(args_exp2) == 0

    # 3. EXP-03
    args_exp3 = argparse.Namespace(
        experiment="EXP-03",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_experiment_3_broker_outage", return_value=mock_res_pass):
        assert await run_cli(args_exp3) == 0

    # 4. EXP-04
    args_exp4 = argparse.Namespace(
        experiment="EXP-04",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_experiment_4_poison_pill", return_value=mock_res_pass):
        assert await run_cli(args_exp4) == 0

    # 5. EXP-05
    args_exp5 = argparse.Namespace(
        experiment="EXP-05",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_experiment_5_mttr_benchmarks", return_value=mock_res_pass):
        assert await run_cli(args_exp5) == 0

    # 6. 'all' experiments option
    args_all = argparse.Namespace(
        experiment="all",
        api_url="http://localhost:8000",
        bank_url="http://localhost:8010",
        broker_url="amqp://localhost",
        db_url="postgresql+asyncpg://localhost/test",
        compose_file="docker-compose.yml",
        output_json=json_path,
        output_markdown=md_path,
    )
    with patch.object(ChaosHarness, "run_all_experiments", return_value=[mock_res_pass]):
        assert await run_cli(args_all) == 0

    # 7. Failed exit code test
    mock_res_fail = ExperimentResult(
        experiment_id="EXP-FAIL",
        name="Fail",
        status=ExperimentStatus.FAILED,
        mttr_ms=5.0,
        started_at="",
        finished_at="",
    )
    with patch.object(ChaosHarness, "run_experiment_1_worker_sigkill", return_value=mock_res_fail):
        assert await run_cli(args_exp1) == 1


@pytest.mark.asyncio
async def test_run_experiments_owned_client() -> None:
    """Verify experiments 1, 2, and 3 when using default owned client."""
    harness = ChaosHarness()

    mock_resp_post = MagicMock(spec=httpx.Response)
    mock_resp_post.status_code = 202
    mock_resp_post.json.return_value = {"wire_id": "00000000-0000-0000-0000-000000000001"}

    with patch("scripts.chaos_harness.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.post.return_value = mock_resp_post
        mock_cls.return_value = instance

        with patch.object(harness, "kill_container", return_value=True), \
             patch.object(harness, "stop_container", return_value=True), \
             patch.object(harness, "start_container", return_value=True), \
             patch.object(harness, "audit_wire_status", return_value={"status": "settled"}), \
             patch.object(harness, "audit_ledger_parity", return_value=LedgerAuditResult(
                 total_debits_cents=100,
                 total_credits_cents=100,
                 drift_cents=0,
                 settled_wires_count=1,
                 unique_idempotency_keys_count=1,
                 is_balanced=True,
                 double_disbursements_count=0,
             )):

            res1 = await harness.run_experiment_1_worker_sigkill(client=None)
            assert res1.status == ExperimentStatus.PASSED

            res2 = await harness.run_experiment_2_ack_modes(client=None)
            assert res2.status == ExperimentStatus.PASSED

            res3 = await harness.run_experiment_3_broker_outage(client=None, downtime_seconds=0.001)
            assert res3.status == ExperimentStatus.PASSED


def test_main_entrypoint() -> None:
    """Verify main() function executes cleanly with argument delegation."""
    with patch("scripts.chaos_harness.run_cli", new_callable=AsyncMock) as mock_run_cli:
        mock_run_cli.return_value = 0
        code = main(["-e", "EXP-01"])
        assert code == 0
        mock_run_cli.assert_called_once()


def test_dunder_main_block(tmp_path: Path) -> None:
    """Verify execution of the if __name__ == '__main__' block."""
    import runpy

    tmp_json = str(tmp_path / "report.json")
    tmp_md = str(tmp_path / "report.md")

    with patch("sys.argv", ["chaos_harness.py", "-e", "EXP-01", "--output-json", tmp_json, "--output-markdown", tmp_md]), \
         patch("sys.exit") as mock_exit:
        runpy.run_path("scripts/chaos_harness.py", run_name="__main__")
        mock_exit.assert_called_once_with(1)
