"""Builds the website's demonstration assets from the synthetic Riverside Technology Group
network, rendered by the real, unmodified Sysopty engine.

    python build/make_synthetic_assets.py [--stage all|engine|evidence|reports|vlan|demo|images|validate|check]

engine    copy the product's code (allowlist, no customer data) into an isolated engine folder
evidence  register the synthetic customer and sites, write their evidence, build each site's map
reports   run the engine's offline report for all five sites
vlan      render VLAN maps with the engine's VLAN-map snapshotter (RTG-HQ)
demo      the enterprise-wide interactive map as the public demo page, and its poster image
images    gallery figures, hero pages, social image and the gallery markup in index.html
validate  consistency checks of the synthetic network and evidence
check     customer-data leak check of everything generated and published (needs the private
          comparison data on the build machine; skipped elsewhere)

No step uses customer evidence as input. The check step only compares against it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "synthetic"))
sys.path.insert(0, str(HERE))
import engine as G          # noqa: E402
import network as N         # noqa: E402
import site_images as SI    # noqa: E402

PUBLIC = HERE.parent / "public"
WORK = G.WORK
HQ, DC1 = "RTG-HQ", "RTG-DC1"

# Every gallery image is taken from the published sample report itself (public/samples), so what the
# page shows is exactly what the download contains.  The first four fill the wide (16:10) cards, the
# last three the narrower (4:3) ones.  ("crop", page text, (left, top, right, bottom) fractions) is a
# legible region of a page; ("pdf", caption, None) is a whole figure.
GALLERY = [
    ("summary", "Executive summary", HQ, ("crop", r"1\.1 Site at a glance", (0.06, 0.075, 0.955, 0.50)),
     "The site at a glance: switches, firewalls, VLANs, access points and endpoints, with the core "
     "infrastructure and how complete the collected evidence is."),
    ("findings", "Findings register", HQ, ("crop", r"9\.1\s+Findings and recommendations", (0.045, 0.07, 0.955, 0.86)),
     "Every finding with its severity, the devices it affects, the confidence of the evidence and a "
     "recommended action."),
    ("topology", "Physical topology", HQ, ("pdf", r"Figure \d+ – L1 Physical Topology[^\n]*", None),
     "How switches, stacks and firewalls are cabled, drawn from the devices' own neighbour tables."),
    ("services", "Access and addressing services", HQ, ("pdf", r"Figure \d+ – Service map: access and addressing[^\n]*", None),
     "Which authentication and DHCP servers each group of devices depends on, read from their "
     "configurations."),
    ("risks", "Key risks and next actions", HQ, ("crop", r"1\.2 Key risks and next actions", (0.06, 0.40, 0.955, 0.81)),
     "The highest-severity risks, why they matter, how strongly the evidence supports them and the next step."),
    ("connectivity", "Engineering connectivity", HQ, ("pdf", r"Figure \d+ – Engineering Connectivity, page 2[^\n]*", None),
     "Port-level links for each core and distribution device, for change planning and fault finding."),
    ("readiness", "Readiness assessment", HQ, ("crop", r"8\.4\s+Readiness assessment", (0.06, 0.098, 0.955, 0.555)),
     "What a change or refresh project can rely on: confirmed facts, unknowns and the actions to close them, "
     "each with its evidence."),
]
SAMPLE_PDF = PUBLIC / "samples" / "Sysopty_Sample_Network_As-Built_Report.pdf"


def reports() -> dict:
    out = {}
    for site in N.SITES:
        pdfs = sorted((WORK / "reports" / site).rglob("devices_report_*.pdf"))
        if not pdfs:
            raise SystemExit(f"run the reports stage first ({site})")
        out[site] = pdfs[-1]
    return out


# ------------------------------------------------------------------ stages
def stage_engine():
    G.make_engine_copy()
    logo = WORK / "sysopty_logo.png"
    if not logo.exists():
        from playwright.sync_api import sync_playwright
        mark = (PUBLIC / "img" / "sysopty-mark.svg").read_text(encoding="utf-8")
        font = (PUBLIC / "fonts" / "poppins-latin-600.woff2").as_uri()
        html = (f"<html><head><style>@font-face{{font-family:P;src:url('{font}')}}body{{margin:0}}"
                "div{display:inline-flex;align-items:center;gap:22px;padding:6px 10px}svg{width:118px;height:118px}"
                "span{font:600 116px/1 P,'Segoe UI',sans-serif;color:#0b2540;letter-spacing:-1px}</style></head>"
                f"<body><div id=logo>{mark}<span>Sysopty</span></div></body></html>")
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(device_scale_factor=2)
            page.set_content(html, wait_until="networkidle")
            page.locator("#logo").screenshot(path=str(logo), omit_background=True)
            b.close()
    print(f"engine copy: {sum(1 for _ in G.ENGINE.rglob('*.py'))} source files, verified")


def stage_evidence():
    G.generate_evidence(N.build())


def stage_reports():
    for site, pdf in G.run_reports().items():
        print(f"{site}: {pdf.name}")


def stage_vlan():
    html = G.WORK / "artifacts" / G.CUSTOMER / HQ / "discovery" / f"network_topology_{HQ}.html"
    if not html.exists():
        html = next((G.WORK / "artifacts").rglob(f"network_topology_{HQ}.html"))
    out = WORK / "vlan_maps"
    res = G.run_engine("import json, topology_snapshot\n"
                       f"r = topology_snapshot.snapshot_vlan_maps({str(html)!r}, {str(out)!r})\n"
                       "print(json.dumps([[v, n, str(p)] for v, n, p in r]))")
    maps = json.loads(res.strip().splitlines()[-1])
    (WORK / "vlan_maps.json").write_text(json.dumps(maps, indent=1), encoding="utf-8")
    print(f"vlan maps: {len(maps)}")


DEMO_MAP_ENV = {"NETWORK_MAP_NODE_STYLE": "icons"}   # the engine's own option: open in the icon view


def stage_demo():
    # The website's enterprise map is built by the engine with icons as the default node style.
    import evidence as E
    enterprise = WORK / "enterprise_map"
    print(f"enterprise map (icons): {G.build_map(E.topology_inputs(N.build(), list(N.SITES)), N.ORG, enterprise, DEMO_MAP_ENV)}")
    src = enterprise / f"network_topology_{N.ORG}.html"
    html = src.read_text(encoding="utf-8")
    # Website default: leaf nodes (APs and endpoints) shown. The engine hides them when they
    # outnumber the infrastructure; the demo starts with the whole network visible, and the
    # page's "Hide leaf nodes" box still hides them.
    html, n = re.subn(r"var hideLeaf = (true|false);", "var hideLeaf = false;", html, count=1)
    if n != 1:
        raise SystemExit("the map page no longer declares its leaf-node default the expected way")
    if "var ICON_DEFAULT = true;" not in html:
        raise SystemExit("the engine did not apply the icon default")
    plotly = (G.ENGINE / "_assets" / "plotly.min.js").read_text(encoding="utf-8")
    html, n = re.subn(r'<script src="[^"]*plotly\.min\.js"[^>]*></script>',
                      lambda _: "<script>" + plotly.replace("</script", "<\\/script") + "</script>", html, count=1)
    # A page outside the artifact root already carries its own copy of the library.
    if n != 1 and plotly.replace("</script", "<\\/script") not in html and plotly not in html:
        raise SystemExit("the map page does not load plotly.min.js the expected way")
    html = html.replace("<head>", "<head><title>Sysopty interactive topology (synthetic demonstration network)</title>"
                        '<meta name="robots" content="noindex">', 1)
    # Two controls need an engineer's workstation (Visio files beside the map, a local
    # monitoring agent); the demo hides them, and the page says they are unavailable.
    hide = ("<script>(function(){var off=['Download Visio','Enable Monitoring','Disable Monitoring'];"
            "function h(){document.querySelectorAll('button').forEach(function(b){"
            "if(off.indexOf(b.textContent.trim())>=0)b.style.display='none';});}"
            "h();new MutationObserver(h).observe(document.documentElement,{childList:true,subtree:true});})();</script>")
    html = html.replace("</body>", hide + "</body>", 1) if "</body>" in html else html + hide
    demo = PUBLIC / "demo" / "topology.html"
    demo.write_text(html, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1.5)
        page.goto(demo.as_uri())
        page.wait_for_timeout(5000)
        page.screenshot(path=str(WORK / "topology_poster.png"))
        b.close()
    from PIL import Image                       # the poster shows the demo's default view
    SI.save_set(Image.open(WORK / "topology_poster.png"), "topology-poster", PUBLIC / "img", widths=(800, 1280),
                full_max=2400)
    print(f"demo: {demo} ({demo.stat().st_size / 1e6:.1f} MB)")


def stage_images():
    from PIL import Image
    # The published sample (its pinned bytes) is the only source: the page shows what the download holds.
    pdfs = {HQ: SI.open_pdf(SAMPLE_PDF)}
    texts = {s: SI.page_texts(p) for s, p in pdfs.items()}
    used = {s: set() for s in pdfs}
    used[HQ].add(0)
    items = []
    for key, title, site, (kind, a, b), blurb in GALLERY:
        if kind == "pdf":
            img, caption = SI.figure_from_pdf(pdfs[site], texts[site], a, used[site])
            caption = re.sub(r",\s*evidence snapshot \w+\s*$", "", SI.caption_text(caption))   # short card caption
        else:
            i, _ = SI.find(texts[site], a, used[site])
            img = SI.render_region(pdfs[site], i, b)
            caption = f"{SI.section_title(texts[site][i], a)}, {site} (page {i + 1})"
        sizes = SI.save_set(img, key, PUBLIC / "img" / "gallery")
        items.append({"key": key, "title": title, "caption": caption, "text": blurb, "site": site, "sizes": sizes})
        print(f"{key}: {img.size} | {caption}")
    # The hero: the cover in front, the executive summary and the key risks behind it.
    hero = {"cover": (HQ, 0), "page2": (HQ, SI.find(texts[HQ], r"1\.1 Site at a glance")[0]),
            "page3": (HQ, SI.find(texts[HQ], r"1\.2 Key risks and next actions")[0])}
    for key, (site, i) in hero.items():
        used[site].add(i)
        SI.save_set(SI.render_page(pdfs[site], i), key, PUBLIC / "img" / "hero", widths=(480, 640, 1200), full_max=1800)
    SI.save_set(Image.open(WORK / "topology_poster.png"), "topology-poster", PUBLIC / "img", widths=(800, 1280),
                full_max=2400)
    og = Image.new("RGB", (1200, 630), (3, 19, 35))
    cover = Image.open(PUBLIC / "img" / "hero" / "cover-640.webp").convert("RGB")
    og.paste(cover.resize((380, round(cover.height * 380 / cover.width)), Image.LANCZOS), (90, 60))
    arch = Image.open(PUBLIC / "img" / "gallery" / "topology-800.webp").convert("RGB")
    arch.thumbnail((620, 460))
    panel = Image.new("RGB", (arch.width + 24, arch.height + 24), (255, 255, 255))
    panel.paste(arch, (12, 12))
    og.paste(panel, (520, (630 - panel.height) // 2))
    og.save(PUBLIC / "img" / "og-image.png", optimize=True)
    SI.write_gallery(items, f"the synthetic {N.ORG} demonstration network")
    manifest = {"gallery": items, "pdf_pages": {s: sorted(v) for s, v in used.items()},
                "source": str(SAMPLE_PDF), "reports": {s: str(p) for s, p in reports().items()}}
    (WORK / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print("images written")


def stage_validate():
    import validate as V
    net = N.build()
    problems = V.validate_network(net) + V.validate_timeline(N.as_of_july(N.build()), net) + \
        V.validate_evidence(WORK / "artifacts") + V.validate_written(net, WORK / "artifacts")
    try:
        pdfs = reports()
    except SystemExit:
        pdfs = {}
        print("reports not generated yet: report checks skipped")
    for site, pdf in pdfs.items():                     # the generated reports against the design
        problems += V.validate_report(net, site, "\n".join(SI.page_texts(SI.open_pdf(pdf))))
    for p in problems:
        print("PROBLEM:", p)
    print(f"validation: {len(problems)} problem(s)")
    if problems:
        raise SystemExit(1)


# ------------------------------------------------------------------ customer-data leak check
def _real_identifiers():
    """Identifier sets from the real customer evidence, for comparison only (never written out)."""
    import glob
    import pandas as pd
    # The leak check runs only on a machine that names its private rules, a file outside this repository.
    rules_path = Path(os.environ.get("SYSOPTY_PRIVATE_RULES") or "")
    if not os.environ.get("SYSOPTY_PRIVATE_RULES") or not rules_path.is_file():
        return None
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    store = Path.home() / "AppData" / "Local" / "Sysopty" / "artifacts"
    roots = [p for p in store.glob("*") if p.is_dir() and not p.name.startswith(("_", "Riverside"))]
    names, serials, macs, ips = set(), set(), set(), set()
    for root in roots:
        for wb in list(root.glob("*/audits/*.xlsx")) + list(root.glob("*/discovery/*.xlsx")):
            try:
                frames = pd.read_excel(wb, sheet_name=None).values()
            except Exception:
                continue
            for df in frames:
                for col in df.columns:
                    vals = df[col].dropna().astype(str)
                    if "serial" in str(col).lower():
                        serials |= {s for v in vals for s in re.split(r"[,\s;]+", v) if len(s) >= 8 and re.search(r"\d", s)}
                    if col in ("Hostname", "Neighbour", "Firewall Hostname"):
                        names |= {v.split("#")[0].strip().lower() for v in vals
                                  if len(v) >= 6 and "-" in v and re.search(r"\d", v)}
        for f in glob.glob(glob.escape(str(root)) + r"\*\raw\*.txt"):
            t = open(f, encoding="utf-8", errors="ignore").read()
            ips |= set(re.findall(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])", t))
            for m in re.finditer(r"(?i)\b[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}\b", t):
                hx = re.sub(r"[^0-9a-f]", "", m.group(0).lower())
                if len(set(hx)) > 2:
                    macs.add(hx)
    ips = {i for i in ips if not i.startswith(("0.", "255.", "127.", "224.")) and not re.fullmatch(r"\d\.\d+\.\d+\.\d+", i)}
    return {"salt": rules["salt"], "blocked": [w.lower() for w in rules["blocklist"]], "names": names,
            "serials": {s.lower() for s in serials}, "macs": macs, "ips": ips}


def stage_check():
    real = _real_identifiers()
    if real is None:
        print("check skipped: the private comparison data is not on this machine")
        return
    sources = {}
    for p in PUBLIC.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".svg", ".txt", ".xml"):
            text = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            if p.name == "topology.html":
                lib = (G.ENGINE / "_assets" / "plotly.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
                text = text.replace(lib, "")
            import html as _h
            import urllib.parse as _u
            sources[f"public/{p.relative_to(PUBLIC)}"] = "\n".join(
                (text, _h.unescape(text), _u.unquote(text),
                 re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)))
    for p in PUBLIC.rglob("*.pdf"):                         # the published sample report: every page is public
        for i, t in enumerate(SI.page_texts(SI.open_pdf(p))):
            sources[f"public/{p.relative_to(PUBLIC).as_posix()} p{i + 1} (published)"] = t
    manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
    for site, pdf in reports().items():                     # every page of every report is scanned
        published = set(manifest["pdf_pages"].get(site, []))
        for i, t in enumerate(SI.page_texts(SI.open_pdf(pdf))):
            sources[f"report {site} p{i + 1}{' (published)' if i in published else ''}"] = t
        for p in pdf.parent.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".dot", ".svg", ".json", ".txt", ".csv", ".html"):
                sources[f"{site}/{p.name}"] = p.read_text(encoding="utf-8", errors="replace")
    for p in (WORK / "artifacts").rglob("*"):
        if p.is_file() and p.suffix.lower() in (".txt", ".json", ".csv"):
            sources[f"evidence/{p.name}"] = p.read_text(encoding="utf-8", errors="replace")
        elif p.is_file() and p.suffix.lower() == ".xlsx":        # audits, mapping, the supplied schedule
            import pandas as pd
            sources[f"evidence/{p.name}"] = "\n".join(df.fillna("").to_csv(index=False) for df in
                                                     pd.read_excel(p, sheet_name=None, dtype=str).values())
    findings = set()
    for name, text in sources.items():
        low = text.lower()
        compact = re.sub(r"[:.\-]", "", low)
        for w in real["blocked"]:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                findings.add((name, "blocked word", w))
        for n in real["names"]:
            if n in low:
                findings.add((name, "real device name", n))
        for s in real["serials"]:
            if s in low:
                findings.add((name, "real serial", s))
        for m in real["macs"]:
            if m in compact:
                findings.add((name, "real MAC", m))
        for ip in set(re.findall(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])", text)) & real["ips"]:
            findings.add((name, "real IP", ip))
    # Classification (nothing is dropped; everything is listed):
    #  * a network or aggregate address (x.x.x.0, 10.0.0.0) names a range, not a host: a shared
    #    RFC 1918 range is a coincidence, not an identifier -> informational;
    #  * text on a report page the website does not publish -> informational (the full PDF is
    #    never published), unless it is a device name, serial, MAC or host address, which fail;
    #  * anything else -> failure.
    failures, info = [], []
    for src, kind, value in sorted(findings):
        tag = "#" + hashlib.sha256(real["salt"].encode() + value.encode()).hexdigest()[:10]
        unpublished_page = src.startswith("report ") and "(published)" not in src
        if kind == "real IP" and (value.endswith(".0") or value == "10.0.0.0"):
            info.append((src, "network address shared with a real range (not a host)", tag))
        elif kind == "blocked word" and unpublished_page:
            info.append((src, "blocked word on an unpublished report page", tag))
        else:
            failures.append((src, kind, tag))
    for f in info:
        print("info:", *f)
    for f in failures:
        print("LEAK:", *f)
    print(f"checked {len(sources)} sources against {len(real['names'])} real device names, {len(real['serials'])} "
          f"serials, {len(real['macs'])} MACs, {len(real['ips'])} IP addresses and {len(real['blocked'])} words: "
          f"{len(failures)} failure(s), {len(info)} informational")
    if failures:
        raise SystemExit(1)


def stage_gallery_text():
    """Rewrites the gallery markup in index.html from the existing image manifest with the
    current GALLERY descriptions. No image is extracted or regenerated."""
    manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
    texts = {key: blurb for key, _, _, _, blurb in GALLERY}
    items = manifest["gallery"]
    for item in items:
        item["text"] = texts[item["key"]]
    SI.write_gallery(items, f"the synthetic {N.ORG} demonstration network")
    manifest["gallery"] = items
    (WORK / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print(f"gallery markup rewritten for {len(items)} existing figures")


STAGES = {"engine": stage_engine, "evidence": stage_evidence, "reports": stage_reports, "vlan": stage_vlan,
          "demo": stage_demo, "images": stage_images, "validate": stage_validate, "check": stage_check,
          "gallery-text": stage_gallery_text}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--platform", help="the Sysopty platform checkout (or set SYSOPTY_PLATFORM_ROOT)")
    ap.add_argument("--platform-python", help="a Python with the platform's requirements (or set SYSOPTY_PLATFORM_PYTHON)")
    a = ap.parse_args(argv)
    if a.platform:
        os.environ[G.PLATFORM_SETTING] = a.platform
    if a.platform_python:
        os.environ[G.PYTHON_SETTING] = a.platform_python
    WORK.mkdir(parents=True, exist_ok=True)
    for name, fn in STAGES.items():
        if a.stage in ("all", name):
            print(f"== {name}")
            fn()


if __name__ == "__main__":
    main()
