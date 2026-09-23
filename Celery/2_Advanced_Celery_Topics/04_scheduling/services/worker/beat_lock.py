"""High-availability Celery Beat leader election and distributed scheduler.

Provides an atomic Redis lease mechanism to ensure only a single Celery Beat instance
evaluates crontab schedules and dispatches tasks at any given time, preventing duplicate
periodic task execution across redundant active-standby scheduler replicas.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import redis
from celery.beat import Scheduler

from services.worker.locks import get_redis_client

logger = logging.getLogger(__name__)

# Atomic Lua renewal script: extend TTL only if current instance owns the lease
_RENEW_LUA_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""

# Atomic Lua release script: delete lease key only if current instance owns it
_RELEASE_LUA_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LeaderElection:
    """Atomic Redis leader lease manager for high-availability scheduling.

    Coordinates primary/standby failover using Redis key expiration and Lua scripts.
    """

    def __init__(
        self,
        lease_key: str = "celery:beat:leader_lock",
        ttl_seconds: int = 15,
        renewal_interval: float = 5.0,
        standby_interval: float = 5.0,
        client: redis.Redis | None = None,
        instance_id: str | None = None,
    ) -> None:
        """Initialize the leader election lease manager.

        Args:
            lease_key: Redis key representing the active leader lease.
            ttl_seconds: Expiration time in seconds for the leader lease.
            renewal_interval: Frequency in seconds to renew the lease when active leader.
            standby_interval: Polling sleep duration in seconds when in standby mode.
            client: Optional Redis client instance; defaults to shared get_redis_client().
            instance_id: Unique string identifying this scheduler replica.
        """
        self.lease_key = lease_key
        self.ttl_seconds = ttl_seconds
        self.renewal_interval = renewal_interval
        self.standby_interval = standby_interval
        self.client = client or get_redis_client()
        self.instance_id = instance_id or f"beat-replica-{uuid.uuid4()}"

    def acquire_lease(self) -> bool:
        """Attempt to acquire the leader lease atomically via SET NX EX.

        Returns:
            bool: True if leadership was acquired, False if another instance is leader.
        """
        # 1. Attempt atomic set-if-not-exists with expiration TTL
        result = self.client.set(
            self.lease_key,
            self.instance_id,
            nx=True,
            ex=self.ttl_seconds,
        )
        acquired = bool(result)
        if acquired:
            logger.info(
                "Acquired Celery Beat leader lease (key=%s, instance_id=%s, ttl=%ss)",
                self.lease_key,
                self.instance_id,
                self.ttl_seconds,
            )
        return acquired

    def renew_lease(self) -> bool:
        """Atomically renew the leader lease TTL using a Lua script.

        Returns:
            bool: True if renewal succeeded, False if lease was lost or expired.
        """
        # 2. Execute atomic Lua renewal verifying owner identity
        try:
            res = self.client.eval(
                _RENEW_LUA_SCRIPT,
                1,
                self.lease_key,
                self.instance_id,
                self.ttl_seconds,
            )
            success = bool(res)
            if success:
                logger.debug(
                    "Renewed Celery Beat leader lease (instance_id=%s, ttl=%ss)",
                    self.instance_id,
                    self.ttl_seconds,
                )
            else:
                logger.warning(
                    "Failed to renew Celery Beat leader lease; ownership lost (instance_id=%s)",
                    self.instance_id,
                )
            return success
        except Exception as exc:
            logger.error("Exception occurred while renewing leader lease: %s", exc)
            return False

    def release_lease(self) -> bool:
        """Atomically release the leader lease using a Lua script upon clean shutdown.

        Returns:
            bool: True if released cleanly, False if key expired or owned by another.
        """
        # 3. Execute atomic Lua deletion verifying owner identity
        try:
            res = self.client.eval(
                _RELEASE_LUA_SCRIPT,
                1,
                self.lease_key,
                self.instance_id,
            )
            released = bool(res)
            if released:
                logger.info(
                    "Released Celery Beat leader lease cleanly (instance_id=%s)",
                    self.instance_id,
                )
            return released
        except Exception as exc:
            logger.error("Exception occurred while releasing leader lease: %s", exc)
            return False


class LeaderElectedScheduler(Scheduler):
    """Custom Celery Beat Scheduler enforcing leader election.

    Only the active leader ticks crontab schedules and dispatches periodic tasks.
    Standby replicas sleep and poll for leader lease expiration to execute clean failover.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the leader-elected scheduler instance.

        Args:
            *args: Positional arguments forwarded to Celery's base Scheduler.
            **kwargs: Keyword arguments forwarded to Celery's base Scheduler.
        """
        # Extract optional leader election overrides
        leader_election: LeaderElection | None = kwargs.pop("leader_election", None)
        client: redis.Redis | None = kwargs.pop("redis_client", None)

        super().__init__(*args, **kwargs)

        # 1. Initialize leader election coordinator
        self.leader_election = leader_election or LeaderElection(client=client)
        self.is_leader: bool = False
        self.last_renewal: float = 0.0

    def tick(self, *args: Any, **kwargs: Any) -> float:
        """Execute one iteration of the scheduler tick loop.

        Returns:
            float: Delay in seconds to wait before the next tick iteration.
        """
        now = time.monotonic()

        # 2. Case A: Standby mode — attempt to acquire leadership
        if not self.is_leader:
            acquired = self.leader_election.acquire_lease()
            if acquired:
                self.is_leader = True
                self.last_renewal = now
                logger.info(
                    "Scheduler promoted to active leader (%s). Resuming schedule tick.",
                    self.leader_election.instance_id,
                )
                return float(super().tick(*args, **kwargs))

            # Not leader: sleep for standby interval without ticking schedules
            logger.debug(
                "Scheduler standby replica waiting for leader lease (%s)",
                self.leader_election.instance_id,
            )
            return self.leader_election.standby_interval

        # 3. Case B: Active leader mode — verify and renew lease periodically
        if now - self.last_renewal >= self.leader_election.renewal_interval:
            renewed = self.leader_election.renew_lease()
            if not renewed:
                self.is_leader = False
                logger.warning(
                    "Scheduler demoted from leader to standby (%s). Halting schedule tick.",
                    self.leader_election.instance_id,
                )
                return self.leader_election.standby_interval
            self.last_renewal = now

        # 4. Delegate to underlying Celery Scheduler to evaluate due tasks
        return float(super().tick(*args, **kwargs))

    def close(self) -> None:
        """Cleanly shut down scheduler and surrender leader lease if currently held."""
        # 5. Release leader lease if held
        if self.is_leader:
            self.leader_election.release_lease()
            self.is_leader = False

        super().close()
