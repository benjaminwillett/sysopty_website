import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

GOOD = {
    "name": "Alex Example",
    "company": "Example Pty Ltd",
    "email": "alex@example.com",
    "enquiry_type": "demo",
    "message": "We would like to see a demonstration for three sites.",
    "website": "",
}


def make(sent=None, **config):
    cfg = {"FORM_SECRET": "test-secret"}
    if sent is not None:
        cfg["SENDER"] = sent.append
    cfg.update(config)
    return server.create_app(cfg).test_client()


def aged_token(client, monkeypatch, seconds=10):
    token = client.get("/api/form-token").get_json()["token"]
    real = time.time
    monkeypatch.setattr(server.time, "time", lambda: real() + seconds)
    return token


def test_valid_enquiry_is_delivered(monkeypatch):
    sent = []
    c = make(sent)
    body = dict(GOOD, form_token=aged_token(c, monkeypatch))
    r = c.post("/api/enquiry", json=body)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(sent) == 1
    msg = sent[0]
    assert msg["Reply-To"] == "alex@example.com"
    # Service repositioning: the legacy "demo" type sent by a cached
    # page is delivered as the current "Request a network assessment" type.
    assert "Request a network assessment" in msg["Subject"]
    assert "three sites" in msg.get_content()


def test_unconfigured_mail_says_so_and_sends_nothing(monkeypatch):
    c = make(None, SMTP_HOST="", MAIL_FROM="", MAIL_TO="")
    body = dict(GOOD, form_token=aged_token(c, monkeypatch))
    r = c.post("/api/enquiry", json=body)
    assert r.status_code == 503
    assert r.get_json()["ok"] is False


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("company", ""), ("email", "not-an-email"), ("email", "a@b"),
    ("enquiry_type", "other"), ("message", "short"), ("message", "x" * 5001), ("name", "x" * 101),
])
def test_invalid_fields_are_rejected(monkeypatch, field, value):
    sent = []
    c = make(sent)
    body = dict(GOOD, form_token=aged_token(c, monkeypatch))
    body[field] = value
    r = c.post("/api/enquiry", json=body)
    assert r.status_code == 422
    assert field in r.get_json()["errors"]
    assert sent == []


# These two originally asserted a 200 "success" for dropped submissions. Pre-launch audit
# The site must never claim an enquiry was sent when it was not, so
# dropped submissions now fail visibly. Nothing is sent in either case, as before.
def test_honeypot_is_dropped_without_claiming_success(monkeypatch):
    sent = []
    c = make(sent)
    body = dict(GOOD, hp_extra="http://spam.example", form_token=aged_token(c, monkeypatch))
    r = c.post("/api/enquiry", json=body)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert sent == []


def test_instant_submission_is_dropped_without_claiming_success():
    sent = []
    c = make(sent)
    token = c.get("/api/form-token").get_json()["token"]
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=token))
    assert r.status_code == 400 and r.get_json() == {
        "ok": False, "code": "too_fast", "message": "Please wait a few seconds and send your enquiry again."}
    assert sent == []


def test_forged_or_missing_token_is_rejected():
    sent = []
    c = make(sent)
    assert c.post("/api/enquiry", json=dict(GOOD, form_token="123.abc")).status_code == 400
    assert c.post("/api/enquiry", json=GOOD).status_code == 400
    assert sent == []


def test_header_injection_is_stripped(monkeypatch):
    sent = []
    c = make(sent)
    body = dict(GOOD, company="Evil\r\nBcc: victim@example.com", form_token=aged_token(c, monkeypatch))
    assert c.post("/api/enquiry", json=body).status_code == 200
    assert "Bcc" not in str(sent[0]["Subject"]).split("\n")[0] or "\n" not in str(sent[0]["Subject"])
    assert sent[0]["Bcc"] is None


def test_rate_limit(monkeypatch):
    sent = []
    c = make(sent)
    token = aged_token(c, monkeypatch)
    codes = [c.post("/api/enquiry", json=dict(GOOD, form_token=token)).status_code for _ in range(server.RATE_LIMIT + 1)]
    assert codes[-1] == 429
    assert len(sent) == server.RATE_LIMIT


def test_only_public_files_are_served():
    c = make([])
    assert c.get("/").status_code == 200
    assert c.get("/css/site.css").status_code == 200
    assert c.get("/server.py").status_code == 404
    assert c.get("/../server.py").status_code == 404
    assert c.get("/%2e%2e/server.py").status_code == 404
    assert c.get("/index.html%00").status_code == 404
    assert c.get("/img/og-image.png%00.html").status_code == 404


def test_security_headers():
    c = make([])
    r = c.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
