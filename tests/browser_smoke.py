"""Browser smoke test for the Sysopty site (Playwright + Chromium).

    python tests/browser_smoke.py [--base http://127.0.0.1:5090] [--out DIR]

Prints a JSON report and writes screenshots to --out. It is not part of the pytest run
because it needs a running server and a browser; the release checklist runs it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = [1920, 1440, 1024, 768, 390, 375, 320]


def luminance(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def scroll_all(page):
    height = page.evaluate("document.body.scrollHeight")
    for _ in range(0, height, 600):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(50)
    page.wait_for_timeout(700)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(200)


def run(base: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    r: dict = {"checks": {}, "failures": []}

    def check(name, ok, detail=None):
        r["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            r["failures"].append(name)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------------------------------------------------------------- initial load and performance
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        requests, errors = [], []
        page.on("request", lambda q: requests.append(q.url))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.add_init_script("""
          window.__lcp = 0; window.__cls = 0;
          new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = e.startTime; })
            .observe({type: 'largest-contentful-paint', buffered: true});
          new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
            .observe({type: 'layout-shift', buffered: true});
        """)
        page.goto(base + "/", wait_until="load")
        page.wait_for_timeout(1500)
        perf = page.evaluate("""() => {
          const res = performance.getEntriesByType('resource');
          const nav = performance.getEntriesByType('navigation')[0];
          const by = {};
          for (const e of res) { const t = e.initiatorType; by[t] = (by[t] || 0) + (e.encodedBodySize || e.transferSize || 0); }
          return {lcp_ms: Math.round(window.__lcp), cls: Math.round(window.__cls * 1000) / 1000,
                  html_bytes: nav.encodedBodySize, resource_bytes: by,
                  total_bytes: nav.encodedBodySize + res.reduce((a, e) => a + (e.encodedBodySize || 0), 0),
                  third_party: res.map(e => e.name).filter(u => !u.startsWith(location.origin))};
        }""")
        r["performance_initial"] = perf
        check("topology demo not loaded initially", not any("/demo/" in u for u in requests))
        check("no third-party requests on load", not perf["third_party"], perf["third_party"])
        check("sample report PDF not loaded initially", not any(".pdf" in u.lower() for u in requests))

        # ---------------------------------------------------------------- findings
        cards = page.locator("#findings .insights > li")
        check("findings section has three cards", cards.count() == 3, cards.count())
        check("findings heading", page.inner_text("#findings-title") == "More than an inventory. Findings with their evidence.")

        # ---------------------------------------------------------------- navigation
        def settle():                                   # wait until smooth scrolling has stopped
            last = None
            for _ in range(40):
                y = page.evaluate("window.scrollY")
                if y == last:
                    return
                last = y
                page.wait_for_timeout(120)

        for href in ("#services", "#how-it-works", "#sample-reports", "#pricing", "#contact"):
            page.click(f'.nav-list a[href="{href}"]')
            page.wait_for_timeout(150)
            settle()
            top = page.evaluate(f"document.querySelector('{href}').getBoundingClientRect().top")
            check(f"nav {href} scrolls to its section", -5 < top < 140, round(top))
        page.click(".brand")
        try:                                        # smooth scrolling over ~5000 px takes about 1.5 s
            page.wait_for_function("() => window.scrollY < 5", timeout=4000)
        except Exception:
            pass
        check("logo returns to top", page.evaluate("window.scrollY") < 5, page.evaluate("window.scrollY"))
        for sel, want in (('.hero a[data-enquiry="assessment"]', "assessment"),
                          ('#pricing a[data-enquiry="proposal"]', "proposal"),
                          ('.cta-band a[data-enquiry="assessment"]', "assessment"),
                          ('.nav-list a[data-enquiry="assessment"]', "assessment")):
            page.select_option("#f-type", "general")
            page.click(sel)
            page.wait_for_timeout(900)
            check(f"CTA {sel} preselects {want}", page.input_value("#f-type") == want)
        links = page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))""")
        dead = [h for h in links if h.startswith("#") and len(h) > 1 and not page.query_selector(h)]
        check("no dead in-page links", not dead, dead)

        # ---------------------------------------------------------------- gallery and lightbox
        page.locator(".more-examples summary").click()
        scroll_all(page)
        imgs = page.evaluate("""() => [...document.querySelectorAll('.shot-frame img')].map(i => ({
            src: i.currentSrc, ok: i.complete && i.naturalWidth > 0,
            ratio_ok: Math.abs((i.naturalWidth / i.naturalHeight) / (i.getAttribute('width') / i.getAttribute('height')) - 1) < 0.02}))""")
        check("7 gallery images", len(imgs) == 7, len(imgs))
        check("gallery images load", all(i["ok"] for i in imgs), [i["src"] for i in imgs if not i["ok"]])
        check("gallery width/height attributes match images", all(i["ratio_ok"] for i in imgs))
        titles = []
        page.locator(".shot-frame").first.click()
        page.wait_for_timeout(700)
        check("lightbox opens", page.evaluate("document.getElementById('lightbox').open"))
        for _ in range(7):
            page.wait_for_function("() => { const i = document.querySelector('.lb-viewport img'); return i.complete && i.naturalWidth > 0; }", timeout=8000)
            titles.append(page.inner_text("#lb-title"))
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(250)
        check("ArrowRight walks all 7 full-size images and wraps", len(set(titles)) == 7 and page.inner_text("#lb-title") == titles[0], titles)
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(300)
        check("ArrowLeft wraps to last", page.inner_text("#lb-title") == titles[-1])
        page.click('[data-lb="next"]')
        page.wait_for_timeout(300)
        check("next button", page.inner_text("#lb-title") == titles[0])
        page.click('[data-lb="prev"]')
        page.wait_for_timeout(300)
        check("previous button", page.inner_text("#lb-title") == titles[-1])

        def scale():
            t = page.evaluate("document.querySelector('.lb-viewport img').style.transform")
            return float(t.split("scale(")[1].rstrip(")")) if "scale(" in t else None
        s0 = scale()
        page.click('[data-lb="in"]')
        check("zoom in button", scale() > s0)
        page.keyboard.press("-")
        page.keyboard.press("-")
        check("keyboard zoom out", scale() < s0 * 1.4)
        page.keyboard.press("0")
        check("0 fits", abs(scale() - s0) < 1e-6)
        page.mouse.move(720, 450)
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(100)
        check("wheel zoom", scale() > s0)
        before = page.evaluate("document.querySelector('.lb-viewport img').style.transform")
        page.mouse.move(700, 450)
        page.mouse.down()
        page.mouse.move(600, 400, steps=5)
        page.mouse.up()
        check("drag pans", page.evaluate("document.querySelector('.lb-viewport img').style.transform") != before)
        page.click('[data-lb="actual"]')
        check("100% button", abs(scale() - 1) < 1e-6)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("Escape closes lightbox", not page.evaluate("document.getElementById('lightbox').open"))
        check("focus returns to the opener", page.evaluate("document.activeElement.classList.contains('shot-frame')"))
        page.locator(".report-stack .page-1").click()
        page.wait_for_timeout(500)
        check("hero cover opens in lightbox", "As-Built" in page.inner_text("#lb-title"), page.inner_text("#lb-title"))
        page.keyboard.press("Escape")

        # Missing image: the lightbox says so instead of showing an empty frame.
        errors_before_404 = len(errors)                 # the next check causes a 404 on purpose
        page.route("**/img/gallery/findings-full.webp", lambda route: route.fulfill(status=404, body=""))
        page.locator(".shot-frame").nth(1).click()
        page.wait_for_timeout(800)
        check("missing full-size image is reported", "could not be loaded" in page.inner_text(".lb-caption").lower(),
              page.inner_text(".lb-caption"))
        page.keyboard.press("Escape")
        page.unroute("**/img/gallery/findings-full.webp")
        del errors[errors_before_404:]

        # ---------------------------------------------------------------- topology demo
        demo_requests = []
        page.on("request", lambda q: demo_requests.append(q.url))
        page.click('.hero a[href="#sample-reports"]')              # "View Sample Documentation"
        page.wait_for_timeout(900)
        top = page.evaluate("document.querySelector('#sample-reports').getBoundingClientRect().top")
        check("View Sample Documentation reaches the gallery", -5 < top < 140, round(top))
        check("topology not loaded until asked", not any("/demo/" in u for u in demo_requests))
        page.click("[data-load-topology]")                            # "Explore Interactive Example"
        page.wait_for_timeout(8000)
        frame = page.frame_locator("[data-topology] iframe")
        check("Explore Interactive Example loads the topology viewer", frame.locator("svg.main-svg").count() > 0)
        external = [u for u in demo_requests if not (u.startswith(base) or u.startswith("data:") or u.startswith("blob:"))]
        check("demo makes no external requests", not external, external)
        check("demo only fetches its own page", all(u.startswith(base + "/demo/") or u.startswith(("data:", "blob:")) for u in demo_requests),
              [u for u in demo_requests][:5])
        visible = frame.locator("button").evaluate_all("bs => bs.filter(b => b.offsetParent).map(b => b.textContent.trim())")
        check("Visio and monitoring controls hidden in demo",
              not any(t in ("Download Visio", "Enable Monitoring") for t in visible), visible)
        check("demo opens with leaf nodes shown",
              not frame.locator('label:has-text("Hide leaf nodes") input').first.is_checked())
        check("demo opens in icon view", frame.locator("button", has_text="Boxes").count() == 1)
        sel = frame.locator("select").first
        options = sel.evaluate("s => [...s.options].map(o => o.value)")
        ok_views = True
        for v in options:
            try:
                sel.select_option(v)
                page.wait_for_timeout(1200)
            except Exception:
                ok_views = False
        check("every topology view can be selected", ok_views and len(options) >= 2, options)
        search = frame.locator('input[placeholder*="hostname" i]').first
        search.fill("c3750-rmc-c01")
        search.press("Enter")
        page.wait_for_timeout(1500)
        check("hostname search runs without errors", not [e for e in errors if "topology" in e.lower()], errors[-3:])
        r["demo_buttons"] = visible
        check("no page errors", not errors, errors[:5])
        page.screenshot(path=str(out / "desktop_1440_viewport.png"))
        ctx.close()

        # ---------------------------------------------------------------- responsive
        r["responsive"] = {}
        for w in WIDTHS:
            ctx = browser.new_context(viewport={"width": w, "height": 900 if w > 800 else 800},
                                      has_touch=w < 800, is_mobile=w < 800, device_scale_factor=2 if w < 800 else 1)
            pg = ctx.new_page()
            pg.goto(base + "/", wait_until="load")
            scroll_all(pg)
            info = pg.evaluate("""() => {
              const vw = document.documentElement.clientWidth;
              const over = [...document.querySelectorAll('body *')].filter(e => {
                const b = e.getBoundingClientRect(); return b.width && (b.right > vw + 1) && getComputedStyle(e).position !== 'fixed'
                  && !e.closest('.hp-field') && !e.closest('.visually-hidden') && !e.closest('dialog'); }).map(e => e.className || e.tagName).slice(0, 5);
              const small = [...document.querySelectorAll('a, button, input, select, textarea')].filter(e => {
                const b = e.getBoundingClientRect(); return b.width && b.height && e.offsetParent && !e.closest('.hp-field')
                  && !e.closest('dialog') && (b.height < 44 && b.width < 44 || b.height < 24);}).map(e => (e.innerText || e.name || e.className).slice(0, 30));
              return {scrollWidth: document.documentElement.scrollWidth, viewport: vw, overflowing: over, small_targets: small};
            }""")
            if w < 800:
                pg.click(".nav-toggle")
                pg.wait_for_timeout(200)
                info["nav_opens"] = pg.is_visible("#site-nav .nav-list")
                pg.screenshot(path=str(out / f"mobile_{w}_nav.png"))
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(200)
                info["nav_escape_closes"] = pg.get_attribute(".nav-toggle", "aria-expanded") == "false"
                pg.click(".nav-toggle")
                pg.click('#site-nav a[href="#pricing"]')
                pg.wait_for_timeout(800)
                info["nav_link_closes"] = pg.get_attribute(".nav-toggle", "aria-expanded") == "false"
                # touch: tap opens the lightbox; one-finger drag pans
                pg.evaluate("window.scrollTo(0, document.querySelector('#sample-reports').offsetTop)")
                pg.wait_for_timeout(300)
                pg.locator(".shot-frame").first.tap()
                pg.wait_for_timeout(600)
                info["tap_opens_lightbox"] = pg.evaluate("document.getElementById('lightbox').open")
                cdp = ctx.new_cdp_session(pg)
                t0 = pg.evaluate("document.querySelector('.lb-viewport img').style.transform")
                for typ, x in (("touchStart", 200), ("touchMove", 160), ("touchMove", 120), ("touchEnd", 120)):
                    cdp.send("Input.dispatchTouchEvent", {"type": typ, "touchPoints": [] if typ == "touchEnd" else [{"x": x, "y": 400}]})
                info["touch_drag_pans"] = pg.evaluate("document.querySelector('.lb-viewport img').style.transform") != t0
                s = pg.evaluate("document.querySelector('.lb-viewport img').style.transform")
                for typ, d in (("touchStart", 40), ("touchMove", 80), ("touchMove", 120), ("touchEnd", 120)):
                    pts = [] if typ == "touchEnd" else [{"x": 195 - d, "y": 400, "id": 1}, {"x": 195 + d, "y": 400, "id": 2}]
                    cdp.send("Input.dispatchTouchEvent", {"type": typ, "touchPoints": pts})
                info["pinch_zooms"] = pg.evaluate("document.querySelector('.lb-viewport img').style.transform") != s
                pg.keyboard.press("Escape")
                for k in ("nav_opens", "nav_escape_closes", "nav_link_closes", "tap_opens_lightbox", "touch_drag_pans", "pinch_zooms"):
                    check(f"{w}px {k}", info[k])
            showcase = pg.evaluate("""() => {
              const a = document.querySelector('#sample-reports .sample-download .btn').getBoundingClientRect();
              const xs = [...document.querySelectorAll('#findings .insights > li')].map(e => Math.round(e.getBoundingClientRect().left));
              return {button_h: a.height, button_w: a.width, card_lefts: xs};
            }""")
            info["showcase"] = showcase
            check(f"{w}px download button usable", showcase["button_h"] >= 44 and showcase["button_w"] > 0, showcase)
            stacked = len(set(showcase["card_lefts"])) == 1
            check(f"{w}px findings cards {'stacked' if w < 880 else 'side by side'}",
                  len(showcase["card_lefts"]) == 3 and (stacked if w < 880 else len(set(showcase["card_lefts"])) == 3),
                  showcase["card_lefts"])
            pg.evaluate("window.scrollTo(0,0)")
            pg.wait_for_timeout(200)
            pg.screenshot(path=str(out / f"page_{w}.png"), full_page=True)
            check(f"{w}px no horizontal overflow", info["scrollWidth"] <= info["viewport"], info["overflowing"])
            r["responsive"][w] = info
            ctx.close()

        # ---------------------------------------------------------------- contrast of the palette's text pairs
        pairs = {
            "text on bg": ((245, 249, 252), (3, 19, 35)), "text-2 on bg": ((168, 190, 208), (3, 19, 35)),
            "text-2 on card": ((168, 190, 208), (9, 34, 57)), "text-3 on bg": ((127, 151, 171), (3, 19, 35)),
            "text-3 on card": ((127, 151, 171), (9, 34, 57)), "cyan on bg": ((0, 188, 212), (3, 19, 35)),
            "button text on cyan": ((2, 34, 51), (0, 188, 212)), "figure caption on white": ((79, 100, 117), (255, 255, 255)),
            "error text on card": ((255, 180, 171), (9, 34, 57)),
        }
        r["contrast"] = {k: contrast(*v) for k, v in pairs.items()}
        for k, v in r["contrast"].items():
            check(f"contrast {k} >= 4.5", v >= 4.5, v)
        browser.close()
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5090")
    ap.add_argument("--out", type=Path, default=Path("smoke_screens"))
    a = ap.parse_args()
    report = run(a.base.rstrip("/"), a.out)
    print(json.dumps(report, indent=1, default=str))
    sys.exit(1 if report["failures"] else 0)
