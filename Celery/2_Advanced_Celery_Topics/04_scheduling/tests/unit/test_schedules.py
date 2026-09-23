"""Unit tests for Celery Beat crontab schedules, timezone evaluation, and DST transitions.

Validates that financial cut-off evaluations adhere to America/New_York legal banking
hours across Eastern Daylight Time (EDT) and Eastern Standard Time (EST) shifts, and
confirms weekend exclusion rules.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone

import pytest
from celery.schedules import crontab

from services.worker.celery_app import celery_app


@pytest.mark.unit
def test_beat_schedule_configuration() -> None:
    """Verify Celery Beat application configuration, custom scheduler, and schedule registry."""
    conf = celery_app.conf
    assert conf.timezone == "America/New_York"
    assert conf.enable_utc is True
    assert conf.beat_scheduler == "services.worker.beat_lock.LeaderElectedScheduler"

    schedule = conf.beat_schedule
    assert "eod-banking-cutoff" in schedule
    assert "hourly-gap-detector" in schedule
    assert "nightly-idempotency-cleanup" in schedule

    # Verify task assignments and AMQP routing
    eod_entry = schedule["eod-banking-cutoff"]
    assert eod_entry["task"] == "services.worker.tasks.reconciliation.reconcile_eod_cutoff"
    assert eod_entry["options"]["queue"] == "reconciliation"
    assert eod_entry["options"]["routing_key"] == "scheduling.reconciliation"

    gap_entry = schedule["hourly-gap-detector"]
    assert gap_entry["task"] == "services.worker.tasks.backfill.detect_and_backfill_gaps"
    assert gap_entry["options"]["queue"] == "reconciliation"
    assert gap_entry["options"]["routing_key"] == "scheduling.reconciliation"

    clean_entry = schedule["nightly-idempotency-cleanup"]
    assert clean_entry["task"] == "services.worker.tasks.cleanup.purge_expired_records"
    assert clean_entry["options"]["queue"] == "cleanup"
    assert clean_entry["options"]["routing_key"] == "scheduling.cleanup"


@pytest.mark.unit
def test_timezone_daylight_saving_summer_edt() -> None:
    """Verify 17:00 New York cut-off during EDT (Summer) translates to 21:00 UTC (UTC-4)."""
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Wednesday July 15 2026, 17:00 EDT
    summer_ny = datetime(2026, 7, 15, 17, 0, 0, tzinfo=ny_tz)
    summer_utc = summer_ny.astimezone(timezone.utc)

    # 1. Assert UTC offset is -4 hours during Daylight Saving Time
    assert summer_ny.utcoffset() == timedelta(hours=-4)
    assert summer_utc.hour == 21
    assert summer_utc.day == 15

    # 2. Evaluate crontab is_due at 17:00 EDT
    cron = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: summer_ny,
    )
    last_run = summer_ny - timedelta(days=1)
    status = cron.is_due(last_run)
    assert status.is_due is True


@pytest.mark.unit
def test_timezone_standard_winter_est() -> None:
    """Verify 17:00 New York cut-off during EST (Winter) translates to 22:00 UTC (UTC-5)."""
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Thursday January 15 2026, 17:00 EST
    winter_ny = datetime(2026, 1, 15, 17, 0, 0, tzinfo=ny_tz)
    winter_utc = winter_ny.astimezone(timezone.utc)

    # 1. Assert UTC offset is -5 hours during Standard Time
    assert winter_ny.utcoffset() == timedelta(hours=-5)
    assert winter_utc.hour == 22
    assert winter_utc.day == 15

    # 2. Evaluate crontab is_due at 17:00 EST
    cron = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: winter_ny,
    )
    last_run = winter_ny - timedelta(days=1)
    status = cron.is_due(last_run)
    assert status.is_due is True


@pytest.mark.unit
def test_weekend_exclusion_filtering() -> None:
    """Verify crontab(mon-fri) excludes Saturday and Sunday from cut-off evaluation."""
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Friday July 17 2026 17:00 EDT (Business Day)
    friday_1700 = datetime(2026, 7, 17, 17, 0, 0, tzinfo=ny_tz)
    # Saturday July 18 2026 17:00 EDT (Weekend)
    saturday_1700 = datetime(2026, 7, 18, 17, 0, 0, tzinfo=ny_tz)
    # Sunday July 19 2026 17:00 EDT (Weekend)
    sunday_1700 = datetime(2026, 7, 19, 17, 0, 0, tzinfo=ny_tz)
    # Monday July 20 2026 17:00 EDT (Business Day)
    monday_1700 = datetime(2026, 7, 20, 17, 0, 0, tzinfo=ny_tz)

    # 1. Friday 17:00 should be due
    cron_fri = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: friday_1700,
    )
    assert cron_fri.is_due(friday_1700 - timedelta(days=1)).is_due is True

    # 2. Saturday 17:00 should NOT be due
    cron_sat = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: saturday_1700,
    )
    assert cron_sat.is_due(friday_1700).is_due is False

    # 3. Sunday 17:00 should NOT be due
    cron_sun = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: sunday_1700,
    )
    assert cron_sun.is_due(friday_1700).is_due is False

    # 4. Monday 17:00 should be due
    cron_mon = crontab(
        hour=17,
        minute=0,
        day_of_week="mon-fri",
        app=celery_app,
        nowfun=lambda: monday_1700,
    )
    assert cron_mon.is_due(friday_1700).is_due is True


@pytest.mark.unit
def test_hourly_gap_detector_crontab() -> None:
    """Verify crontab(minute=30) triggers at minute 30 and sleeps at other minutes."""
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Due at 14:30
    dt_due = datetime(2026, 9, 23, 14, 30, 0, tzinfo=ny_tz)
    cron_due = crontab(minute=30, app=celery_app, nowfun=lambda: dt_due)
    last_run = datetime(2026, 9, 23, 13, 30, 0, tzinfo=ny_tz)
    assert cron_due.is_due(last_run).is_due is True

    # Not due at 14:15
    dt_not_due = datetime(2026, 9, 23, 14, 15, 0, tzinfo=ny_tz)
    cron_not_due = crontab(minute=30, app=celery_app, nowfun=lambda: dt_not_due)
    assert cron_not_due.is_due(last_run).is_due is False


@pytest.mark.unit
def test_nightly_cleanup_crontab() -> None:
    """Verify crontab(hour=2, minute=0) triggers at 02:00."""
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Due at 02:00
    dt_due = datetime(2026, 9, 23, 2, 0, 0, tzinfo=ny_tz)
    cron_due = crontab(hour=2, minute=0, app=celery_app, nowfun=lambda: dt_due)
    last_run = datetime(2026, 9, 22, 2, 0, 0, tzinfo=ny_tz)
    assert cron_due.is_due(last_run).is_due is True

    # Not due at 03:00 if already run today at 02:00
    dt_not_due = datetime(2026, 9, 23, 3, 0, 0, tzinfo=ny_tz)
    cron_not_due = crontab(hour=2, minute=0, app=celery_app, nowfun=lambda: dt_not_due)
    assert cron_not_due.is_due(dt_due).is_due is False
