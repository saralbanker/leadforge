"""Tests for the send ramp and bounce circuit breaker."""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from leadforge.outreach.ramp import (
    bounce_rate,
    delivery_allowance,
    parse_ramp_schedule,
    ramp_ceiling,
)


class FakeSettings:
    def __init__(self, **vals):
        self.vals = vals

    def get_int(self, key, default=0):
        return int(self.vals.get(key, default))

    def get_float(self, key, default=0.0):
        return float(self.vals.get(key, default))

    def get_str(self, key, default=""):
        return str(self.vals.get(key, default))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE email_drafts (id TEXT PRIMARY KEY, recipient_email TEXT, "
        "status TEXT, sent_at TEXT, opportunity_id TEXT)"
    )
    c.execute("CREATE TABLE opportunities (id TEXT PRIMARY KEY, business_id TEXT)")
    c.execute("CREATE TABLE communication_threads (id TEXT PRIMARY KEY, business_id TEXT)")
    c.execute(
        "CREATE TABLE communication_messages (id TEXT PRIMARY KEY, thread_id TEXT, "
        "classification_label TEXT)"
    )
    yield c
    c.close()


def _bounced_business(c, draft_id: str, notices: int) -> None:
    """Links one sent draft to a business that produced `notices` bounce mails."""
    biz, opp, thread = f"b-{draft_id}", f"o-{draft_id}", f"t-{draft_id}"
    c.execute("INSERT INTO opportunities VALUES (?,?)", (opp, biz))
    c.execute("INSERT INTO communication_threads VALUES (?,?)", (thread, biz))
    c.execute("UPDATE email_drafts SET opportunity_id=? WHERE id=?", (opp, draft_id))
    for i in range(notices):
        c.execute("INSERT INTO communication_messages VALUES (?,?,'BOUNCE')",
                  (f"m-{draft_id}-{i}", thread))
    c.commit()


def _send(c, n, status="SENT", when="2026-08-01", prefix="d"):
    for i in range(n):
        c.execute(
            "INSERT INTO email_drafts (id, recipient_email, status, sent_at) VALUES (?,?,?,?)",
            (f"{prefix}{i}", f"{prefix}{i}@example.com", status, f"{when}T10:00:00Z"),
        )
    c.commit()


def test_parse_ramp_schedule_sorts_and_drops_junk():
    assert parse_ramp_schedule("8:20,1:10,junk,,15:x") == [(1, 10), (8, 20)]


def test_ramp_starts_at_first_step_with_no_history(conn):
    # An untouched system must start at the bottom of the ramp, not the top.
    assert ramp_ceiling(conn, "1:10,8:20,15:30") == 10


@pytest.mark.parametrize("day_offset,expected", [(0, 10), (6, 10), (7, 20), (20, 30), (99, 30)])
def test_ramp_steps_up_with_days_since_first_send(conn, day_offset, expected):
    first = date(2026, 8, 1)
    _send(conn, 1, when=first.isoformat())
    got = ramp_ceiling(conn, "1:10,8:20,15:30", today=first + timedelta(days=day_offset))
    assert got == expected


def test_bounce_rate_counts_failed_sends(conn):
    _send(conn, 9, status="SENT", prefix="s")
    _send(conn, 1, status="FAILED", prefix="f")
    rate, bad, total = bounce_rate(conn, 50)
    assert (bad, total) == (1, 10)
    assert rate == pytest.approx(0.1)


def test_breaker_opens_above_threshold(conn):
    _send(conn, 8, status="SENT", prefix="s")
    _send(conn, 2, status="FAILED", prefix="f")
    allowance, reason = delivery_allowance(
        conn, FakeSettings(**{"outreach.daily_send_limit": 40, "outreach.bounce_threshold": 0.08})
    )
    assert allowance == 0
    assert "circuit breaker open" in reason


def test_breaker_ignores_tiny_samples(conn):
    # 1 bounce out of 2 is noise; halting on it would stall the system forever.
    _send(conn, 1, status="SENT", prefix="s")
    _send(conn, 1, status="FAILED", prefix="f")
    allowance, reason = delivery_allowance(conn, FakeSettings(**{"outreach.daily_send_limit": 40}))
    assert allowance > 0
    assert "circuit breaker" not in reason


def _utc_today() -> date:
    """The production code counts a day in UTC. A test using the local date is
    wrong for the ~5.5 hours after local midnight in IST, which is how this
    first failed."""
    return datetime.now(timezone.utc).date()


def test_allowance_is_bounded_by_the_lower_of_ramp_and_config(conn):
    today = _utc_today()
    _send(conn, 1, when=today.isoformat(), prefix="s")  # day 1 -> ramp ceiling 10
    allowance, _ = delivery_allowance(
        conn,
        FakeSettings(**{"outreach.daily_send_limit": 40, "outreach.ramp_schedule": "1:10,8:20"}),
    )
    assert allowance == 9  # ceiling 10 minus the one already sent today


def test_configured_limit_can_be_stricter_than_the_ramp(conn):
    today = _utc_today()
    _send(conn, 1, when=today.isoformat(), prefix="s")
    allowance, _ = delivery_allowance(
        conn,
        FakeSettings(**{"outreach.daily_send_limit": 3, "outreach.ramp_schedule": "1:10,8:20"}),
    )
    assert allowance == 2


def test_repeated_bounce_notices_for_one_address_count_once(conn):
    """A single dead address can generate dozens of mailer-daemon replies - the
    live inbox held 25 for one business. Counting each would peg the rate far
    above 100% and wedge the breaker shut permanently."""
    _send(conn, 20, status="SENT", prefix="s")
    _bounced_business(conn, "s0", notices=25)
    rate, bad, total = bounce_rate(conn, 50)
    assert (bad, total) == (1, 20)
    assert rate == pytest.approx(0.05)


def test_draft_both_failed_and_bounced_is_not_double_counted(conn):
    _send(conn, 9, status="SENT", prefix="s")
    _send(conn, 1, status="FAILED", prefix="f")
    _bounced_business(conn, "f0", notices=3)
    rate, bad, total = bounce_rate(conn, 50)
    assert (bad, total) == (1, 10)


def test_historical_bounces_outside_the_window_are_excluded(conn):
    """Old bounces must not hold the breaker open once fresh sends replace them."""
    _send(conn, 1, status="SENT", when="2026-01-01", prefix="old")
    _bounced_business(conn, "old0", notices=25)
    _send(conn, 30, status="SENT", when="2026-08-01", prefix="new")
    rate, bad, total = bounce_rate(conn, 10)  # window excludes the old send
    assert bad == 0
    assert rate == 0.0
