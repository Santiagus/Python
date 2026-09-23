"""Distributed Circuit Breaker with Automated Outbound Partner Rail Failover.

Protects Celery worker fleets and database row locks from downstream bank outages.
Monitors error rates over a rolling time window, transitions to OPEN to fail-fast
when error thresholds are breached, and supports automatic failover between instant rails
(e.g., RTP -> FedNow).
"""

from __future__ import annotations

from enum import Enum
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Lifecycle states for the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is rejected because the target circuit is OPEN."""

    def __init__(self, rail: str, message: str | None = None) -> None:
        super().__init__(message or f"Circuit breaker for rail '{rail}' is OPEN")
        self.rail = rail


class DistributedCircuitBreaker:
    """Sliding-window circuit breaker tracking partner bank clearance health."""

    def __init__(
        self,
        rail: str,
        failure_threshold_pct: float = 50.0,
        rolling_window_seconds: float = 30.0,
        min_requests: int = 5,
        recovery_timeout_seconds: float = 15.0,
    ) -> None:
        """Initialize circuit breaker for a financial rail.

        Args:
            rail: Financial rail identifier (e.g. 'rtp', 'fednow').
            failure_threshold_pct: Percentage of failures (5xx/timeouts) to trip circuit (0-100).
            rolling_window_seconds: Rolling measurement window in seconds.
            min_requests: Minimum request count in rolling window before tripping can occur.
            recovery_timeout_seconds: Seconds to wait in OPEN state before testing with HALF_OPEN canary.
        """
        self.rail = rail
        self.failure_threshold_pct = failure_threshold_pct
        self.rolling_window_seconds = rolling_window_seconds
        self.min_requests = min_requests
        self.recovery_timeout_seconds = recovery_timeout_seconds

        self._state: CircuitState = CircuitState.CLOSED
        self._tripped_at: float = 0.0
        self._success_timestamps: list[float] = []
        self._failure_timestamps: list[float] = []

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state, evaluating recovery timeout."""
        now = time.monotonic()
        if self._state == CircuitState.OPEN:
            if now - self._tripped_at >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_breaker_half_open_probe",
                    extra={"rail": self.rail, "waited_seconds": now - self._tripped_at},
                )
        return self._state

    def can_execute(self) -> bool:
        """Determine whether an outbound call is permitted through the circuit.

        Returns:
            bool: True if call should proceed (CLOSED or HALF_OPEN), False if blocked (OPEN).
        """
        current_state = self.state
        return current_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful partner bank clearance."""
        now = time.monotonic()
        self._clean_old_records(now)
        self._success_timestamps.append(now)

        if self._state == CircuitState.HALF_OPEN:
            # Canary succeeded: recover fully to CLOSED
            self._state = CircuitState.CLOSED
            self._failure_timestamps.clear()
            logger.info("circuit_breaker_recovered_to_closed", extra={"rail": self.rail})

    def record_failure(self) -> None:
        """Record a failed partner bank clearance (5xx or network timeout)."""
        now = time.monotonic()
        self._clean_old_records(now)
        self._failure_timestamps.append(now)

        if self._state == CircuitState.HALF_OPEN:
            # Canary probe failed: immediately trip back to OPEN
            self._trip(now)
            return

        # In CLOSED state: evaluate rolling failure rate
        total_calls = len(self._success_timestamps) + len(self._failure_timestamps)
        if total_calls >= self.min_requests:
            failure_rate = (len(self._failure_timestamps) / total_calls) * 100.0
            if failure_rate >= self.failure_threshold_pct:
                logger.warning(
                    "circuit_breaker_tripped_open",
                    extra={
                        "rail": self.rail,
                        "failure_rate": f"{failure_rate:.1f}%",
                        "failures": len(self._failure_timestamps),
                        "total_calls": total_calls,
                    },
                )
                self._trip(now)

    def _trip(self, now: float) -> None:
        """Transition circuit breaker to OPEN state."""
        self._state = CircuitState.OPEN
        self._tripped_at = now

    def _clean_old_records(self, now: float) -> None:
        """Purge timestamps older than the rolling window."""
        cutoff = now - self.rolling_window_seconds
        self._success_timestamps = [t for t in self._success_timestamps if t > cutoff]
        self._failure_timestamps = [t for t in self._failure_timestamps if t > cutoff]

    def reset(self) -> None:
        """Force reset circuit breaker to pristine CLOSED state (test isolation hook)."""
        self._state = CircuitState.CLOSED
        self._tripped_at = 0.0
        self._success_timestamps.clear()
        self._failure_timestamps.clear()


# Module-level registry of per-rail circuit breakers
_rail_circuit_breakers: dict[str, DistributedCircuitBreaker] = {
    "rtp": DistributedCircuitBreaker(rail="rtp"),
    "fednow": DistributedCircuitBreaker(rail="fednow"),
}


def get_circuit_breaker(rail: str) -> DistributedCircuitBreaker:
    """Return or initialize the circuit breaker for a given financial rail.

    Args:
        rail: Rail identifier string (e.g. 'rtp', 'fednow').

    Returns:
        DistributedCircuitBreaker: The configured circuit breaker instance.
    """
    clean_rail = rail.lower().strip()
    if clean_rail not in _rail_circuit_breakers:
        _rail_circuit_breakers[clean_rail] = DistributedCircuitBreaker(rail=clean_rail)
    return _rail_circuit_breakers[clean_rail]


def reset_all_circuit_breakers() -> None:
    """Reset all registered circuit breakers to CLOSED (test isolation hook)."""
    for cb in _rail_circuit_breakers.values():
        cb.reset()


def get_fallback_rail(primary_rail: str) -> str | None:
    """Determine the optimal healthy fallback rail if primary rail is degraded.

    Args:
        primary_rail: The requested payment rail (e.g. 'rtp').

    Returns:
        str | None: Alternative healthy rail ('fednow' if RTP is down, 'rtp' if FedNow is down),
                    or None if no healthy alternative exists.
    """
    clean_primary = primary_rail.lower().strip()
    candidate = "fednow" if clean_primary == "rtp" else "rtp"
    candidate_cb = get_circuit_breaker(candidate)
    if candidate_cb.can_execute():
        return candidate
    return None

