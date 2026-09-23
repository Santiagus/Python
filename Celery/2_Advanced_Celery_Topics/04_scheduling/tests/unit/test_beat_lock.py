"""Unit tests for high-availability Celery Beat leader election and custom scheduler.

Validates atomic Redis leader lease acquisition, periodic heartbeat renewal, failover
when the leader lease expires, and LeaderElectedScheduler standby tick suppression.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.worker.beat_lock import LeaderElectedScheduler, LeaderElection
from services.worker.celery_app import celery_app


@pytest.mark.unit
def test_leader_election_acquire_success() -> None:
    """Verify acquire_lease returns True when Redis SET NX succeeds."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    election = LeaderElection(client=mock_redis, instance_id="replica-1")
    assert election.acquire_lease() is True
    mock_redis.set.assert_called_once_with(
        "celery:beat:leader_lock",
        "replica-1",
        nx=True,
        ex=15,
    )


@pytest.mark.unit
def test_leader_election_acquire_failure() -> None:
    """Verify acquire_lease returns False when Redis SET NX fails (already held)."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = None

    election = LeaderElection(client=mock_redis, instance_id="replica-2")
    assert election.acquire_lease() is False


@pytest.mark.unit
def test_leader_election_renew_success_and_failure() -> None:
    """Verify renew_lease handles Lua script return codes."""
    mock_redis = MagicMock()
    election = LeaderElection(client=mock_redis, instance_id="replica-1")

    # 1. Renewal succeeds (Lua returns 1)
    mock_redis.eval.return_value = 1
    assert election.renew_lease() is True

    # 2. Renewal fails because another instance owns lease (Lua returns 0)
    mock_redis.eval.return_value = 0
    assert election.renew_lease() is False

    # 3. Renewal handles Redis network exceptions gracefully
    mock_redis.eval.side_effect = RuntimeError("Redis connection lost")
    assert election.renew_lease() is False


@pytest.mark.unit
def test_leader_election_release_success_and_failure() -> None:
    """Verify release_lease handles Lua script release."""
    mock_redis = MagicMock()
    election = LeaderElection(client=mock_redis, instance_id="replica-1")

    # 1. Release succeeds
    mock_redis.eval.return_value = 1
    assert election.release_lease() is True

    # 2. Release fails (not owned or already expired)
    mock_redis.eval.return_value = 0
    assert election.release_lease() is False

    # 3. Release handles exception
    mock_redis.eval.side_effect = RuntimeError("Redis timeout")
    assert election.release_lease() is False


@pytest.mark.unit
def test_leader_elected_scheduler_standby_poll() -> None:
    """Verify standby replica does not evaluate schedules and returns standby_interval."""
    mock_election = MagicMock()
    mock_election.acquire_lease.return_value = False
    mock_election.standby_interval = 5.0
    mock_election.instance_id = "standby-node"

    scheduler = LeaderElectedScheduler(
        app=celery_app,
        leader_election=mock_election,
        lazy=True,
    )

    with patch("celery.beat.Scheduler.tick") as mock_super_tick:
        interval = scheduler.tick()
        assert interval == 5.0
        assert scheduler.is_leader is False
        mock_super_tick.assert_not_called()


@pytest.mark.unit
def test_leader_elected_scheduler_promotion_to_leader() -> None:
    """Verify standby replica is promoted to leader upon acquiring lease and runs tick."""
    mock_election = MagicMock()
    mock_election.acquire_lease.return_value = True
    mock_election.renewal_interval = 5.0
    mock_election.instance_id = "new-leader"

    scheduler = LeaderElectedScheduler(
        app=celery_app,
        leader_election=mock_election,
        lazy=True,
    )

    with patch("celery.beat.Scheduler.tick", return_value=10.0) as mock_super_tick:
        interval = scheduler.tick()
        assert interval == 10.0
        assert scheduler.is_leader is True
        mock_super_tick.assert_called_once()


@pytest.mark.unit
def test_leader_elected_scheduler_renewal_and_demotion() -> None:
    """Verify active leader attempts renewal and is demoted if renewal fails."""
    mock_election = MagicMock()
    mock_election.renewal_interval = 2.0
    mock_election.standby_interval = 5.0
    mock_election.instance_id = "leader-node"

    scheduler = LeaderElectedScheduler(
        app=celery_app,
        leader_election=mock_election,
        lazy=True,
    )
    scheduler.is_leader = True
    scheduler.last_renewal = 100.0

    # 1. Monotonic clock does NOT exceed renewal interval, skips renew_lease
    mock_election.renew_lease.return_value = True
    with patch("time.monotonic", return_value=101.0):
        with patch("celery.beat.Scheduler.tick", return_value=2.0) as mock_super_tick:
            interval = scheduler.tick()
            assert interval == 2.0
            assert scheduler.is_leader is True
            mock_election.renew_lease.assert_not_called()
            mock_super_tick.assert_called_once()

    # 2. Monotonic clock exceeds renewal interval, renewal succeeds
    with patch("time.monotonic", return_value=103.0):
        with patch("celery.beat.Scheduler.tick", return_value=1.5) as mock_super_tick:
            interval = scheduler.tick()
            assert interval == 1.5
            assert scheduler.is_leader is True
            mock_election.renew_lease.assert_called_once()
            mock_super_tick.assert_called_once()

    # 3. Monotonic clock exceeds renewal interval, renewal fails -> demoted
    mock_election.renew_lease.reset_mock()
    mock_election.renew_lease.return_value = False
    with patch("time.monotonic", return_value=106.0):
        with patch("celery.beat.Scheduler.tick") as mock_super_tick:
            interval = scheduler.tick()
            assert interval == 5.0
            assert scheduler.is_leader is False
            mock_super_tick.assert_not_called()


@pytest.mark.unit
def test_leader_elected_scheduler_close_releases_lease() -> None:
    """Verify closing active leader releases lease, while closing standby does not."""
    mock_election = MagicMock()
    scheduler = LeaderElectedScheduler(
        app=celery_app,
        leader_election=mock_election,
        lazy=True,
    )

    # 1. Close when standby
    scheduler.is_leader = False
    scheduler.close()
    mock_election.release_lease.assert_not_called()

    # 2. Close when active leader
    scheduler.is_leader = True
    scheduler.close()
    mock_election.release_lease.assert_called_once()
    assert scheduler.is_leader is False


@pytest.mark.unit
def test_multi_beat_failover_simulation() -> None:
    """Simulate primary leader failing and standby taking over scheduling."""
    # Shared simulated Redis dictionary
    simulated_redis: dict[str, str] = {}

    def fake_set(key: str, val: str, nx: bool = False, ex: int = 15) -> bool:
        if nx and key in simulated_redis:
            return False
        simulated_redis[key] = val
        return True

    mock_redis = MagicMock()
    mock_redis.set.side_effect = fake_set

    # Instance 1: Primary
    primary_election = LeaderElection(client=mock_redis, instance_id="replica-primary")
    primary_scheduler = LeaderElectedScheduler(app=celery_app, leader_election=primary_election, lazy=True)

    # Instance 2: Standby
    standby_election = LeaderElection(client=mock_redis, instance_id="replica-standby")
    standby_scheduler = LeaderElectedScheduler(app=celery_app, leader_election=standby_election, lazy=True)

    with patch("celery.beat.Scheduler.tick", return_value=1.0):
        # 1. Primary starts first: acquires lease and becomes leader
        assert primary_scheduler.tick() == 1.0
        assert primary_scheduler.is_leader is True
        assert simulated_redis["celery:beat:leader_lock"] == "replica-primary"

        # 2. Standby starts second: fails to acquire lease and remains standby
        s_interval = standby_scheduler.tick()
        assert standby_scheduler.is_leader is False
        assert s_interval == 5.0

        # 3. Primary terminates: releases lease
        primary_scheduler.close()
        simulated_redis.pop("celery:beat:leader_lock", None)

        # 4. Standby ticks on next cycle: acquires lease and is promoted to leader!
        assert standby_scheduler.tick() == 1.0
        assert standby_scheduler.is_leader is True
        assert simulated_redis["celery:beat:leader_lock"] == "replica-standby"
