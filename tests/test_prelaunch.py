"""Pre-launch regression tests: security boundaries, production configuration, SMTP failure
handling, the deployable public/ directory and anonymisation of published files."""
import base64
import html
import json
import logging
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

PUBLIC = ROOT / "public"
GOOD = {"name": "Alex Example", "company": "Example Pty Ltd", "email": "alex@example.com",
        "enquiry_type": "demo", "message": "We would like to see a demonstration for three sites."}
PROD_ENV = {"SYSOPTY_FORM_SECRET": "x" * 48, "SYSOPTY_SMTP_HOST": "smtp.example.com",
            "SYSOPTY_MAIL_FROM": "website@example.com", "SYSOPTY_MAIL_TO": "sales@example.com",
            "SYSOPTY_SMTP_USERNAME": "website@example.com", "SYSOPTY_SMTP_PASSWORD": "not-a-real-password"}


def client(**config):
    cfg = {"FORM_SECRET": "test-secret"}
    cfg.update(config)
    return server.create_app(cfg).test_client()


@pytest.fixture
def aged(monkeypatch):
    def token(c, seconds=10):
        t = c.get("/api/form-token").get_json()["token"]
        real = time.time
        monkeypatch.setattr(server.time, "time", lambda: real() + seconds)
        return t
    return token


# ------------------------------------------------------------------ cross-site requests
@pytest.mark.parametrize("headers,code", [
    ({"Origin": "https://evil.example"}, 403),
    ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Origin": "http://localhost"}, 200),         # the test client's own host
    ({}, 200),                                     # non-browser clients send neither
])
def test_cross_site_posts_are_refused(aged, headers, code):
    sent = []
    c = client(SENDER=sent.append)
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)), headers=headers)
    assert r.status_code == code
    assert len(sent) == (1 if code == 200 else 0)


def test_legacy_honeypot_field_name_is_still_caught(aged):
    sent = []
    c = client(SENDER=sent.append)
    r = c.post("/api/enquiry", json=dict(GOOD, website="spam", form_token=aged(c)))
    assert r.status_code == 400 and r.get_json()["ok"] is False and sent == []


def test_every_failure_says_not_sent(aged):
    """No response other than a delivered message carries ok: true."""
    c = client()                                          # mail not configured
    for body in (dict(GOOD), dict(GOOD, hp_extra="x"), dict(GOOD, form_token="1.2"), {}):
        r = c.post("/api/enquiry", json=body)
        assert r.get_json()["ok"] is False and r.status_code >= 400
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))
    assert r.status_code == 503 and r.get_json()["ok"] is False


# ------------------------------------------------------------------ headers
def test_hsts_only_over_https():
    c = client()
    assert "Strict-Transport-Security" not in c.get("/").headers
    r = c.get("/", base_url="https://sysopty.com")
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_hsts_follows_the_proxy_when_trusted():
    c = client(TRUST_PROXY=True)
    r = c.get("/", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in r.headers


def test_site_csp_allows_no_third_parties():
    csp = client().get("/").headers["Content-Security-Policy"]
    assert "http" not in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp


def test_api_responses_are_not_cached():
    c = client()
    assert c.get("/api/form-token").headers["Cache-Control"] == "no-store"
    assert c.get("/healthz").headers["Cache-Control"] == "no-store"


# ------------------------------------------------------------------ errors
def test_api_errors_are_json_without_detail():
    c = client()
    r = c.get("/api/nope")
    assert r.status_code == 404 and r.get_json() == {"ok": False, "message": "Not Found"}
    r = c.put("/api/enquiry")
    assert r.status_code == 405 and r.get_json()["ok"] is False
    r = c.post("/api/enquiry", data="x" * 40_000, content_type="application/json")
    assert r.status_code == 413 and r.get_json()["ok"] is False


def test_unhandled_errors_do_not_leak_tracebacks():
    app = server.create_app({"FORM_SECRET": "t"})

    @app.get("/api/boom")
    def boom():
        raise RuntimeError(r"secret detail C:\internal\path")

    @app.get("/boom")
    def boom_page():
        raise RuntimeError(r"secret detail C:\internal\path")

    c = app.test_client()
    for url in ("/api/boom", "/boom"):
        r = c.get(url)
        body = r.get_data(as_text=True)
        assert r.status_code == 500
        assert "secret detail" not in body and "Traceback" not in body and "internal" not in body


@pytest.mark.parametrize("path", ["/.env", "/.git/config", "/index.html::$DATA", "/css/..%5c..%5cserver.py",
                                  "/server.py", "/wsgi.py", "/build/private_rules.json", "/README.md",
                                  "/%2e%2e/server.py", "/C:/Windows/win.ini"])
def test_private_paths_are_not_served(path):
    assert client().get(path).status_code == 404


# ------------------------------------------------------------------ production configuration
def test_production_problems():
    base = server.env_config()
    good = dict(base, FORM_SECRET="x" * 48, SMTP_HOST="smtp.example.com", MAIL_FROM="a@example.com",
                MAIL_TO="b@example.com", SMTP_SECURITY="starttls")
    assert server.production_problems(good) == []
    assert server.production_problems(dict(good, FORM_SECRET=""))
    assert server.production_problems(dict(good, FORM_SECRET="short"))
    assert server.production_problems(dict(good, SMTP_SECURITY="tls"))
    assert server.production_problems(dict(good, SMTP_SECURITY="none", SMTP_USERNAME="u", SMTP_PASSWORD="p"))
    assert server.production_problems(dict(good, MAIL_TO=""))
    assert server.production_problems(dict(good, SMTP_USERNAME="u", SMTP_PASSWORD=""))


def _import_wsgi(env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SYSOPTY_")}
    clean.update(env)
    return subprocess.run([sys.executable, "-c", "import wsgi; print(wsgi.app.name)"], cwd=ROOT, env=clean,
                          capture_output=True, text=True)


def test_wsgi_refuses_an_unsafe_configuration():
    r = _import_wsgi({})
    assert r.returncode != 0 and "SYSOPTY_FORM_SECRET" in r.stderr
    assert "x" * 10 not in r.stderr                             # never echoes configuration values


def test_wsgi_starts_with_a_safe_configuration():
    r = _import_wsgi(PROD_ENV)
    assert r.returncode == 0, r.stderr
    assert "not-a-real-password" not in r.stdout + r.stderr


# ------------------------------------------------------------------ SMTP delivery (mocked; nothing is sent)
class FakeSMTP:
    instances = []
    fail_with = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")
        if FakeSMTP.fail_with == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials for alex@example.com")

    def send_message(self, msg):
        self.calls.append("send")
        self.msg = msg


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_with = [], None
    monkeypatch.setattr(server.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(server.smtplib, "SMTP_SSL", lambda *a, **k: FakeSMTP(*a, **k))
    return FakeSMTP


def smtp_client(**extra):
    cfg = dict(SMTP_HOST="smtp.example.com", SMTP_PORT=587, MAIL_FROM="website@example.com",
               MAIL_TO="sales@example.com", SMTP_USERNAME="website@example.com", SMTP_PASSWORD="pw",
               SMTP_SECURITY="starttls")
    cfg.update(extra)
    return client(**cfg)


def test_smtp_success_uses_starttls_and_login(aged, fake_smtp):
    c = smtp_client()
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    s = fake_smtp.instances[0]
    assert s.calls == ["starttls", "login", "send"]
    assert s.msg["To"] == "sales@example.com" and s.msg["Reply-To"] == "alex@example.com"


def test_smtp_ssl_mode(aged, fake_smtp):
    c = smtp_client(SMTP_SECURITY="ssl", SMTP_PORT=465)
    assert c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c))).status_code == 200
    assert fake_smtp.instances[0].calls == ["login", "send"]


def test_smtp_auth_failure_is_reported_and_not_logged_in_detail(aged, fake_smtp, caplog):
    fake_smtp.fail_with = "auth"
    c = smtp_client()
    with caplog.at_level(logging.INFO, logger="sysopty_site"):
        r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))
    assert r.status_code == 502 and r.get_json()["ok"] is False
    logged = caplog.text
    assert "SMTPAuthenticationError" in logged
    assert "alex@example.com" not in logged and "demonstration for three sites" not in logged


def test_smtp_unavailable_is_reported(aged, monkeypatch):
    def refuse(*a, **k):
        raise ConnectionRefusedError("connection refused")
    monkeypatch.setattr(server.smtplib, "SMTP", refuse)
    c = smtp_client()
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))
    assert r.status_code == 502 and r.get_json()["ok"] is False


def test_credentials_are_never_sent_without_tls(aged, fake_smtp):
    c = smtp_client(SMTP_SECURITY="none")
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))
    assert r.status_code == 502 and fake_smtp.instances == []


def test_rate_table_drops_idle_addresses(monkeypatch, aged):
    monkeypatch.setattr(server, "RATE_TABLE_MAX", 3)
    sent = []
    app = server.create_app({"FORM_SECRET": "t", "SENDER": sent.append})
    c = app.test_client()
    token = aged(c, seconds=10)
    for i in range(6):
        c.post("/api/enquiry", json=dict(GOOD, form_token=token), environ_base={"REMOTE_ADDR": f"192.0.2.{i}"})
    real = server.time.time
    monkeypatch.setattr(server.time, "time", lambda: real() + server.RATE_WINDOW + 60)
    token = c.get("/api/form-token").get_json()["token"]
    monkeypatch.setattr(server.time, "time", lambda: real() + server.RATE_WINDOW + 80)
    for i in range(6, 9):
        assert c.post("/api/enquiry", json=dict(GOOD, form_token=token),
                      environ_base={"REMOTE_ADDR": f"192.0.2.{i}"}).status_code == 200


# ------------------------------------------------------------------ the deployable public/ directory
ALLOWED = {".html", ".css", ".js", ".webp", ".png", ".svg", ".ico", ".woff2", ".txt", ".xml"}


def public_files():
    return [p for p in PUBLIC.rglob("*") if p.is_file()]


# No document is published. A reviewed one would be exempted here by exact path only.
APPROVED_DOCUMENTS: set[str] = set()


def test_public_contains_only_web_assets():
    documents = [p for p in public_files() if p.relative_to(PUBLIC).as_posix() in APPROVED_DOCUMENTS]
    bad = [str(p.relative_to(PUBLIC)) for p in public_files()
           if (p.suffix.lower() not in ALLOWED or p.name.startswith(".")) and p not in documents]
    assert bad == []
    names = {p.name.lower() for p in public_files()}
    assert not names & {"private_rules.json", "server.py", "wsgi.py", ".env", "manifest.json"}
    assert not [p for p in public_files()
                if p.suffix.lower() in (".pdf", ".xlsx", ".dot", ".json") and p not in documents]
    assert max(p.stat().st_size for p in public_files()) < 8 * 1024 * 1024


def test_every_referenced_asset_exists():
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    refs = set(re.findall(r'(?:src|href|data-full)="(/[^"#?]*)"', page))
    for srcset in re.findall(r'(?:srcset|imagesrcset)="([^"]+)"', page):
        refs.update(part.split()[0] for part in srcset.split(","))
    css = (PUBLIC / "css" / "site.css").read_text(encoding="utf-8")
    refs.update("/" + u.lstrip("./") for u in re.findall(r'url\("?(\.\./[^")]+)"?\)', css))
    missing = sorted(r for r in refs if r != "/" and not (PUBLIC / r.lstrip("/")).is_file())
    assert missing == []


def test_gallery_has_one_preview_per_platform():
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    titles = re.findall(r'<figure class="shot-card">\s*<h3>([^<]+)</h3>', page)
    assert titles == ["Microsoft Azure", "Amazon AWS", "Google Cloud Platform", "VMware NSX", "VMware ESXi and vCenter"]
    # The previews are illustrative layouts, and the page says so beside them.
    assert "Reporting capabilities are in development." in page


# ------------------------------------------------------------------ anonymisation of published files
RULES = Path(os.environ.get("SYSOPTY_PRIVATE_RULES") or ROOT / "no-private-rules")


def decoded_variants(text: str):
    yield text
    yield html.unescape(text)
    yield urllib.parse.unquote(text)
    yield re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    for b64 in re.findall(r"[A-Za-z0-9+/]{40,}={0,2}", text)[:2000]:
        try:
            yield base64.b64decode(b64, validate=True).decode("utf-8", "ignore")
        except Exception:
            pass


# plotly.js v3.0.1 (MIT) exactly as inlined into the demo. Only a byte-identical copy of the
# library is skipped (minified identifiers in it collide with short blocked words); anything
# else in the demo page, including the site data and viewer code, is scanned.
PLOTLY_SHA256 = "a32e817bb121e9e89016ce4cee85ee3f1c66f6a6c95c4b53a5f488f77756d7a4"


def without_vendored_plotly(text: str) -> str:
    import hashlib
    text = text.replace("\r\n", "\n")                     # the file may have been written with CRLF
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.S):
        if hashlib.sha256(m.group(1).encode("utf-8")).hexdigest() == PLOTLY_SHA256:
            return text[:m.start()] + text[m.end():]
    return text


@pytest.mark.skipif(not RULES.exists(), reason="private rules are only on the asset build machine")
def test_published_files_contain_no_blocked_words():
    blocked = [w.lower() for w in json.loads(RULES.read_text(encoding="utf-8"))["blocklist"]]
    found = []
    for p in public_files():
        raw = p.read_bytes().decode("utf-8", "ignore") if p.suffix in (".html", ".css", ".js", ".svg", ".txt", ".xml") \
            else p.read_bytes().decode("latin-1")
        if p.name == "topology.html":
            raw = without_vendored_plotly(raw)
        binary = p.suffix not in (".html", ".css", ".js", ".svg", ".txt", ".xml")
        # In compressed image/font bytes, 3-4 letter words occur by chance; longer ones do not.
        words = [w for w in blocked if len(w) >= 5] if binary else blocked
        for variant in ([raw] if binary else decoded_variants(raw)):
            low = variant.lower()
            for w in words:
                if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                    found.append((str(p.relative_to(PUBLIC)), f"blocked word #{blocked.index(w)}"))
    assert sorted(set(found)) == []      # reports the word's index, never the word itself


def test_images_carry_no_metadata():
    for p in public_files():
        data = p.read_bytes()
        if p.suffix == ".webp":
            assert b"EXIF" not in data[:4096] and b"XMP " not in data[:4096], p.name
        if p.suffix in (".png", ".ico"):      # an .ico holds PNG images
            assert not any(chunk in data for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf")), p.name


# ------------------------------------------------------------------ release package
def test_release_package_holds_only_the_allowlist(tmp_path):
    import zipfile
    sys.path.insert(0, str(ROOT / "build"))
    import package_release
    archive = package_release.build(tmp_path)
    names = zipfile.ZipFile(archive).namelist()
    assert {"server.py", "wsgi.py", "requirements.txt", "public/index.html"} <= set(names)
    assert all(n in ("server.py", "wsgi.py", "requirements.txt") or n.startswith("public/") for n in names)
    assert not [n for n in names if "private_rules" in n or n.startswith(("build/", "tests/")) or n.endswith((".md", ".env"))]


# ------------------------------------------------------------------ behind the reverse proxy (real waitress)
def _serve(**proxy_options):
    import threading
    import waitress
    app = server.create_app({"FORM_SECRET": "t", "TRUST_PROXY": True})
    srv = waitress.create_server(app, host="127.0.0.1", port=0, threads=2, **proxy_options)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv, srv.effective_port


def _get(port, headers):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/", headers=headers)
    r = c.getresponse()
    r.read()
    return dict(r.getheaders())


PROXY_HEADERS = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.7", "X-Forwarded-Host": "sysopty.com"}
TRUSTED = dict(trusted_proxy="127.0.0.1", trusted_proxy_headers="x-forwarded-for x-forwarded-proto x-forwarded-host",
               clear_untrusted_proxy_headers=True)


def test_waitress_drops_proxy_headers_without_the_trusted_proxy_flags():
    pytest.importorskip("waitress")
    srv, port = _serve()
    try:
        assert "Strict-Transport-Security" not in _get(port, PROXY_HEADERS)
    finally:
        srv.close()


def test_waitress_with_the_documented_flags_sees_https():
    pytest.importorskip("waitress")
    srv, port = _serve(**TRUSTED)
    try:
        assert _get(port, PROXY_HEADERS).get("Strict-Transport-Security") == "max-age=31536000"
    finally:
        srv.close()


def test_deployment_files_use_the_trusted_proxy_flags():
    unit = (ROOT / "deploy" / "sysopty-site.service").read_text(encoding="utf-8")
    assert "--trusted-proxy=127.0.0.1" in unit and "x-forwarded-proto" in unit and "--clear-untrusted-proxy-headers" in unit
    assert not re.search(r"\\n", unit)                       # no literal "\n" escape sequences


# ------------------------------------------------------------------ service enquiry types (repositioning)
@pytest.mark.parametrize("value,subject", [
    ("assessment", "Request a network assessment"), ("proposal", "Request a service proposal"),
    ("samples", "Request sample documentation"), ("general", "General enquiry"),
    ("demo", "Request a network assessment"), ("pricing", "Request a service proposal"),   # cached older pages
])
def test_enquiry_types(aged, value, subject):
    sent = []
    c = client(SENDER=sent.append)
    r = c.post("/api/enquiry", json=dict(GOOD, enquiry_type=value, form_token=aged(c)))
    assert r.status_code == 200 and subject in sent[0]["Subject"]


def test_unknown_enquiry_type_is_rejected(aged):
    c = client(SENDER=[].append)
    r = c.post("/api/enquiry", json=dict(GOOD, enquiry_type="licence", form_token=aged(c)))
    assert r.status_code == 422 and "enquiry_type" in r.get_json()["errors"]


def test_optional_scope_fields(aged):
    sent = []
    c = client(SENDER=sent.append)
    r = c.post("/api/enquiry", json=dict(GOOD, sites="5", devices="about 120\r\nBcc: x@example.com",
                                         form_token=aged(c)))
    assert r.status_code == 200
    body = sent[0].get_content()
    assert "Number of sites: 5" in body and "Approximate number of devices: about 120 Bcc: x@example.com" in body
    assert sent[0]["Bcc"] is None
    r = c.post("/api/enquiry", json=dict(GOOD, form_token=aged(c)))            # both optional
    assert r.status_code == 200 and "Number of sites" not in sent[-1].get_content()
    r = c.post("/api/enquiry", json=dict(GOOD, sites="x" * 41, form_token=aged(c)))
    assert r.status_code == 422 and "sites" in r.get_json()["errors"]


def test_page_offers_the_service_enquiry_types_and_fields():
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    options = re.findall(r'<option value="([a-z]+)">', page)
    assert options == list(server.ENQUIRY_TYPES)
    assert 'name="sites"' in page and 'name="devices"' in page
    for target in re.findall(r'href="#([\w-]+)"', page):
        assert f'id="{target}"' in page, target                               # every anchor resolves


def test_reviewer_terms_come_from_the_account_and_a_private_file(tmp_path, monkeypatch):
    import json
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build"))
    import review_sample_pdf as r
    monkeypatch.delenv("SYSOPTY_REVIEW_TERMS", raising=False)
    monkeypatch.setattr(r.getpass, "getuser", lambda: "reviewer.one")
    assert r.reviewer_patterns() == {"account name": r"(?i)\breviewer\.one\b"}
    terms = tmp_path / "terms.json"
    terms.write_text(json.dumps({"account name": "(?i)example-reviewer"}), encoding="utf-8")
    monkeypatch.setenv("SYSOPTY_REVIEW_TERMS", str(terms))
    assert r.reviewer_patterns() == {"account name": "(?i)example-reviewer"}


def test_the_commercial_manifest_lists_exactly_the_tracked_files():
    listed = (ROOT / "build" / "commercial_manifest.txt").read_text(encoding="utf-8").splitlines()
    assert listed == sorted(set(listed)) and all((ROOT / f).is_file() for f in listed)
    tracked = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotepath=false", "ls-files"], capture_output=True, text=True)
    if tracked.returncode:
        pytest.skip("not a Git checkout")
    assert set(tracked.stdout.splitlines()) == set(listed)
    assert not [f for f in listed if re.search(r"(^|/)(private_rules|\.env$|review_terms)|\.(pem|key|pfx)$", f)]


def test_the_sample_review_recognises_a_carrier_name_without_naming_it():
    import review_sample_pdf as review
    assert review.carrier_words("Examplecarrier_portal export") == ["examplecarrier"]
    assert review.carrier_words("WAN provider service export") == []
