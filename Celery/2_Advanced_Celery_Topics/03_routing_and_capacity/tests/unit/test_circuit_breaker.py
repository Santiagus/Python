"""Unit tests for DistributedCircuitBreaker and partner bank rail failover."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    DistributedCircuitBreaker,
    get_circuit_breaker,
    get_fallback_rail,
    reset_all_circuit_breakers,
)


@pytest.mark.unit
class TestCircuitBreaker:
    """Test sliding-window circuit breaker state machine and failover."""

    def setup_method(self) -> None:
        """Reset all circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_init_and_state_defaults(self) -> None:
        """Verify initial default state is CLOSED."""
        cb = DistributedCircuitBreaker(rail="rtp")
        assert cb.rail == "rtp"
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        assert cb.failure_threshold_pct == 50.0
        assert cb.rolling_window_seconds == 30.0
        assert cb.min_requests == 5
        assert cb.recovery_timeout_seconds == 15.0

    def test_record_success_in_closed_state(self) -> None:
        """Verify successful executions in CLOSED keep circuit CLOSED."""
        cb = DistributedCircuitBreaker(rail="rtp", min_requests=3)
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        assert len(cb._success_timestamps) == 2

    def test_failure_below_min_requests_does_not_trip(self) -> None:
        """Failures do not trip the circuit before min_requests threshold is reached."""
        cb = DistributedCircuitBreaker(rail="rtp", min_requests=5, failure_threshold_pct=50.0)
        # 4 consecutive failures (100% failure rate, but < 5 requests)
        for _ in range(4):
            cb.record_failure()

        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_failure_with_min_requests_met_below_threshold(self) -> None:
        """Calls meet min_requests but failure rate is below threshold, circuit stays CLOSED."""
        cb = DistributedCircuitBreaker(rail="rtp", min_requests=5, failure_threshold_pct=50.0)
        # 4 successes, 1 failure = 20% failure rate (< 50%)
        for _ in range(4):
            cb.record_success()
        cb.record_failure()

        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_failure_above_threshold_trips_to_open(self) -> None:
        """Circuit trips to OPEN when failure rate meets or exceeds threshold."""
        cb = DistributedCircuitBreaker(rail="rtp", min_requests=4, failure_threshold_pct=50.0)
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()  # 2 failures / 4 requests = 50.0% -> Trips OPEN

        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_recovery_timeout_transitions_to_half_open(self) -> None:
        """OPEN state transitions to HALF_OPEN after recovery_timeout_seconds."""
        cb = DistributedCircuitBreaker(rail="rtp", recovery_timeout_seconds=10.0)
        cb._trip(now=time.monotonic() - 11.0)

        assert cb.state == CircuitState.HALF_OPEN
        assert cb.can_execute() is True

    def test_open_state_persists_before_recovery_timeout(self) -> None:
        """OPEN state persists if recovery timeout has not elapsed."""
        cb = DistributedCircuitBreaker(rail="rtp", recovery_timeout_seconds=10.0)
        cb._trip(now=time.monotonic() - 5.0)

        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_canary_probe_success_recovers_to_closed(self) -> None:
        """A successful request in HALF_OPEN restores circuit to CLOSED."""
        cb = DistributedCircuitBreaker(rail="rtp", recovery_timeout_seconds=5.0)
        cb._trip(now=time.monotonic() - 6.0)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert len(cb._failure_timestamps) == 0
        assert cb.can_execute() is True

    def test_canary_probe_failure_trips_back_to_open(self) -> None:
        """A failed request in HALF_OPEN immediately re-trips to OPEN."""
        cb = DistributedCircuitBreaker(rail="rtp", recovery_timeout_seconds=5.0)
        cb._trip(now=time.monotonic() - 6.0)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_rolling_window_cleans_old_timestamps(self) -> None:
        """Timestamps older than rolling_window_seconds are purged."""
        cb = DistributedCircuitBreaker(rail="rtp", rolling_window_seconds=10.0)
        old_time = time.monotonic() - 15.0
        cb._success_timestamps.append(old_time)
        cb._failure_timestamps.append(old_time)

        cb._clean_old_records(now=time.monotonic())
        assert len(cb._success_timestamps) == 0
        assert len(cb._failure_timestamps) == 0

    def test_reset(self) -> None:
        """Verify reset clears timestamps and forces CLOSED state."""
        cb = DistributedCircuitBreaker(rail="rtp")
        cb._trip(now=time.monotonic())
        cb._failure_timestamps.append(time.monotonic())
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._tripped_at == 0.0
        assert len(cb._failure_timestamps) == 0

    def test_circuit_breaker_open_error(self) -> None:
        """Verify custom exception carries rail and message."""
        err_default = CircuitBreakerOpenError(rail="rtp")
        assert err_default.rail == "rtp"
        assert "Circuit breaker for rail 'rtp' is OPEN" in str(err_default)

        err_custom = CircuitBreakerOpenError(rail="fednow", message="Custom message")
        assert err_custom.rail == "fednow"
        assert str(err_custom) == "Custom message"

    def test_get_circuit_breaker_and_reset_all(self) -> None:
        """Verify registry lookup, case normalization, and global reset."""
        cb1 = get_circuit_breaker("RTP")
        cb2 = get_circuit_breaker("rtp")
        assert cb1 is cb2

        custom = get_circuit_breaker("visa_direct")
        assert custom.rail == "visa_direct"

        custom._trip(now=time.monotonic())
        assert custom.state == CircuitState.OPEN

        reset_all_circuit_breakers()
        assert custom.state == CircuitState.CLOSED

    def test_get_fallback_rail(self) -> None:
        """Verify dynamic failover to alternative healthy rail."""
        rtp_cb = get_circuit_breaker("rtp")
        fednow_cb = get_circuit_breaker("fednow")

        # Both healthy: RTP falls back to FedNow, FedNow to RTP
        assert get_fallback_rail("rtp") == "fednow"
        assert get_fallback_rail("fednow") == "rtp"

        # If FedNow is OPEN, RTP has no healthy fallback
        fednow_cb._trip(now=time.monotonic())
        assert get_fallback_rail("rtp") is None

        # If RTP is OPEN, FedNow falls back to None if RTP is also OPEN
        rtp_cb._trip(now=time.monotonic())
        assert get_fallback_rail("fednow") is None
