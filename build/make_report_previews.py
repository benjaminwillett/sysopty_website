"""Render the illustrative Sysopty report pages shown on the homepage (synthetic Riverside Technology Group data).

Usage: python build/make_report_previews.py <repo root> <work folder>
Writes public/img/hero/*.webp and public/img/gallery/*.webp. Needs Playwright (Chromium) and Pillow.
"""
import sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

repo = Path(sys.argv[1]).resolve()
work = Path(sys.argv[2]).resolve()
work.mkdir(parents=True, exist_ok=True)
fonts = (repo / "public/fonts").as_uri()

MARK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{s}" height="{s}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#d97706"/></linearGradient></defs><path d="M32 6 L58 20 L32 34 L6 20 Z" fill="url(#g)"/><path d="M8 32 L32 45 L56 32" fill="none" stroke="#f59e0b" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 44 L32 57 L56 44" fill="none" stroke="#d97706" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""

CSS = """
@font-face{font-family:Inter;src:url(FONTS/inter-latin-var.woff2);font-weight:100 900}
@font-face{font-family:Poppins;src:url(FONTS/poppins-latin-500.woff2);font-weight:500}
@font-face{font-family:Poppins;src:url(FONTS/poppins-latin-600.woff2);font-weight:600}
*{box-sizing:border-box}
body{margin:0;font:400 13px/1.45 Inter,sans-serif;color:#2a2010;background:#fff}
.page{display:flex;flex-direction:column;padding:38px 46px 26px;background:#fff;overflow:hidden}
.hdr{display:flex;justify-content:space-between;align-items:center;padding-bottom:12px;border-bottom:2px solid #d97706}
.logo{display:flex;align-items:center;gap:8px;font:600 19px/1 Poppins;color:#2a1c08}
.hdr .ctx{font-size:11.5px;color:#7a6a50;letter-spacing:.04em}
.pill{font:600 10px/1 Inter;letter-spacing:.12em;text-transform:uppercase;color:#92400e;border:1.5px solid #f59e0b;border-radius:5px;padding:7px 11px;background:#fffbeb}
.kicker{font:600 11px/1 Inter;letter-spacing:.16em;text-transform:uppercase;color:#b45309;margin:22px 0 8px}
h1{font:600 27px/1.15 Poppins;color:#1f180e;margin:0}
h2{font:600 15px/1.2 Poppins;color:#1f180e;margin:20px 0 8px}
.lead{color:#5c4a2e;margin-top:8px;max-width:760px;font-size:13.5px}
.ftr{margin-top:auto;padding-top:10px;border-top:1px solid #ecdfc6;display:flex;justify-content:space-between;font-size:10.5px;color:#7a6a50}
.tiles{display:grid;gap:12px;margin-top:16px}
.tile{border:1px solid #ecdfc6;border-radius:8px;padding:12px 14px;background:#fffcf5}
.tile b{display:block;font:600 26px/1 Poppins;color:#b45309}
.tile span{display:block;margin-top:6px;font-size:11.5px;color:#5c4a2e}
.tile.warn b{color:#1d4ed8}.tile.bad b{color:#b42318}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;font:600 10.5px/1.2 Inter;letter-spacing:.08em;text-transform:uppercase;color:#5c4a2e;background:#fbf3e2;padding:8px 10px;border-bottom:1px solid #e3d3b3}
td{padding:8px 10px;border-bottom:1px solid #efe6d3;vertical-align:top}
.mono{font-family:Consolas,"Cascadia Mono",monospace;font-size:11.5px}
.b{display:inline-block;font:700 9.5px/1 Inter;letter-spacing:.07em;text-transform:uppercase;color:#fff;border-radius:4px;padding:4px 7px;white-space:nowrap}
.high{background:#b42318}.med{background:#b9650f}.low{background:#6b7280}.ok{background:#18794e}.ver{background:#fff;color:#1d4ed8;border:1px solid #6b8fe8}.plain{background:#fff;color:#5c4a2e;border:1px solid #d8c9a8}
.call{border-left:5px solid #d97706;background:#fffbeb;padding:11px 14px;border-radius:0 6px 6px 0;margin-top:16px}
.call b{display:block;font:600 11px/1.2 Inter;letter-spacing:.08em;text-transform:uppercase;color:#92400e;margin-bottom:3px}
.cols{display:grid;gap:26px}
.muted{color:#7a6a50}
.bar{display:flex;height:16px;border-radius:4px;overflow:hidden;background:#fbf3e2}
.bar i{display:block;height:100%}
.legend{display:flex;gap:16px;font-size:11px;color:#5c4a2e;margin-top:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.cap{position:relative;height:14px;background:#fbf3e2;border-radius:3px;overflow:hidden;min-width:150px}
.cap i{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
""".replace("FONTS", fonts)


def chrome(body, w, h, page_no, ctx="Cloud &amp; Virtual Infrastructure As-Built · Riverside Technology Group"):
    return f"""<!doctype html><meta charset="utf-8"><style>{CSS}.page{{width:{w}px;height:{h}px}}</style>
<div class="page"><div class="hdr"><div class="logo">{MARK.format(s=24)}Sysopty</div><div class="ctx">{ctx}</div></div>
{body}
<div class="ftr"><span>Illustrative preview · synthetic data · Riverside Technology Group is a fictional organisation</span><span>{page_no}</span></div></div>"""


def rows(data):
    return "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in data)


def head(cols):
    return "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"


def tiles(items, cols=4):
    return f'<div class="tiles" style="grid-template-columns:repeat({cols},1fr)">' + "".join(
        f'<div class="tile {cls}"><b>{n}</b><span>{t}</span></div>' for n, t, cls in items) + "</div>"


B = lambda cls, text: f'<span class="b {cls}">{text}</span>'
M = lambda t: f'<span class="mono">{t}</span>'
HIGH, MED, LOW, VER = B("high", "High"), B("med", "Medium"), B("low", "Low"), B("ver", "Verify")

# Findings per platform: high, medium, low, needs verification. The pages below list exactly these.
COUNTS = [
    ("Microsoft Azure", 0, 1, 1, 1),
    ("Amazon AWS", 1, 1, 1, 0),
    ("Google Cloud Platform", 0, 1, 0, 1),
    ("VMware NSX", 0, 1, 1, 0),
    ("VMware ESXi and vCenter", 1, 1, 1, 0),
]
tot = [sum(c[i] for c in COUNTS) for i in (1, 2, 3, 4)]

# ---------------------------------------------------------------- portrait pages (A4 at 96 dpi)
PW, PH = 794, 1123

cover = f"""<!doctype html><meta charset="utf-8"><style>{CSS}
.page{{width:{PW}px;height:{PH}px;padding:0}}
.top{{padding:64px 62px 0;display:flex;justify-content:space-between;align-items:center}}
.top .logo{{font-size:30px;gap:12px}}
.band{{margin-top:190px;background:#1f180e;color:#fff;padding:44px 62px 48px;border-bottom:6px solid #f59e0b}}
.band .k{{font:600 11.5px/1 Inter;letter-spacing:.18em;text-transform:uppercase;color:#fcd34d;border-top:3px solid #f59e0b;display:inline-block;padding-top:12px}}
.band h1{{color:#fff;font-size:40px;margin-top:20px}}
.band p{{margin:10px 0 0;font-size:16px;color:#efe4cf}}
.band p.o{{font:600 17px/1.2 Poppins;color:#fff;margin-top:14px}}
.meta{{margin:auto 62px 70px}}
.meta td{{padding:10px 0;font-size:12.5px;border-bottom:1px solid #efe6d3}}
.meta td:first-child{{width:170px;font-weight:600;color:#4a3a22}}
</style><div class="page"><div class="top"><div class="logo">{MARK.format(s=40)}Sysopty</div><span class="pill">Illustrative preview · synthetic data</span></div>
<div class="band"><span class="k">Cloud &amp; virtual infrastructure as-built</span><h1>Riverside Technology Group</h1><p class="o">Cloud and virtual estate</p><p>Microsoft Azure, Amazon AWS, Google Cloud Platform, VMware NSX, VMware ESXi and vCenter</p></div>
<div class="meta"><table>{rows([
    ["Organisation", "Riverside Technology Group"],
    ["Document", "Cloud and Virtual Infrastructure As-Built"],
    ["Scope", "3 subscriptions, 2 accounts, 2 projects, 1 NSX Manager and 1 vCenter"],
    ["Evidence collected", "20 Oct 2026, read-only access to each platform"],
    ["Report sections", "Five platforms, with audit evidence and coverage"],
    ["Review status", "Not reviewed: illustrative layout"],
    ["Classification", "Public preview: synthetic data, fictional organisation"],
])}</table></div></div>"""

UNIT = 34
bar_rows = "".join(
    f"""<tr><td style="width:215px">{n}</td><td><div class="bar" style="width:{(h + m + l + v) * UNIT}px">
<i class="high" style="width:{h * UNIT}px"></i><i class="med" style="width:{m * UNIT}px"></i><i class="low" style="width:{l * UNIT}px"></i><i style="width:{v * UNIT}px;background:#a9bff5"></i></div></td>
<td style="width:44px;text-align:right;font-weight:600">{h + m + l + v}</td></tr>"""
    for n, h, m, l, v in COUNTS)

overview = chrome(f"""
<p class="kicker">Section 1</p><h1>Estate at a glance</h1>
{tiles([("5", "platforms documented", ""), ("301", "virtual machines and instances", ""), (str(tot[0] + tot[1] + tot[2]), "findings in total", "bad"), (str(tot[3]), "items needing verification", "warn")])}
<h2>What was found on each platform</h2>
<table>{head(["Platform", "Scope", "Networks", "Compute"])}{rows([
    ["Microsoft Azure", "3 subscriptions, 14 resource groups", "6 virtual networks", "46 virtual machines"],
    ["Amazon AWS", "2 accounts, 1 region", "3 VPCs", "31 instances"],
    ["Google Cloud Platform", "2 projects", "2 VPC networks", "12 instances"],
    ["VMware NSX", "1 NSX Manager", "18 segments, 4 gateways", "124 firewall rules"],
    ["VMware ESXi and vCenter", "1 vCenter, 2 clusters", "9 hosts", "212 virtual machines"],
])}</table>
<h2>Findings by platform</h2>
<table>{bar_rows}</table>
<div class="legend"><span><i class="high"></i>High</span><span><i class="med"></i>Medium</span><span><i class="low"></i>Low</span><span><i style="background:#a9bff5"></i>Needs verification</span></div>
<h2>Audit evidence and coverage</h2>
<table>{head(["Platform", "Access used", "Collected", "Coverage"])}{rows([
    ["Microsoft Azure", "Read-only role, 3 subscriptions", "20 Oct 2026", B("ok", "Complete")],
    ["Amazon AWS", "Read-only role, 2 accounts", "20 Oct 2026", B("ok", "Complete")],
    ["Google Cloud Platform", "Read-only role, 1 of 2 projects", "20 Oct 2026", B("ver", "Partial")],
    ["VMware NSX", "Read-only account, NSX Manager", "20 Oct 2026", B("ok", "Complete")],
    ["VMware ESXi and vCenter", "Read-only account, vCenter", "20 Oct 2026", B("ok", "Complete")],
])}</table>
<p class="muted" style="margin-top:8px;font-size:11.5px">Where access was not granted, the related sections are marked as needing verification and are not reported as complete.</p>""", PW, PH, "Page 3")


def cap(pct):
    colour = "#b42318" if pct >= 90 else ("#d08a1c" if pct >= 75 else "#d9a441")
    return f'<div class="cap"><i style="width:{pct}%;background:{colour}"></i></div>'


vsphere_p = chrome(f"""
<p class="kicker">Section 6 · VMware ESXi and vCenter</p><h1>Clusters and hosts</h1>
<p class="lead">Hosts, builds and cluster settings read from {M("vcsa-hq-01")}, with the virtual machines each cluster runs.</p>
{tiles([("2", "clusters in one vCenter", ""), ("9", "ESXi hosts", ""), ("212", "virtual machines", "")], 3)}
<h2>Clusters</h2>
<table>{head(["Cluster", "Hosts", "HA", "DRS", "Virtual machines"])}{rows([
    [M("HQ-Prod"), "6", "Enabled", "Fully automated", "187"],
    [M("HQ-Mgmt"), "3", "Enabled, admission control off", "Partially automated", "25"],
])}</table>
<h2>Hosts</h2>
<table>{head(["Host", "Cluster", "Model", "ESXi build", "Status"])}{rows([
    [M("esx-hq-p01 to p04"), "HQ-Prod", "R650", M("8.0 U2"), B("ok", "Current")],
    [M("esx-hq-p05, p06"), "HQ-Prod", "R640", M("7.0 U3"), B("high", "Out of security updates")],
    [M("esx-hq-m01 to m03"), "HQ-Mgmt", "R650", M("8.0 U2"), B("ok", "Current")],
])}</table>
<div class="call"><b>Mixed builds in one cluster</b>HQ-Prod runs two ESXi builds. Two hosts are on a build that no longer receives security updates.</div>
<h2>Finding</h2>
<table>{rows([
    ["<b>Finding</b>", "Hosts on a build that no longer receives security updates " + HIGH],
    ["<b>Affected</b>", M("esx-hq-p05") + " and " + M("esx-hq-p06") + ", cluster HQ-Prod"],
    ["<b>Evidence</b>", "Host inventory read from vCenter on 20 Oct 2026"],
    ["<b>Why it matters</b>", "The hosts run 61 production virtual machines and will receive no further fixes."],
    ["<b>Recommended action</b>", "Confirm hardware support for the newer release, then upgrade both hosts."],
])}</table>
<p class="muted" style="margin-top:12px;font-size:11px">Hardware models, builds and support dates on this page are placeholders.</p>""", PW, PH, "Page 34")

# ---------------------------------------------------------------- landscape figures
LW, LH = 1200, 830


def observations(items):
    return "<h2>Observations</h2><table>" + head(["Finding", "Where", "Severity"]) + rows(items) + "</table>"


azure = chrome(f"""
<p class="kicker">Section 2 · Microsoft Azure</p><h1>Subscriptions and virtual networks</h1>
{tiles([("3", "subscriptions in scope", ""), ("14", "resource groups", ""), ("6", "virtual networks with 21 subnets", ""), ("46", "virtual machines", "")])}
<h2>Virtual networks</h2>
<table>{head(["Virtual network", "Subscription", "Region", "Address space", "Subnets", "Peered with"])}{rows([
    [M("vnet-hub-01"), "rtg-shared", "Australia East", M("10.40.0.0/20"), "4", M("vnet-prod-01, vnet-nonprod-01")],
    [M("vnet-prod-01"), "rtg-prod", "Australia East", M("10.41.0.0/16"), "6", M("vnet-hub-01, vnet-nonprod-01")],
    [M("vnet-prod-dr-01"), "rtg-prod", "Australia Southeast", M("10.42.0.0/16"), "4", M("vnet-hub-01")],
    [M("vnet-nonprod-01"), "rtg-nonprod", "Australia East", M("10.45.0.0/16"), "5", M("vnet-hub-01, vnet-prod-01")],
    [M("vnet-sandbox-01"), "rtg-nonprod", "Australia East", M("10.46.0.0/20"), "1", "None"],
    [M("vnet-mgmt-01"), "rtg-shared", "Australia East", M("10.40.16.0/22"), "1", M("vnet-hub-01")],
])}</table>
{observations([
    ["Production and non-production networks are peered directly, with forwarded traffic allowed", M("vnet-prod-01, vnet-nonprod-01"), VER],
    ["Two virtual machines have a public address and no network security group on the subnet", M("rtg-nonprod"), MED],
    ["Three resource groups have no owner tag", M("rtg-shared, rtg-nonprod"), LOW],
])}""", LW, LH, "Page 8")

aws = chrome(f"""
<p class="kicker">Section 3 · Amazon AWS</p><h1>Accounts, VPCs and security groups</h1>
{tiles([("2", "accounts in scope", ""), ("3", "VPCs with 14 subnets", ""), ("31", "instances", ""), ("1", "security group open to any address on SSH", "bad")])}
<h2>VPCs</h2>
<table>{head(["VPC", "Account", "Region", "CIDR", "Subnets", "Instances", "Internet gateway"])}{rows([
    [M("vpc-prod"), "rtg-production", "ap-southeast-2", M("10.60.0.0/16"), "8", "24", "Yes"],
    [M("vpc-sandbox"), "rtg-sandbox", "ap-southeast-2", M("10.68.0.0/16"), "4", "5", "Yes"],
    [M("default"), "rtg-sandbox", "ap-southeast-2", M("172.31.0.0/16"), "2", "2", "Yes"],
])}</table>
<h2>Security groups that accept traffic from any address</h2>
<table>{head(["Security group", "VPC", "Port", "Source", "Attached to", "Review"])}{rows([
    [M("sg-web-public"), M("vpc-prod"), M("tcp/443"), M("0.0.0.0/0"), "Load balancer", B("ok", "Expected")],
    [M("sg-web-admin"), M("vpc-prod"), M("tcp/22"), M("0.0.0.0/0"), "4 instances", B("high", "SSH from any address")],
])}</table>
{observations([
    ["A security group allows SSH from any address", M("sg-web-admin, vpc-prod"), HIGH],
    ["The default VPC is still in use and holds two instances", M("rtg-sandbox"), MED],
    ["Three elastic IP addresses are not attached to anything", M("rtg-production"), LOW],
])}""", LW, LH, "Page 15")

gcp = chrome(f"""
<p class="kicker">Section 4 · Google Cloud Platform</p><h1>Projects, networks and firewall rules</h1>
{tiles([("2", "projects in scope", ""), ("1", "project read in full", "warn"), ("2", "VPC networks with 5 subnets", ""), ("12", "instances", "")])}
<h2>Projects and networks</h2>
<table>{head(["Project", "VPC network", "Region", "Subnets", "Instances", "Coverage"])}{rows([
    [M("rtg-analytics"), M("vpc-analytics"), "australia-southeast1", "3", "9", B("ok", "Complete")],
    [M("rtg-web"), M("vpc-web"), "australia-southeast1", "2", "3", B("ver", "Access not granted")],
])}</table>
<h2>Firewall rules, {M("vpc-analytics")}</h2>
<table>{head(["Rule", "Direction", "Source", "Ports", "Targets", "Review"])}{rows([
    [M("allow-iap-ssh"), "Ingress", M("35.235.240.0/20"), M("tcp/22"), "All instances", B("ok", "No issue")],
    [M("allow-lb-health"), "Ingress", "Load balancer ranges", M("tcp/8080"), M("tag: web"), B("ok", "No issue")],
    [M("allow-all-internal"), "Ingress", M("10.0.0.0/8"), "All", "All instances", B("med", "Wider than the VPC")],
    [M("deny-all-egress"), "Egress", "All", "All", M("tag: restricted"), B("ok", "No issue")],
])}</table>
{observations([
    ["An internal rule allows all ports from 10.0.0.0/8, which is wider than the ranges this VPC uses", M("allow-all-internal"), MED],
    ["Read access to one project was not granted, so its inventory comes from the organisation listing only", M("rtg-web"), VER],
])}""", LW, LH, "Page 21")

nsx = chrome(f"""
<p class="kicker">Section 5 · VMware NSX</p><h1>Gateways, segments and distributed firewall</h1>
{tiles([("4", "gateways: 1 tier-0 and 3 tier-1", ""), ("18", "segments", ""), ("124", "distributed firewall rules in 9 policies", ""), ("2", "rules that allow any source to any destination", "bad")])}
<div class="cols" style="grid-template-columns:1fr 1.25fr;margin-top:2px">
<div><h2>Gateways and segments</h2>
<table>{head(["Gateway", "Type", "Segments", "Uplink"])}{rows([
    [M("t0-hq"), "Tier-0", "0", "BGP to the core switches"],
    [M("t1-prod"), "Tier-1", "9", M("t0-hq")],
    [M("t1-nonprod"), "Tier-1", "6", M("t0-hq")],
    [M("t1-mgmt"), "Tier-1", "3", M("t0-hq")],
])}</table></div>
<div><h2>Distributed firewall policies</h2>
<table>{head(["Policy", "Category", "Rules", "Any to any", "Review"])}{rows([
    [M("Emergency-Quarantine"), "Emergency", "2", "0", B("ok", "No issue")],
    [M("Shared-Services"), "Infrastructure", "21", "0", B("ok", "No issue")],
    [M("Prod-to-NonProd"), "Environment", "8", "0", B("ok", "No issue")],
    [M("App-Finance"), "Application", "34", "0", B("ok", "No issue")],
    [M("App-Legacy"), "Application", "17", "2", B("med", "Any to any")],
    [M("Default-Layer3"), "Application", "1", "0", B("plain", "Default drop")],
])}</table>
<p class="muted" style="margin-top:6px;font-size:11px">Showing 6 of 9 policies.</p></div></div>
{observations([
    ["Two rules in an application policy allow any source to reach any destination", M("App-Legacy"), MED],
    ["Three segments have no connected virtual machines", M("t1-nonprod"), LOW],
])}""", LW, LH, "Page 27")

vsphere = chrome(f"""
<p class="kicker">Section 6 · VMware ESXi and vCenter</p><h1>Clusters, hosts and datastores</h1>
{tiles([("9", "ESXi hosts in 2 clusters", ""), ("212", "virtual machines", ""), ("2", "hosts out of security updates", "bad"), ("1", "datastore more than 90% full", "bad")])}
<div class="cols" style="grid-template-columns:1.15fr 1fr;margin-top:2px">
<div><h2>Clusters</h2>
<table>{head(["Cluster", "Hosts", "ESXi builds", "HA", "DRS", "VMs"])}{rows([
    [M("HQ-Prod"), "6", M("8.0 U2") + " × 4, " + M("7.0 U3") + " × 2", "Enabled", "Fully automated", "187"],
    [M("HQ-Mgmt"), "3", M("8.0 U2") + " × 3", "Admission control off", "Partially automated", "25"],
])}</table></div>
<div><h2>Datastores</h2>
<table>{head(["Datastore", "Capacity", "Used", ""])}{rows([
    [M("ds-prod-01"), "40 TB", "68%", cap(68)],
    [M("ds-prod-02"), "40 TB", "91%", cap(91)],
    [M("ds-prod-03"), "20 TB", "77%", cap(77)],
    [M("ds-mgmt-01"), "8 TB", "42%", cap(42)],
])}</table></div></div>
{observations([
    ["Two hosts run a build that no longer receives security updates", M("esx-hq-p05, esx-hq-p06"), HIGH],
    ["A production datastore is 91% full", M("ds-prod-02"), MED],
    ["Admission control is turned off, so a host failure may leave machines without capacity to restart", M("HQ-Mgmt"), LOW],
])}
<p class="muted" style="margin-top:10px;font-size:11px">Builds and support dates on this page are placeholders.</p>""", LW, LH, "Page 33")

PAGES = {
    "cover": (cover, PW, PH), "overview": (overview, PW, PH), "clusters": (vsphere_p, PW, PH),
    "azure": (azure, LW, LH), "aws": (aws, LW, LH), "gcp": (gcp, LW, LH), "nsx": (nsx, LW, LH), "vsphere": (vsphere, LW, LH),
}

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, (html, w, h) in PAGES.items():
        src = work / f"{name}.html"
        src.write_text(html, encoding="utf-8")
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        page.goto(src.as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(250)
        over = page.evaluate("(() => { const p = document.querySelector('.page'); return p.scrollHeight - p.clientHeight; })()")
        if over > 0:
            print("OVERFLOW", name, over)
        page.screenshot(path=str(work / f"{name}.png"), clip={"x": 0, "y": 0, "width": w, "height": h})
        page.close()
    browser.close()


def save(name, out, width):
    im = Image.open(work / f"{name}.png").convert("RGB")
    if width and width < im.width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "WEBP", quality=86, method=6)


img = repo / "public/img"
for src, dst in (("cover", "cover"), ("overview", "page2"), ("clusters", "page3")):
    for tag, width in (("480", 480), ("640", 640), ("1200", 1200), ("full", None)):
        save(src, img / f"hero/{dst}-{tag}.webp", width)

# Gallery thumbnails are a legible 3:2 crop from the top left of the page; the lightbox shows all of it.
CROP = {"azure": 0.62, "aws": 0.62, "gcp": 0.62, "nsx": 0.78, "vsphere": 0.78}
for name, frac in CROP.items():
    save(name, img / f"gallery/{name}-full.webp", None)
    im = Image.open(work / f"{name}.png").convert("RGB")
    w = round(im.width * frac)
    crop = im.crop((0, 0, w, round(w / 1.5)))
    for width in (800, 1400):
        crop.resize((width, round(width / 1.5)), Image.LANCZOS).save(img / f"gallery/{name}-{width}.webp", "WEBP", quality=86, method=6)
print("report previews written")
