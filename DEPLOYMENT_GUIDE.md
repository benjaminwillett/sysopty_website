# Sysopty website: deployment guide

This guide describes how to deploy the existing Flask site. Nothing in it has been provisioned or deployed. The hosting provider is the owner's choice: the design runs on any small Linux or Windows server.

## 1. Recommended architecture

```
Internet ──HTTPS 443──▶ Caddy (TLS, HTTP→HTTPS, compression, access log)
                          │  reverse_proxy 127.0.0.1:8080  (X-Forwarded-For / -Proto / -Host)
                          ▼
                       waitress (single process, 8 threads)  ──▶  wsgi:app  (server.py)
                          │                                        │
                          │                                        └─ SMTP submission (TLS) ─▶ mail provider
                          └─ reads public/ only (static files, demo)
```

| Component | Choice | Why |
|---|---|---|
| Host | One small VM: 1 vCPU, 1 GB RAM, 10 GB disk. Linux (Ubuntu/Debian LTS) is preferred; Windows Server works too. | The site is stateless and light: about 10 MB of files and one form endpoint. |
| WSGI server | **waitress ≥ 3.0.2**, single process, with the trusted-proxy flags | Pure Python, runs on Windows and Linux. A single process keeps the in-memory rate limit shared by every request (gunicorn with several workers would give each worker its own limit). Do not use 3.0.0: CVE-2024-49768 and CVE-2024-49769. |
| Reverse proxy and TLS | **Caddy 2** | Automatic Let's Encrypt certificates and renewal, HTTP→HTTPS redirect, zstd/gzip. The 6 MB topology demo compresses to about 1.5 MB. Two short config files (`deploy/Caddyfile`). nginx or IIS + ARR work if they are already standard in your environment. |
| Process supervision | systemd on Linux (`deploy/sysopty-site.service`). On Windows, run waitress and Caddy as services (for example with NSSM or `sc.exe` and a wrapper). | Restart on failure and start at boot. |
| Headers | Set by the application on every response; Caddy only removes `Server`. | One source of truth: the CSP, the demo sandbox and HSTS are covered by `tests/test_prelaunch.py`. |

**Not recommended for this release:**
- A static-only host such as S3, Netlify or Pages. The enquiry form needs `/api/form-token` and `/api/enquiry`, and the security headers would have to be rebuilt in that host's own format.
- Serving `public/` directly from Caddy. It works, but the headers would then live in two places.

## 2. Environment variables

They are all documented in `.env.example`. Keep them in `/etc/sysopty-site/site.env` on Linux (mode 0600, owned by root) or in the Windows service's environment. **Never deploy a `.env` file inside the site folder.**

| Variable | Required | Notes |
|---|---|---|
| `SYSOPTY_FORM_SECRET` | **Yes** | At least 32 random characters: `python -c "import secrets; print(secrets.token_hex(32))"`. `wsgi.py` refuses to start without it. |
| `SYSOPTY_SMTP_HOST` | For enquiries | Until this is set, the form tells visitors their message was **not** sent (503). |
| `SYSOPTY_SMTP_PORT` | | 587 with `starttls`, 465 with `ssl`. |
| `SYSOPTY_SMTP_SECURITY` | | `starttls` (default), `ssl` or `none`. `none` is only for an unauthenticated internal relay; with a username, `wsgi.py` refuses it. |
| `SYSOPTY_SMTP_USERNAME` / `SYSOPTY_SMTP_PASSWORD` | If the provider needs login | Use an app password or SMTP credential scoped to sending only. |
| `SYSOPTY_MAIL_FROM` | With SMTP | An address the provider allows you to send as (SPF/DKIM aligned for your domain). |
| `SYSOPTY_MAIL_TO` | With SMTP | The inbox that receives enquiries. |
| `SYSOPTY_TRUST_PROXY` | **Yes behind Caddy** (`1`) | Use together with waitress's `--trusted-proxy=127.0.0.1 --trusted-proxy-headers="x-forwarded-for x-forwarded-proto x-forwarded-host" --clear-untrusted-proxy-headers` (in `deploy/sysopty-site.service`). **waitress removes `X-Forwarded-*` from untrusted peers**: without those flags every visitor appears to be the proxy, the whole site shares one rate limit (5 enquiries per hour) and HSTS is never sent. This was verified locally with Caddy 2.11 and waitress. |
| `SYSOPTY_HSTS_MAX_AGE` | | Default 31536000 (one year), sent on HTTPS responses only. Start with 300 for the first deployment, then raise it. |

## 3. First-time setup (Linux example)

```bash
sudo useradd --system --home /opt/sysopty-site --shell /usr/sbin/nologin sysopty
sudo mkdir -p /opt/sysopty-site/releases /etc/sysopty-site
sudo python3 -m venv /opt/sysopty-site/venv
sudo install -m 0600 /dev/null /etc/sysopty-site/site.env     # then fill in from .env.example
sudo cp deploy/sysopty-site.service /etc/systemd/system/
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile                # after installing Caddy from its official repository
```

DNS (owner action): point `sysopty.com` and `www.sysopty.com` (A/AAAA records) at the server. Ports 80 and 443 must be reachable so Caddy can obtain certificates. Only 22 (restricted to admin addresses), 80 and 443 should be open. Waitress listens on 127.0.0.1 only.

## 4. Deployment procedure

On the build machine:

```bash
python -m pytest tests                              # all must pass
python build/make_synthetic_assets.py --stage check --platform <platform checkout>   # only if the assets were rebuilt; must report 0 problems
python build/package_release.py                     # dist/sysopty-site-<timestamp>.zip + .sha256
```

`package_release.py` packages an allowlist only: `server.py`, `wsgi.py`, `requirements.txt` and `public/`. It refuses to build if a private or non-web file would be included. `build/` (including `private_rules.json`), `tests/`, these documents and any `.env` are never packaged.

On the server:

```bash
R=/opt/sysopty-site/releases/$(date +%Y%m%d-%H%M%S)
sudo mkdir -p "$R" && sudo unzip -q sysopty-site-<timestamp>.zip -d "$R"
(cd "$R" && sha256sum -c --ignore-missing /path/to/sysopty-site-<timestamp>.sha256)
sudo /opt/sysopty-site/venv/bin/pip install -r "$R/requirements.txt"
sudo -u sysopty env $(sudo cat /etc/sysopty-site/site.env | xargs) /opt/sysopty-site/venv/bin/python -c "import sys; sys.path.insert(0,'$R'); import wsgi"   # configuration check
sudo ln -sfn "$R" /opt/sysopty-site/current
sudo systemctl daemon-reload && sudo systemctl enable --now sysopty-site && sudo systemctl restart sysopty-site
sudo systemctl reload caddy
```

On **Windows**, the steps are the same:
1. Extract the release into `C:\sysopty-site\releases\<timestamp>`.
2. Install the requirements into a venv.
3. Point the service's working directory at the new release.
4. Restart the waitress service with the same command line as the Linux unit file, `--trusted-proxy` flags included.

## 5. Rollback

Releases are kept side by side, so rollback means pointing at the previous release and restarting:

```bash
ls -1 /opt/sysopty-site/releases                    # pick the previous release
sudo ln -sfn /opt/sysopty-site/releases/<previous> /opt/sysopty-site/current
sudo systemctl restart sysopty-site
```

Keep at least the last three releases. The site holds no data (enquiries are only emailed), so rollback never loses anything.

## 6. Post-deployment verification

```bash
curl -sI https://sysopty.com/ | grep -Ei 'strict-transport|content-security|x-frame|x-content-type'
curl -s  https://sysopty.com/healthz                # {"mail_configured": true, "status": "ok"}
curl -sI http://sysopty.com/ | head -1              # 308 redirect to https
# Proxy headers reach the app: HSTS present above; a 6th test enquiry from one address in an hour gets 429, not the whole site.
curl -sI https://www.sysopty.com/ | grep -i location
curl -s -o /dev/null -w '%{http_code}\n' https://sysopty.com/server.py   # 404
curl -sI -H 'Accept-Encoding: gzip' https://sysopty.com/css/site.css | grep -i content-encoding
python tests/browser_smoke.py --base https://sysopty.com --out smoke_prod   # read-only; submits no enquiry
```

Then the owner sends **one real test enquiry** from the live form and confirms it arrives, with Reply-To set to the visitor's address.

## 7. Operations

- **Logging.** Caddy access logs are JSON and rotated (they contain visitor IP addresses, which the privacy notice should mention). The application logs to the service journal: delivery failures as `enquiry delivery failed: <ExceptionType>`, without visitor details or SMTP server replies.
- **Monitoring.**
  - An external uptime check on `https://sysopty.com/healthz` that expects `"mail_configured": true`.
  - An alert on `enquiry delivery failed` in the journal.
  - Caddy renews certificates automatically; watch its log for renewal errors.
- **Backups.** The server holds no data. Keep the release archives and their `.sha256` files, plus a secure copy of the environment values in your password manager or secret store. The asset build machine's `build/private_rules.json` must be backed up **privately**: it is needed to regenerate the images.
- **Updates.**
  - Apply OS security updates and `pip install -U -r requirements.txt` in a test release first.
  - Re-run `pytest` and the browser smoke test before switching `current`.
  - Re-check waitress, Flask and Werkzeug against published advisories, for example with `pip-audit` (not installed on the build machine).
