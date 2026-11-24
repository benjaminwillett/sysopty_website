"""Runs the real, unmodified Sysopty engine over the synthetic evidence, in isolation.

1. The product's code is copied from the checkout into an engine folder by an allowlist:
   Python source plus four named reference files. Customer data that the engine would
   otherwise read during an offline run (support schedules, Panorama templates, the WAN
   export, site maps, sibling site folders, .env, host keys) is never copied, so it cannot
   be read. The copy is verified before use.
2. A synthetic customer and five sites are registered through the engine's own folder layout.
3. Evidence is written (evidence.py); each site's interactive map is built with the engine's
   own topology builder; then the engine's offline report command runs for each site.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE_ROOT = HERE.parents[1]
PLATFORM_SETTING = "SYSOPTY_PLATFORM_ROOT"     # the Sysopty platform checkout (read only)
PYTHON_SETTING = "SYSOPTY_PLATFORM_PYTHON"     # a Python with the platform's requirements
WORK = Path(os.environ.get("SYSOPTY_SYNTH_WORK") or
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SysoptySiteBuild" / "synthetic")
ENGINE = WORK / "engine"
CUSTOMER = "Riverside Technology Group"

# What the engine copy may contain besides *.py source.
REFERENCE_FILES = ["eol_models.csv", "topology_mapping_config.json", "reference/ieee/oui.csv",
                   "reference/ieee/oui.provenance.json", "reference/ieee/PROVENANCE.md",
                   "software_audit/lifecycle_data/cisco.json",
                   "software_audit/lifecycle_data/extreme.json", "software_audit/lifecycle_data/paloalto.json",
                   "software_audit/lifecycle_data/juniper.json", "software_audit/lifecycle_data/netscaler.json"]
PACKAGES = ["routing_topology", "vendors", "hardware_inventory", "software_audit", "asset_intelligence",
            "compliance_engine", "network_gap_analysis", "security_audit", "ip_inventory"]
# Generated from the platform's pinned plotly package: a clean checkout does not hold it.
PLOTLY_LIBRARY = "_assets/plotly.min.js"
REFERENCE_DATE = datetime(2026, 10, 20, 2, 0).timestamp()      # the evidence's collection date
# Never present in the copy (checked after copying).
FORBIDDEN = ["All_Sites", "Panorama", "known_hosts", "logs", "backups", "config", ".env", ".env.enc",
             "*Customer_Portal_Data_Services*.csv", "*Device Schedule*", "company_logo.png", "sysopty_site"]

sys.path.insert(0, str(HERE))
import network as N        # noqa: E402
import evidence as E       # noqa: E402


def platform_root() -> Path:
    """The platform checkout the build reads: explicit, never a folder that happens to be nearby."""
    value = os.environ.get(PLATFORM_SETTING)
    if not value:
        raise SystemExit(f"set {PLATFORM_SETTING} (or pass --platform) to the Sysopty platform checkout")
    root = Path(value).resolve()
    if not (root / "sysopty.py").is_file():
        raise SystemExit(f"{PLATFORM_SETTING}={root}: not a Sysopty platform checkout (no sysopty.py)")
    return root


def platform_python() -> str:
    """The engine runs in the platform's own environment: its pins differ from the website's."""
    return os.environ.get(PYTHON_SETTING) or sys.executable


def make_engine_copy() -> Path:
    TOOLS = platform_root()
    if ENGINE.exists():
        shutil.rmtree(ENGINE)
    ENGINE.mkdir(parents=True)
    for p in TOOLS.glob("*.py"):
        shutil.copy2(p, ENGINE / p.name)
    for pkg in PACKAGES:
        for p in (TOOLS / pkg).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            dest = ENGINE / p.relative_to(TOOLS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    for rel in REFERENCE_FILES:
        src = TOOLS / rel
        if not src.is_file():
            raise SystemExit(f"the platform checkout has no {rel}")
        dest = ENGINE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    # The engine dates the lifecycle data by its folder (asbuilt_collection evidence register): one fixed
    # date, or the same evidence would give a different report from every fresh clone.
    for rel in {Path(r).parent for r in REFERENCE_FILES} - {Path(".")}:
        os.utime(ENGINE / rel, (REFERENCE_DATE, REFERENCE_DATE))
    write_plotly_library()
    verify_engine_copy()
    return ENGINE


def write_plotly_library():
    dest = ENGINE / PLOTLY_LIBRARY
    dest.parent.mkdir(parents=True, exist_ok=True)
    code = ("import sys; from plotly.offline import get_plotlyjs; "
            "open(sys.argv[1], 'w', encoding='utf-8').write(get_plotlyjs())")
    r = subprocess.run([platform_python(), "-c", code, str(dest)], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"could not write the map library:\n{r.stderr[-2000:]}")


def verify_engine_copy():
    """The copy holds Python source and the allowlisted reference files only."""
    problems = [name for name in FORBIDDEN if any(ENGINE.glob(name))]
    allowed = {str(Path(r)) for r in REFERENCE_FILES} | {str(Path(PLOTLY_LIBRARY))}
    for p in ENGINE.rglob("*"):
        if p.is_file() and p.suffix != ".py" and str(p.relative_to(ENGINE)) not in allowed:
            problems.append(str(p.relative_to(ENGINE)))
    if problems:
        raise SystemExit(f"engine copy contains files outside the allowlist: {problems[:10]}")


def env() -> dict:
    # PYTHONPATH too: the engine uses the platform's own environment, and its evidence boundary refuses any other path.
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SYSOPTY_", "ASBUILT_")) and k != "PYTHONPATH"}
    e.update({
        "SYSOPTY_ARTIFACT_ROOT": str(WORK / "artifacts"),
        # Never this machine's configuration: a customer's conventions or WAN clouds must not reach the demo.
        "SYSOPTY_HOME": str(WORK / "home"),
        "SYSOPTY_NAMING_CONVENTIONS": "none",
        "SYSOPTY_CUSTOMER": CUSTOMER,
        "SYSOPTY_SITE_MAP": str(WORK / "site_map.json"),
        "SYSOPTY_WAN_EXPORT": str(WORK / "no-wan-export.csv"),     # does not exist: no WAN data
        "SYSOPTY_NO_ENV_FILES": "1",
        "ASBUILT_PANORAMA": "offline",
        "ASBUILT_LOGO": str(WORK / "sysopty_logo.png"),
        "ASBUILT_AUTHOR": "Sysopty",
        # The engine's explicit sample setting: the reports say on the cover, in every footer and in
        # their metadata that they are a public synthetic sample (never inferred from a name).
        "ASBUILT_PUBLICATION": "synthetic-sample",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return e


def run_engine(code: str) -> str:
    r = subprocess.run([platform_python(), "-c", code], cwd=ENGINE, env=env(), capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"engine step failed:\n{r.stdout[-3000:]}\n{r.stderr[-6000:]}")
    return r.stdout


def register_sites() -> dict:
    """The synthetic customer and sites, created through the engine's own folder layout."""
    if (WORK / "artifacts").exists():
        shutil.rmtree(WORK / "artifacts")
    (WORK / "site_map.json").write_text(json.dumps({
        "customers": {"RTG": {"name": CUSTOMER}},
        "sites": [{"name": s, "customer": "RTG"} for s in N.SITES]}, indent=1), encoding="utf-8")
    out = run_engine("import json, asbuilt_extras\n"
                     f"sites = {list(N.SITES)!r}\n"
                     "res = {}\n"
                     "for s in sites:\n"
                     "    l = asbuilt_extras._layout(s)\n"
                     "    for d in ('audits', 'discovery', 'raw', 'backups'): l.dir(d, create=True)\n"
                     "    res[s] = str(l.base)\n"
                     "print(json.dumps(res))")
    folders = json.loads(out.strip().splitlines()[-1])
    for s, f in folders.items():
        if WORK not in Path(f).parents:
            raise SystemExit(f"site folder outside the work area: {f}")
    return {s: Path(f) for s, f in folders.items()}


TOPOLOGY_CODE = """
import json, sys, pandas as pd, network_mapping as nm
spec = json.load(open(sys.argv[1], encoding="utf-8"))
df = pd.DataFrame(spec["rows"])
cdp = nm.dataframe_to_cdp_dict(df)
g = nm.build_network_topology(cdp, spec["vendor_map"], spec["platform_map"], spec["ip_map"],
                              spec["l2"], spec["l3"], set(spec["reporting"]))
nm.generate_topology_outputs(g, sys.argv[2], output_dir=sys.argv[3], open_html=False, export_visio=False)
print(g.number_of_nodes(), g.number_of_edges())
"""


def build_map(spec: dict, name: str, out_dir: Path, extra_env: dict | None = None) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / f"topology_inputs_{name}.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    r = subprocess.run([platform_python(), "-c", TOPOLOGY_CODE, str(spec_path), name, str(out_dir)], cwd=ENGINE,
                       env={**env(), **(extra_env or {})}, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"topology build failed for {name}:\n{r.stderr[-6000:]}")
    spec_path.unlink()
    return r.stdout.strip().splitlines()[-1]


# The July 2026 HQ collection (network.as_of_july), recorded as the site's history.
JULY_RUN = "20260720_020000"
JULY_CLOCK = "10:14:41.523 AEST Mon Jul 20 2026"
JULY_COLLECTED = (2026, 7, 20, 10, 14)
JULY_DOCUMENTED = (2026, 7, 20, 10, 40, 0)

# The engine's own document step, as the menu runs it after a live collection ("Document
# network": sysopty_services.document_from_collection with history recording on), on the July
# evidence. Two differences from a live run, both so the build never reaches anything outside
# this machine and the record carries the collection's date: NetBox and the interactive maps are
# not consulted (with_netbox / with_maps off), and the engine's clock reads the July time.
HISTORY_CODE = """
import datetime as _dt, json, os, sys
T = _dt.datetime(*json.loads(sys.argv[2]))

class _Clock(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return T if tz is None else T.replace(tzinfo=tz)

import sysopty_services as svc, asbuilt_extras, asbuilt_pdf, asbuilt_snapshot, asbuilt_findings, pdf_exporter
_real = _dt.datetime
for m in list(sys.modules.values()):
    if m is not _dt and getattr(m, "datetime", None) is _real:
        m.datetime = _Clock
svc.LIVE_GATHER = {"with_netbox": False, "with_maps": False}
site = sys.argv[1]
layout = asbuilt_extras._layout(site)
out = os.path.join(layout.dir("reports", create=True), "live_" + T.strftime("%Y%m%dT%H%M%S"))
os.makedirs(out, exist_ok=True)
# An engine that confines a report to its site's evidence (report_scope) is given that scope; an
# engine without it documents the saved evidence directly. Either way the same document step runs.
if hasattr(svc, "report_scope"):
    scope_cm = svc.scoped_report(layout, svc.report_scope(layout, output_dirs=[out, layout.base], evidence_dirs=()))
else:
    import contextlib
    scope_cm = contextlib.nullcontext()
with scope_cm:
    ev = svc.saved_evidence(site)
    mapping = (ev["mapping"], None, None, None, list(ev["netbox_devices"]), {}, {}, {}, {}, {}, ev["l3"], {})
    with asbuilt_extras.writing_to(os.path.join(out, "derived")):
        pdf = svc.document_from_collection(site, audit=ev["audit"], firewalls=ev["firewalls"], mapping_results=mapping,
                                           netbox_devices=ev["netbox_devices"],
                                           filename=os.path.join(out, f"devices_report_{site}.pdf"), wan=None)
hist = os.path.join(layout.base, "history")
print(json.dumps({"pdf": str(pdf), "history": sorted(os.path.relpath(os.path.join(r, f), hist)
                                                     for r, _, fs in os.walk(hist) for f in fs)}))
"""


def record_history(site: str, documented, engine: Path | None = None) -> dict:
    r = subprocess.run([platform_python(), "-c", HISTORY_CODE, site, json.dumps(list(documented))], cwd=engine or ENGINE,
                       env=env(), capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"history step failed:\n{r.stdout[-3000:]}\n{r.stderr[-6000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def generate_evidence(net) -> dict:
    folders = register_sites()
    # The July HQ collection first, recorded by the engine as the site's history.
    july = N.as_of_july(N.build())
    started = time.time()
    with E.collection(JULY_RUN, JULY_CLOCK, JULY_COLLECTED, lambda d: 108, 0.55):
        E.write_site(july, "RTG-HQ", folders["RTG-HQ"])
        (folders["RTG-HQ"] / "discovery" / "topology_inputs.json").unlink()
        build_map(E.topology_inputs(july, ["RTG-HQ"]), "RTG-HQ", folders["RTG-HQ"] / "discovery")
        E.set_collection_times(folders["RTG-HQ"], started)
    hist = record_history("RTG-HQ", JULY_DOCUMENTED)
    print(f"RTG-HQ: July collection recorded ({len(hist['history'])} history files)")
    # The customer's supplied files (WAN service export, support schedule): one customer folder.
    customer = {b.parent for b in folders.values()}
    if len(customer) != 1:
        raise SystemExit(f"sites are not in one customer folder: {sorted(map(str, customer))}")
    E.write_supplemental(net, next(iter(customer)) / "_supplemental")
    E.set_collection_times(next(iter(customer)) / "_supplemental", 0, E.SUPPLIED)
    for site, base in folders.items():
        started = time.time()
        E.write_site(net, site, base)
        (base / "discovery" / "topology_inputs.json").unlink()
        print(f"{site}: map {build_map(E.topology_inputs(net, [site]), site, base / 'discovery')} (nodes edges)")
        E.set_collection_times(base, started)
    enterprise = WORK / "enterprise_map"
    if enterprise.exists():
        shutil.rmtree(enterprise)
    print(f"enterprise map: {build_map(E.topology_inputs(net, list(N.SITES)), N.ORG, enterprise)}")
    return folders


@contextmanager
def evidence_drive():
    """The artifact root as the report should print it.

    A report's document-control page records the folder its evidence was read from
    . Read from the build folder, that is this workstation's profile
    path, with the user name. On Windows the build folder is mapped to a spare drive letter
    for the run (subst, removed afterwards), so the report records R:\\artifacts\\... instead.
    Elsewhere, or with no spare letter, the build folder is used and the review catches it."""
    if os.name != "nt":
        yield str(WORK / "artifacts")
        return
    letter = next((f"{c}:" for c in "RSTUVWXYZ" if not os.path.exists(f"{c}:\\")), None)
    if letter is None or subprocess.run(["subst", letter, str(WORK)], capture_output=True).returncode:
        yield str(WORK / "artifacts")
        return
    try:
        yield f"{letter}\\artifacts"
    finally:
        subprocess.run(["subst", letter, "/D"], capture_output=True)


def run_reports(sites=None) -> dict:
    out = WORK / "reports"
    if out.exists():
        shutil.rmtree(out)
    pdfs = {}
    with evidence_drive() as root:
        print(f"evidence root for the reports: {root}")
        for site in sites or N.SITES:
            pdfs[site] = _run_report(site, out, root)
    return pdfs


def _run_report(site, out, root) -> Path:
    r = subprocess.run([platform_python(), "sysopty.py", "report", "--site", site, "--output", str(out / site),
                        "--runs-dir", str(WORK / "runs"), "--json", str(WORK / f"report_run_{site}.json")],
                       cwd=ENGINE, env={**env(), "SYSOPTY_ARTIFACT_ROOT": root},
                       capture_output=True, text=True, encoding="utf-8")
    found = sorted((out / site).rglob("devices_report_*.pdf"))
    status = [ln for ln in r.stdout.splitlines() if "Status:" in ln or "validation" in ln.lower()]
    print(f"{site}: {'; '.join(s.strip() for s in status[:2])}", flush=True)
    if not found or r.returncode:
        raise SystemExit(f"report for {site} failed (exit {r.returncode}):\n{r.stdout[-3000:]}\n{r.stderr[-4000:]}")
    return found[-1]
