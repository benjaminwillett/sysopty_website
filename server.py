"""Sysopty marketing site: static files plus the enquiry endpoint.

Only the public/ directory is served. Enquiries are delivered by SMTP using
settings from the environment (see .env.example). When SMTP is not configured
the endpoint answers 503 and the page says the message was not sent. The
endpoint never reports success for a message it did not hand to the mail server.

Production runs through wsgi.py (it refuses to start with an unsafe configuration);
`python server.py` is the local development server only.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from collections import deque
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

PUBLIC = Path(__file__).resolve().parent / "public"
# The one downloadable document: the reviewed synthetic sample report.
SAMPLE_REPORT = "samples/Sysopty_Sample_Network_As-Built_Report.pdf"
log = logging.getLogger("sysopty_site")

ENQUIRY_TYPES = {
    "assessment": "Request a network assessment",
    "proposal": "Request a service proposal",
    "samples": "Request sample documentation",
    "general": "General enquiry",
}
# Values sent by pages from before the service repositioning (a browser may still have one
# cached); they are accepted and delivered under the corresponding current type.
LEGACY_ENQUIRY_TYPES = {"demo": "assessment", "pricing": "proposal"}
OPTIONAL_FIELDS = {"sites": "Number of sites", "devices": "Approximate number of devices"}
EMAIL_RE = re.compile(
    r"^[^\s@<>()\[\],;:\"]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SMTP_SECURITY = ("starttls", "ssl", "none")

MIN_FILL_SECONDS = 3          # faster than this is a bot (or a person who must wait a moment)
MAX_TOKEN_AGE = 2 * 60 * 60   # a form left open longer must fetch a new token
RATE_LIMIT = 5                # enquiries per address per window
RATE_WINDOW = 60 * 60
RATE_TABLE_MAX = 10_000       # addresses remembered before old ones are dropped

# The one third party: the shared Microsoft Bookings page, framed by the "Book a call" dialog.
BOOKINGS_ORIGIN = "https://bookings.cloud.microsoft"
SITE_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "font-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    f"frame-src 'self' {BOOKINGS_ORIGIN}; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)
# The topology demo is a self-contained Plotly page with inline scripts. `sandbox`
# gives it an opaque origin even when opened directly, so its scripts can never act
# as the site; it may only be framed by the site itself.
DEMO_CSP = (
    "sandbox allow-scripts; "
    "default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def env_config() -> dict:
    return dict(
        FORM_SECRET=os.environ.get("SYSOPTY_FORM_SECRET", ""),
        SMTP_HOST=os.environ.get("SYSOPTY_SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SYSOPTY_SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("SYSOPTY_SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SYSOPTY_SMTP_PASSWORD", ""),
        SMTP_SECURITY=os.environ.get("SYSOPTY_SMTP_SECURITY", "starttls").strip().lower(),
        MAIL_FROM=os.environ.get("SYSOPTY_MAIL_FROM", ""),
        MAIL_TO=os.environ.get("SYSOPTY_MAIL_TO", ""),
        HSTS_MAX_AGE=int(os.environ.get("SYSOPTY_HSTS_MAX_AGE", "31536000")),
        TRUST_PROXY=os.environ.get("SYSOPTY_TRUST_PROXY") == "1",
    )


def production_problems(config: dict) -> list[str]:
    """What stops this configuration being used in production (empty when it is fine)."""
    problems = []
    if len(config.get("FORM_SECRET") or "") < 32:
        problems.append("SYSOPTY_FORM_SECRET must be set to a random value of at least 32 characters "
                        "(it signs form tokens and must be the same for every worker)")
    if config.get("SMTP_SECURITY") not in SMTP_SECURITY:
        problems.append(f"SYSOPTY_SMTP_SECURITY must be one of {', '.join(SMTP_SECURITY)}")
    if config.get("SMTP_SECURITY") == "none" and config.get("SMTP_USERNAME"):
        problems.append("SYSOPTY_SMTP_SECURITY=none would send the SMTP password unencrypted")
    if config.get("SMTP_HOST") and not (config.get("MAIL_FROM") and config.get("MAIL_TO")):
        problems.append("SYSOPTY_MAIL_FROM and SYSOPTY_MAIL_TO are required when SYSOPTY_SMTP_HOST is set")
    if config.get("SMTP_USERNAME") and not config.get("SMTP_PASSWORD"):
        problems.append("SYSOPTY_SMTP_PASSWORD is empty but SYSOPTY_SMTP_USERNAME is set")
    return problems


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(env_config())
    app.config.update(MAX_CONTENT_LENGTH=32 * 1024, SENDER=None)  # SENDER: tests replace delivery
    if config:
        app.config.update(config)
    if not app.config["FORM_SECRET"]:
        # Development only: tokens stop validating on restart and differ between workers.
        app.config["FORM_SECRET"] = secrets.token_hex(32)
    if app.config["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    hits: dict[str, deque] = {}
    hits_lock = threading.Lock()

    def rate_limited(addr: str) -> bool:
        now = time.time()
        with hits_lock:
            if len(hits) >= RATE_TABLE_MAX:               # drop addresses with nothing in the window
                for key in [k for k, q in hits.items() if not q or now - q[-1] > RATE_WINDOW]:
                    del hits[key]
            q = hits.setdefault(addr, deque())
            while q and now - q[0] > RATE_WINDOW:
                q.popleft()
            if len(q) >= RATE_LIMIT:
                return True
            q.append(now)
            return False

    def sign(ts: str) -> str:
        return hmac.new(app.config["FORM_SECRET"].encode(), ts.encode(), hashlib.sha256).hexdigest()

    def token_problem(token: str) -> str:
        ts, _, sig = (token or "").partition(".")
        if not ts.isdigit() or not hmac.compare_digest(sig, sign(ts)):
            return "invalid"
        age = time.time() - int(ts)
        if age < MIN_FILL_SECONDS:
            return "too_fast"
        if age > MAX_TOKEN_AGE:
            return "expired"
        return ""

    def mail_configured() -> bool:
        c = app.config
        return bool(c["SENDER"] or (c["SMTP_HOST"] and c["MAIL_FROM"] and c["MAIL_TO"]))

    def deliver(msg: EmailMessage) -> None:
        c = app.config
        if c["SENDER"]:
            c["SENDER"](msg)
            return
        if c["SMTP_SECURITY"] not in SMTP_SECURITY:
            raise RuntimeError("unknown SMTP security mode")
        if c["SMTP_SECURITY"] == "none" and c["SMTP_USERNAME"]:
            raise RuntimeError("refusing to send SMTP credentials without TLS")
        context = ssl.create_default_context()
        if c["SMTP_SECURITY"] == "ssl":
            server = smtplib.SMTP_SSL(c["SMTP_HOST"], c["SMTP_PORT"], timeout=15, context=context)
        else:
            server = smtplib.SMTP(c["SMTP_HOST"], c["SMTP_PORT"], timeout=15)
        with server:
            if c["SMTP_SECURITY"] == "starttls":
                server.starttls(context=context)
            if c["SMTP_USERNAME"]:
                server.login(c["SMTP_USERNAME"], c["SMTP_PASSWORD"])
            server.send_message(msg)

    def cross_site() -> bool:
        """A browser request sent from another site (Origin, or Fetch Metadata when Origin is absent)."""
        origin = request.headers.get("Origin")
        if origin:
            return urlsplit(origin).netloc.lower() != request.host.lower()
        return request.headers.get("Sec-Fetch-Site", "") == "cross-site"

    @app.after_request
    def security_headers(resp):
        demo = request.path.startswith("/demo/")
        resp.headers["Content-Security-Policy"] = DEMO_CSP if demo else SITE_CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if not demo:
            resp.headers["X-Frame-Options"] = "DENY"
        if request.is_secure and app.config["HSTS_MAX_AGE"] > 0:
            resp.headers["Strict-Transport-Security"] = f"max-age={app.config['HSTS_MAX_AGE']}"
        if request.path.startswith("/api/") or request.path == "/healthz":
            resp.headers["Cache-Control"] = "no-store"
        elif request.path.startswith(("/img/", "/css/", "/js/", "/fonts/", "/demo/")):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        elif request.path == "/" + SAMPLE_REPORT and resp.status_code == 200:
            resp.headers["Content-Disposition"] = f'attachment; filename="{SAMPLE_REPORT.rsplit("/", 1)[-1]}"'
            resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        # Plain, fixed messages: never a traceback, path or framework detail.
        if request.path.startswith("/api/"):
            return jsonify(ok=False, message=exc.name), exc.code
        return (f"<!doctype html><meta charset=utf-8><title>{exc.code} {exc.name}</title>"
                f"<h1>{exc.name}</h1><p><a href=\"/\">Sysopty home</a></p>"), exc.code

    @app.errorhandler(Exception)
    def server_error(exc: Exception):
        log.exception("unhandled error on %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify(ok=False, message="Something went wrong. Please try again later."), 500
        return "<!doctype html><meta charset=utf-8><title>Server error</title><h1>Something went wrong</h1>", 500

    @app.get("/")
    def index():
        return send_from_directory(PUBLIC, "index.html")

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", mail_configured=mail_configured())

    @app.get("/api/form-token")
    def form_token():
        ts = str(int(time.time()))
        return jsonify(token=f"{ts}.{sign(ts)}")

    @app.post("/api/enquiry")
    def enquiry():
        if cross_site():
            return jsonify(ok=False, message="Enquiries must be sent from the Sysopty website."), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = request.form.to_dict()

        def field(name: str) -> str:
            value = data.get(name, "")
            return CONTROL_RE.sub("", value).strip() if isinstance(value, str) else ""

        # Spam checks: nothing is sent and the response never claims otherwise.
        if field("hp_extra") or field("website"):
            return jsonify(ok=False, message="Your enquiry could not be sent."), 400
        problem = token_problem(field("form_token"))
        if problem == "too_fast":
            return jsonify(ok=False, code="too_fast",
                           message="Please wait a few seconds and send your enquiry again."), 400
        if problem:
            return jsonify(ok=False, code="expired",
                           message="This form has expired. Please reload the page and try again."), 400

        # Single-line fields end up in mail headers, so line breaks are collapsed.
        values = {k: " ".join(field(k).split()) for k in ("name", "company", "email", "enquiry_type", *OPTIONAL_FIELDS)}
        values["enquiry_type"] = LEGACY_ENQUIRY_TYPES.get(values["enquiry_type"], values["enquiry_type"])
        values["message"] = field("message")
        errors = {}
        for key in OPTIONAL_FIELDS:                      # optional, short, single line
            if len(values[key]) > 40:
                errors[key] = "Use 40 characters or fewer."
        if not values["name"]:
            errors["name"] = "Enter your name."
        elif len(values["name"]) > 100:
            errors["name"] = "Use 100 characters or fewer."
        if not values["company"]:
            errors["company"] = "Enter your organisation name."
        elif len(values["company"]) > 150:
            errors["company"] = "Use 150 characters or fewer."
        if not values["email"]:
            errors["email"] = "Enter your business email address."
        elif len(values["email"]) > 254 or not EMAIL_RE.match(values["email"]):
            errors["email"] = "Enter a valid email address, like name@company.com."
        if values["enquiry_type"] not in ENQUIRY_TYPES:
            errors["enquiry_type"] = "Choose an enquiry type."
        if len(values["message"]) < 10:
            errors["message"] = "Add a little more detail (at least 10 characters)."
        elif len(values["message"]) > 5000:
            errors["message"] = "Keep the message under 5,000 characters."
        if errors:
            return jsonify(ok=False, errors=errors), 422

        if not mail_configured():
            return jsonify(ok=False, message="Enquiry delivery is not configured."), 503
        if rate_limited(request.remote_addr or "unknown"):
            return jsonify(ok=False, message="Too many enquiries."), 429

        kind = ENQUIRY_TYPES[values["enquiry_type"]]
        msg = EmailMessage()
        msg["Subject"] = f"Sysopty enquiry: {kind} from {values['company']}"[:200]
        msg["From"] = app.config["MAIL_FROM"] or "website@example.invalid"   # tests only: SENDER set
        msg["To"] = app.config["MAIL_TO"] or "enquiries@example.invalid"
        msg["Reply-To"] = values["email"]
        msg.set_content(                                   # plain text: markup in fields is inert
            f"Enquiry type: {kind}\n"
            f"Name: {values['name']}\n"
            f"Organisation: {values['company']}\n"
            f"Email: {values['email']}\n"
            + "".join(f"{label}: {values[key]}\n" for key, label in OPTIONAL_FIELDS.items() if values[key])
            + f"\n{values['message']}\n"
        )
        try:
            deliver(msg)
        except Exception as exc:  # noqa: BLE001 - any delivery failure is reported the same way
            # The exception type only: no message, so no addresses or server replies in the log.
            log.error("enquiry delivery failed: %s", type(exc).__name__)
            return jsonify(ok=False, message="Your enquiry could not be sent. Please try again later."), 502
        log.info("enquiry delivered (%s)", values["enquiry_type"])
        return jsonify(ok=True)

    @app.get("/<path:path>")
    def static_files(path: str):
        parts = path.replace("\\", "/").split("/")
        if any(p.startswith(".") or ":" in p for p in parts):  # dotfiles, NTFS streams, drive letters
            abort(404)
        if "\x00" in path:  # a NUL byte is never a file name (the file check would raise: a 500)
            abort(404)
        if path.lower().endswith(".pdf") and path != SAMPLE_REPORT:  # no other document is published
            abort(404)
        target = (PUBLIC / path).resolve()
        if PUBLIC not in target.parents or not target.is_file():
            abort(404)
        return send_from_directory(PUBLIC, path)

    return app


app = create_app()

if __name__ == "__main__":
    print("Development server only. For production use wsgi.py (see DEPLOYMENT_GUIDE.md).")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5090")), debug=False)
