import smtplib

import pytest

from veyraquant import emailer
from veyraquant.config import SmtpConfig


def make_config(to_email="to@example.com"):
    return SmtpConfig(
        host="smtp.test",
        port=465,
        user="user@example.com",
        password="secret",
        from_email="from@example.com",
        to_email=to_email,
    )


def test_build_message_is_multipart_alternative_plain_then_html():
    msg = emailer.build_message(make_config(), "Subject", "plain body", "<p>html</p>")
    assert msg.get_content_type() == "multipart/alternative"
    parts = msg.get_payload()
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]


def test_build_message_plain_only_when_no_html():
    msg = emailer.build_message(make_config(), "Subject", "plain body", None)
    assert msg.get_content_type() == "multipart/alternative"
    parts = msg.get_payload()
    assert [p.get_content_type() for p in parts] == ["text/plain"]


def test_build_message_has_date_and_message_id():
    msg = emailer.build_message(make_config(), "Subject", "body")
    assert msg["Date"]
    assert msg["Message-ID"] and msg["Message-ID"].startswith("<")


def test_build_message_encodes_unicode_subject():
    msg = emailer.build_message(make_config(), "量化简报", "body")
    assert "=?utf-8?" in msg.as_string()


def test_recipients_splits_comma_separated():
    assert emailer._recipients("a@x.com, b@y.com ,c@z.com") == [
        "a@x.com",
        "b@y.com",
        "c@z.com",
    ]


def test_send_email_requires_all_smtp_fields():
    cfg = SmtpConfig("h", 465, None, "pw", "f@x.com", "t@x.com")
    with pytest.raises(RuntimeError, match="Missing SMTP"):
        emailer.send_email(cfg, "s", "b")


class _FakeServer:
    def __init__(self, fail_times, sent):
        self.fail_times = fail_times
        self.sent = sent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        pass

    def send_message(self, msg, to_addrs=None):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise smtplib.SMTPServerDisconnected("boom")
        self.sent.append((msg["Subject"], to_addrs))


def test_send_email_retries_then_succeeds(monkeypatch):
    sent = []
    state = {"server": _FakeServer(fail_times=2, sent=sent)}
    monkeypatch.setattr(emailer.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        emailer.smtplib, "SMTP_SSL", lambda host, port, timeout=None: state["server"]
    )
    emailer.send_email(make_config(), "Subject", "body")
    assert sent == [("Subject", ["to@example.com"])]


def test_send_email_raises_after_exhausting_retries(monkeypatch):
    sent = []
    server = _FakeServer(fail_times=99, sent=sent)
    monkeypatch.setattr(emailer.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        emailer.smtplib, "SMTP_SSL", lambda host, port, timeout=None: server
    )
    with pytest.raises(RuntimeError, match="failed after"):
        emailer.send_email(make_config(), "Subject", "body")
    assert sent == []
