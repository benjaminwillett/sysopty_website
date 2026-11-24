# Sysopty marketing site

Single-page marketing site for https://sysopty.com/. It is plain HTML, CSS and JavaScript, plus a small Flask server for the enquiry form. There is no frontend build step, and nothing at runtime depends on the Sysopty product.

```
sysopty_site/
  public/              everything that is served (the only folder to deploy as static files)
    index.html         the page
    css/site.css       styles (palette tokens at the top)
    js/site.js         navigation, lightbox, enquiry form
    img/               logo, generated product images (WebP), social image, touch icon
    robots.txt, sitemap.xml
  server.py            serves public/ and the enquiry API
  wsgi.py              production entry point (refuses an unsafe configuration)
  tests/               pytest suite + browser_smoke.py (Playwright)
  build/               asset pipeline and release packaging (never deploy)
  deploy/              reference Caddyfile and systemd unit
```

## Local preview

```bash
python -m pip install -r requirements.txt
python server.py                # development server only: http://127.0.0.1:5090/
python -m pytest tests          # server, security, SMTP (mocked), public/ and anonymisation tests
python tests/browser_smoke.py   # navigation, gallery, lightbox, demo, sample download, 7 viewport widths (needs the server running)
```

## Enquiry form

`POST /api/enquiry` validates every field on the server as well as in the browser. Spam is handled in three ways:

- **Honeypot field:** a hidden field that real visitors never fill in.
- **Signed time token:** fetched from `/api/form-token`. A form submitted less than 3 seconds after loading, or more than 2 hours after, is rejected.
- **Rate limit:** 5 enquiries per hour per address.

Messages are sent by SMTP using the settings in `.env.example`, which are read from environment variables. Credentials are never sent to the browser.

**Submissions are not enabled until SMTP is configured.** Until `SYSOPTY_SMTP_HOST`, `SYSOPTY_MAIL_FROM` and `SYSOPTY_MAIL_TO` are set:
- the endpoint answers `503`;
- the page tells the visitor their message was not sent;
- `/healthz` reports `"mail_configured": false`.

To enable submissions, set those variables (plus a username and password if the mail server needs them) and a long random `SYSOPTY_FORM_SECRET`, then restart.

## Deployment

See **DEPLOYMENT_GUIDE.md** (architecture, environment, procedure, rollback, verification). Build the deployable archive with `python build/package_release.py`; it contains `server.py`, `wsgi.py`, `requirements.txt` and `public/` only. Nothing is deployed and no DNS is changed by anything in this folder.

## Product images (`build/`)

Every screenshot, report page and the interactive demo on the page was rendered by the **real, unmodified Sysopty engine** from **synthetic evidence**. That evidence comes from the fictional Riverside Technology Group network (five sites, 124 devices), which was designed from scratch. No customer data is used.

```bash
python build/make_synthetic_assets.py --platform <platform checkout> --platform-python <its Python>   # all stages, about 15 minutes
python build/make_synthetic_assets.py --platform <platform checkout> --platform-python <its Python> --stage validate
```

- **SYNTHETIC_NETWORK_DESIGN.md:** the network.
- **SYNTHETIC_EVIDENCE_GENERATOR.md:** how it is written as Sysopty evidence and run through the engine. The engine runs in isolation, from an allowlisted copy of its source, so it cannot read customer reference data.

## Report previews and documents

The report pages on the homepage are illustrative layouts built from synthetic data by `build/make_report_previews.py`.
The site publishes no downloadable document: the server returns 404 for every `.pdf`, and `APPROVED_DOCUMENTS` in
`build/package_release.py` is empty. To publish one, review it with `build/review_sample_pdf.py`, view every page,
then add its path and SHA-256 there.

