"""The polled mailbox is a real person's inbox.

Only mail from someone this system actually emailed - or from the mail system
reporting on that mail - may be read, classified or acted on. Everything else
must be left untouched AND unread.
"""

import pytest

from leadforge.communication.inbox import IMAPInboxMonitor


@pytest.fixture
def monitor():
    return IMAPInboxMonitor()


def _raw(sender: str) -> bytes:
    return (
        f"From: Someone <{sender}>\r\n"
        "To: orvionstudio.co@gmail.com\r\n"
        "Subject: re: quick question\r\n\r\n"
        "Sounds interesting, tell me more.\r\n"
    ).encode()


def test_sender_is_parsed_from_display_name_form(monitor):
    assert monitor._sender_of(_raw("owner@acme.example")) == "owner@acme.example"


def test_unparseable_message_yields_no_sender(monitor):
    assert monitor._sender_of(b"\xff\xfe not a message") == ""


def test_known_recipient_is_relevant(monitor):
    assert monitor._is_relevant("owner@acme.example", {"owner@acme.example"}) is True


def test_stranger_is_not_relevant(monitor):
    """A personal email from someone we never contacted must be ignored."""
    assert monitor._is_relevant("mum@family.example", {"owner@acme.example"}) is False


def test_empty_sender_is_not_relevant(monitor):
    assert monitor._is_relevant("", {"owner@acme.example"}) is False


@pytest.mark.parametrize("sender", [
    "mailer-daemon@googlemail.com",
    "postmaster@outlook.com",
    "mail-delivery-subsystem@google.com",
])
def test_bounce_notifiers_are_relevant_even_though_unknown(monitor, sender):
    """Bounces come from the mail system, not the prospect. If these were filtered
    out the circuit breaker in ramp.py could never see a real bounce."""
    assert monitor._is_relevant(sender, set()) is True


def test_fetch_uses_peek_so_foreign_mail_is_never_marked_read():
    """A plain (RFC822) fetch sets \\Seen server-side, which would mark the
    owner's personal mail as read before we decide to skip it."""
    import inspect
    src = inspect.getsource(IMAPInboxMonitor.poll_inbox)
    assert "BODY.PEEK[]" in src
    assert "(RFC822)" not in src
