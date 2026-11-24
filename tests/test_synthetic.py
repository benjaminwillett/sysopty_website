"""The synthetic demonstration network: design consistency, generated evidence, and that the
validator really detects each kind of fault (each check is exercised with an injected fault)."""
import copy
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = os.environ.get("SYSOPTY_PLATFORM_ROOT")
needs_platform = pytest.mark.skipif(not PLATFORM, reason="reads the engine's parsers: set SYSOPTY_PLATFORM_ROOT to a platform checkout")
sys.path.insert(0, str(ROOT / "build" / "synthetic"))
pd = pytest.importorskip("pandas")
import network as N    # noqa: E402
import evidence as E   # noqa: E402
import validate as V   # noqa: E402


@pytest.fixture(scope="module")
def net():
    return N.build()


def test_build_is_deterministic():
    a, b = N.build(), N.build()
    assert list(a.devices) == list(b.devices)
    assert [vars(x) for x in a.links] == [vars(x) for x in b.links]
    assert N.synthetic_serial("c9500-hq-c01") == N.synthetic_serial("c9500-hq-c01")


def test_inventory_matches_the_design(net):
    roles = {}
    for d in net.devices.values():
        roles[d.role] = roles.get(d.role, 0) + 1
    assert roles == {"core": 8, "distribution": 2, "access": 34, "firewall": 8, "router": 7, "ap": 60, "endpoint": 662}
    assert len(net.devices) == 781                 # 124 infrastructure, APs and early endpoints + 657 endpoints
    assert {d.vendor for d in net.devices.values() if d.kind in ("switch", "firewall")} == \
        {"cisco", "extreme", "palo", "fortinet"}
    assert {d.site for d in net.devices.values()} == set(N.SITES)


def test_the_network_is_consistent(net):
    assert V.validate_network(net) == []


def _mutate(net, fn):
    n = copy.deepcopy(net)
    fn(n)
    return V.validate_network(n)


@pytest.mark.parametrize("fault,expected", [
    (lambda n: setattr(n.devices["c9300-hq-a02"], "mgmt_ip", n.devices["c9300-hq-a01"].mgmt_ip), "duplicate management address"),
    (lambda n: setattr(n.links[0], "b", "no-such-device"), "dangling link endpoint"),
    (lambda n: setattr(n.links[0], "a_port", "GigabitEthernet9"), "does not fit"),
    (lambda n: n.links.append(copy.deepcopy(n.links[0])), "used by 2 links"),
    (lambda n: n.links[0].vlans.append(42), "not defined at"),
    (lambda n: n.devices["c9500-hq-c01"].svis.__setitem__("Vlan20", "10.99.20.2/24"), "outside VLAN 20"),
    (lambda n: n.devices["c9500-hq-c02"].svis.__setitem__("Vlan20", "10.10.20.2/24"), "assigned 2 times"),
    (lambda n: n.devices["pa5410-dc1-f01"].fw_interfaces.append(("ae1.77", "lab", 77, "10.21.77.1/24")),
     "not carried by its ae1 members"),
    (lambda n: n.devices["pa5410-dc1-f01"].fw_interfaces.append(("ae1.41", "", 41, "10.21.141.1/24")), "no zone"),
    (lambda n: n.devices["pa445-sth-f01"].fw_interfaces.append(("ethernet1/9", "untrust", 0, "8.8.8.8/29")),
     "non-documentation public address"),
])
def test_validator_detects_each_fault(net, fault, expected):
    problems = _mutate(net, fault)
    assert any(expected in p for p in problems), problems


def test_hostnames_classify_correctly_for_the_engine(net):
    scheme = re.compile(r"^((c9500|c9300|c9200|vsp7520|vsp5520|vsp5420|pa\d{3,4}|fg\d{2,3}f|c4451|c1111)"
                        r"-(hq|dc1|nth|sth|brn)-[cafr]\d\d|(hq|dc1|nth|sth|brn)-[a-z0-9]+-ap\d\d"
                        r"|(hq|dc1|nth|sth|brn)-(prn|nvr|ups|cam|bms)-\d\d|(hq|sth)-door-ctl\d\d"
                        r"|(hq|nth|sth|brn)-(ws|ph)-\d{4})$")
    for d in net.devices.values():
        # Every name follows the synthetic scheme exactly (so none can match the engine's
        # special-cased prefixes, such as "ws-", which it treats as infrastructure).
        assert scheme.match(d.hostname), d.hostname
        if d.role in ("core", "distribution"):
            assert re.search(r"-c\d\d$", d.hostname)
        if d.role == "access":
            assert re.search(r"-a\d\d$", d.hostname)
        if d.role == "ap":
            assert re.search(r"-ap\d\d$", d.hostname)


def test_evidence_files_for_every_site(net, tmp_path):
    for site in N.SITES:
        E.write_site(net, site, tmp_path / site)
        names = {p.name for p in (tmp_path / site).rglob("*")}
        assert f"network_mapping_output_{site}.xlsx" in names
        assert any(n.endswith(f"_switch_audit_output_{site}.xlsx") for n in names)
    hq = tmp_path / "RTG-HQ"
    audit = pd.read_excel(hq / "audits" / "cisco_switch_audit_output_RTG-HQ.xlsx")
    assert set(audit["Hostname"]) >= {"c9500-hq-c01", "c9300-hq-c03", "c9300-hq-a01"}
    assert (audit.groupby("Hostname").size()["c9300-hq-a01"]) == 2        # a two-member stack
    assert all(str(v).startswith("[") for v in audit["interface_ip"])
    mapping = pd.read_excel(hq / "discovery" / "network_mapping_output_RTG-HQ.xlsx")
    links = set(zip(mapping["Hostname"], mapping["Switch Interface"], mapping["Neighbour"], mapping["Switch Port ID"]))
    # both ends of a switch-to-switch link are reported (the engine then marks it Confirmed)
    for h, p, n, q in links:
        if n in set(audit["Hostname"]) and h in set(audit["Hostname"]):
            assert (n, q, h, p) in links
    assert V.validate_evidence(tmp_path) == []


def test_firewall_output_parses_with_the_documented_columns(net):
    text = E.palo_raw(net, net.devices["pa5410-dc1-f01"])
    section = text.split("=== show interface all ===")[1].split("\n=== ")[0]
    header = next(l for l in section.splitlines() if "name" in l and "vsys" in l)
    rows = [l for l in section.splitlines() if l.startswith("ae1.")]
    cut = header.index("address")
    addresses = [r[cut:].strip() for r in rows]
    assert all(re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", a) for a in addresses), addresses
    assert len(header) > max(len(r.rstrip()) for r in rows)             # header padded past the longest address


def test_backups_pass_the_engines_completeness_gate(net):
    for host, fn in (("c9300-hq-a01", E.cisco_backup), ("vsp5520-sth-c01", E.extreme_backup),
                     ("pa445-sth-f01", E.palo_backup)):
        text = fn(net, net.devices[host]).strip().splitlines()
        assert len([l for l in text if l.strip()]) > 20
        assert re.search(r"[#>]$", text[-1]) and host in text[-1]


def test_no_credentials_are_generated(net):
    for d in net.devices.values():
        if not d.collected:
            continue
        for fn in (E.cisco_backup, E.extreme_backup, E.palo_backup):
            if (fn is E.cisco_backup and d.vendor == "cisco" and d.kind == "switch") or \
                    (fn is E.extreme_backup and d.vendor == "extreme") or (fn is E.palo_backup and d.vendor == "palo"):
                assert not V.SECRET_RE.search(fn(net, d)), d.hostname


def test_public_addresses_are_documentation_ranges(net):
    import ipaddress
    for d in net.devices.values():
        for _, _, _, a in d.fw_interfaces:
            if a != "ha":
                ip = ipaddress.ip_interface(a).ip
                assert ip.is_private or any(ip in r for r in V.DOC_RANGES), (d.hostname, a)


RULES = Path(os.environ.get("SYSOPTY_PRIVATE_RULES") or ROOT / "no-private-rules")


@pytest.mark.skipif(not RULES.exists(), reason="private rules are only on the asset build machine")
def test_synthetic_evidence_has_no_customer_words(net, tmp_path):
    blocked = json.loads(RULES.read_text(encoding="utf-8"))["blocklist"]
    for site in N.SITES:
        E.write_site(net, site, tmp_path / site)
    assert V.validate_evidence(tmp_path, blocked) == []
    names = " ".join(net.devices).lower()
    assert not [i for i, w in enumerate(blocked) if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", names)]


# ------------------------------------------------------------------ carrier services, HA, written evidence
def _wan_with(change):
    rows = [list(r) for r in N.WAN_SERVICES]
    change(rows)
    return [tuple(r) for r in rows]


@pytest.mark.parametrize("change,expected", [
    (lambda r: r[0].__setitem__(5, ("c9300-hq-a01",)), "must end on one uncollected carrier CPE"),
    (lambda r: r[0].__setitem__(5, ("no-such-cpe",)), "does not exist"),
    (lambda r: r[3].__setitem__(5, ("c9500-hq-c02", "c9300-nth-c01")), "no carrier EPL link"),
    (lambda r: r[2].__setitem__(1, "IP address block 10.10.0.0/29"), "not a documentation range"),
    (lambda r: r[2].__setitem__(1, "IP address block 198.51.100.200/29"), "does not hold the RTG-HQ firewall"),
    (lambda r: r[13].__setitem__(4, "500 Mbps"), "different details at its two ends"),
    (lambda r: r.pop(1), "carrier CPE c4451-hq-r02 has no service"),
    (lambda r: r[0].__setitem__(3, "ACME-123456"), "not in the synthetic format"),
])
def test_validator_detects_each_carrier_service_fault(net, monkeypatch, change, expected):
    monkeypatch.setattr(N, "WAN_SERVICES", _wan_with(change))
    problems = V.validate_network(net)
    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize("fault,expected", [
    (lambda n: setattr(n.devices["pa3410-hq-f02"], "ha_state", "active"), "states active/active"),
    (lambda n: setattr(n.devices["pa3410-hq-f02"], "platform", "pa5410"), "differ in model or software"),
    (lambda n: setattr(n.devices["pa3410-hq-f02"], "ha_peer", "pa5410-dc1-f01"), "not each other's peer"),
])
def test_validator_detects_each_ha_fault(net, fault, expected):
    problems = _mutate(net, fault)
    assert any(expected in p for p in problems), problems


@pytest.fixture()
def written(net, tmp_path):
    """The evidence for every site and the customer's supplied files, as the build writes them."""
    root = tmp_path / "artifacts"
    customer = root / "Riverside Technology Group [RTG]"
    for site in N.SITES:
        E.write_site(net, site, customer / site)
    E.write_supplemental(net, customer / "_supplemental")
    return root, customer


def test_written_evidence_agrees_with_the_design(net, written):
    root, _ = written
    assert V.validate_written(net, root, history=False) == []
    assert V.validate_evidence(root) == []


def _edit_xlsx(path, fn):
    df = pd.read_excel(path, dtype=str).fillna("")
    fn(df)
    df.to_excel(path, index=False)


def _edit_text(path, old, new):
    t = path.read_text(encoding="utf-8")
    assert old in t
    path.write_text(t.replace(old, new, 1), encoding="utf-8")


def _set(df, rows, col, value):
    df.loc[rows[0], col] = value


def _append(path, line):
    path.write_text(path.read_text(encoding="utf-8") + line, encoding="utf-8")


PORTS = ("RTG-HQ", "audits", "port_status_audit_output_RTG-HQ.xlsx")
WRITTEN_FAULTS = {
    "schedule serial missing": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE,
                                                     lambda d: d.drop(d.index[0], inplace=True)), "has no record"),
    "schedule serial invented": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE,
                                                      lambda d: _set(d, d.index, "Serial No", "SYN00000000")),
                                 "is no collected asset"),
    "schedule dates reversed": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE,
                                                     lambda d: _set(d, d.index, "Actual End Date", "2020-01-01")),
                                "invalid dates"),
    "lifecycle claimed verified": (lambda c: (c / "_supplemental" / E.SCHEDULE_RECORD).write_text(
        json.dumps(dict(E.SCHEDULE_VERIFIED, source="vendor end-of-life notices")), encoding="utf-8"),
        "claims lifecycle verification"),
    "verification record named for the workbook": (lambda c: (c / "_supplemental" / E.SCHEDULE_RECORD).rename(
        c / "_supplemental" / (E.SCHEDULE + ".verified.json")), "expected only"),
    "stray verification record":(lambda c: (c / "RTG-HQ" / "lifecycle.verified.json").write_text("{}", encoding="utf-8"),
                                  "unexpected verification record"),
    "circuit not in the design": (lambda c: _append(c / "_supplemental" / E.WAN_EXPORT,
                                                    "RTG-HQ,Extra,Internet,Active,SYN-INT-HQ-0099,100 Mbps,x,-,2024-07-01\n"),
                                  "not in the design"),
    "port up without a link": (lambda c: _edit_xlsx(c.joinpath(*PORTS), lambda d: _set(
        d, d[d["Status"] == "notconnect"].index, "Status", "connected")), "up in the port status audit without a link"),
    "linked port down": (lambda c: _edit_xlsx(c.joinpath(*PORTS), lambda d: _set(
        d, d[d["Status"] == "connected"].index, "Status", "notconnect")), "not up in the port status audit"),
    "stack member temperature missing": (lambda c: _edit_text(c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a01.txt",
                                                              "Switch 2: SYSTEM TEMPERATURE is OK\n", ""),
                                         "temperature not reported for every stack member"),
    "HA compatibility contradicts versions": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "palo_raw_pa3410-hq-f01.txt", "Build Compatibility           : Match",
        "Build Compatibility           : Mismatch"), "HA peer version and compatibility disagree"),
    "credential in a workbook": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE,
                                                      lambda d: _set(d, d.index, "SLA", "x\npassword hunter2")),
                                 "looks like a credential"),
}


@pytest.mark.parametrize("name", sorted(WRITTEN_FAULTS))
def test_validator_detects_each_written_evidence_fault(net, written, name):
    root, customer = written
    fault, expected = WRITTEN_FAULTS[name]
    fault(customer)
    problems = V.validate_written(net, root, history=False) + V.validate_evidence(root)
    assert any(expected in p for p in problems), problems


def test_voss_bridge_identifiers_are_checked_by_their_mac(tmp_path):
    (tmp_path / "a.txt").write_text("Cist Root : 80:00:02:72:74:aa:bb:cc\n", encoding="utf-8")
    assert V.validate_evidence(tmp_path) == []
    (tmp_path / "a.txt").write_text("Cist Root : 80:00:00:1b:21:aa:bb:cc\n", encoding="utf-8")   # a vendor MAC
    assert any("not locally administered" in p for p in V.validate_evidence(tmp_path))


@needs_platform
def test_voss_spanning_tree_and_counters_parse_with_the_engines_parsers(net):
    sys.path.insert(0, PLATFORM)
    import asbuilt_facts as af
    d = net.devices["vsp5420-hq-a09"]
    raw = E.voss_asbuilt_raw(net, d)
    sect = lambda name: raw.split(f"=== {name} ===\n", 1)[1].split("\n=== ", 1)[0]
    e = af.extreme_stp_evidence("", "", sect("show spanning-tree mstp status"),
                                sect("show spanning-tree mstp port role"), fabric=True)
    assert e["status"] == "collected" and e["protocol"] == "MSTP"
    assert e["instances"]["CIST"]["is_root"] is False                  # the HQ core is the root
    assert e["instances"]["CIST"]["root_id"].endswith(N.synthetic_mac("c9500-hq-c01"))
    roles = sorted((x["role"], x["state"]) for x in e["ports"])
    assert ("root", "forwarding") in roles and ("alternate", "discarding") in roles
    # every other spanning-tree port is an edge port the switch is designated for: AP, desks, devices
    edge = [p for p, o, _, _ in N.neighbours(net, d.hostname) if net.devices[o].kind != "switch"]
    assert roles.count(("designated", "forwarding")) == len(edge)
    ctr = af.parse_voss_interface_counters(sect("show interfaces gigabitEthernet error"),
                                           sect("show interfaces gigabitEthernet statistics"))
    assert set(ctr["interfaces"]) == set(E.port_vlans(net, d.hostname))


def test_the_july_design_is_consistent_and_differs_as_recorded():
    july = N.as_of_july(N.build())
    assert V.validate_network(july) == []
    now = N.build()
    assert july.devices["c9500-hq-c01"].software == "17.9.4a" and now.devices["c9500-hq-c01"].software == "17.9.5"
    assert "hq-blb-ap24" not in july.devices and "hq-blb-ap24" in now.devices
    assert "\nip http server\n" in E.cisco_backup(july, july.devices["c9300-hq-c03"])
    assert "\nno ip http server\n" in E.cisco_backup(now, now.devices["c9300-hq-c03"])
    others = lambda n: {h for h, d in n.devices.items() if d.site != "RTG-HQ"}
    assert others(july) == others(now)
    assert len(N.JULY_CHANGES) == 8
    assert july.devices["c9300-hq-a03"].psu_fault == "" and now.devices["c9300-hq-a03"].psu_fault == "1B"


def _july_snapshot(customer, **change):
    snaps = customer / "RTG-HQ" / "history" / "snapshots"
    snaps.mkdir(parents=True)
    devices = {"a": {"name": "c9500-hq-c01", "software": "17.9.4a"}, "b": {"name": "c9500-hq-c02", "software": "17.9.4a"},
               "c": {"name": "c9300-hq-a01", "software": "17.9.5"}}
    snap = {"generated": "2026-07-20 10:40:00", "devices": devices}
    snap.update(change)
    (snaps / "snapshot_20260720_104000.json").write_text(json.dumps(snap), encoding="utf-8")


@pytest.mark.parametrize("change,expected", [
    ({}, None),
    ({"generated": "2026-10-26 12:54:28"}, "is not the July collection"),
    ({"devices": {"a": {"name": "c9500-hq-c01", "software": "17.9.5"}}}, "the July design says 17.9.4a"),
])
def test_validator_checks_the_recorded_history(net, written, change, expected):
    root, customer = written
    _july_snapshot(customer, **change)
    problems = V.validate_written(net, root)
    assert (expected is None and problems == []) or any(expected in p for p in problems), problems


def test_validator_requires_the_history_when_asked(net, written):
    root, _ = written
    assert any("no earlier collection recorded" in p for p in V.validate_written(net, root))


# ------------------------------------------------------------------ the generated report against the design
def _report_text(net, site="RTG-HQ"):
    """The parts of a report validate_report reads, as the engine prints them, consistent with the design."""
    devs = [d for d in net.site_devices(site) if d.collected and d.kind in ("switch", "firewall")]
    brand = {"cisco": "Cisco", "extreme": "Extreme Networks", "palo": "Palo Alto Networks"}
    def support(h):
        rec = N.SUPPORT_EXCEPTIONS.get(h, ("Active",))
        return "No matching record - - -" if rec is None else \
            "Expired 8x5xNBD 22 Aug 2023 21 Aug 2026" if rec[0] == "Expired" else "Covered 8x5xNBD 01 Jul 2025 30 Jun 2027"
    covered = "\r\n".join(f"{d.hostname} {m if d.kind == 'switch' else '-'} {brand[d.vendor]} {d.model} "
                          f"{N.synthetic_serial(d.hostname, m)} {support(d.hostname)}"
                          for d in devs for m in range(1, (d.members if d.kind == "switch" else 1) + 1))
    circuits = "\r\n".join(f"{svc} {kind} Active {c}" for s, svc, kind, c, _, _ in N.WAN_SERVICES if s == site)
    return (f"Collection {len(devs)} of {len(devs)} devices complete in every capability; 284 of 284 capabilities\r\n"
            "Findings 5 in total: 2 high, 2 medium, 1 low, 0 info\r\n"
            f"{V.unused_ports_up(net, site)} unused ports are left enabled\r\n"
            f"3.1 WAN services\r\n{circuits}\r\n"
            "Reference data status: 0 of 22 rows rest on a verified vendor source\r\n"
            f"{covered}\r\n"
            "Compared with the snapshot generated 2026-07-20 10:40:00 (snapshot_20260720_104000.json)\r\n"
            "software 0 0 2 0 0 0\r\n"
            "Summary of findings\r\n"
            "HIGH F-HW-AAAAAA c9300-hq-a03\r\nPower, fan or temperature faults.\r\n"
            "HIGH F-SUP-BBBBBB c9300-hq-a05\r\nSupport has ended.\r\n"
            "MEDIUM F-SUP-CCCCCC c9300-hq-a06\r\nHardware not on the schedule.\r\n"
            "MEDIUM F-SEC-13E8DF 8 devices (vsp5420-hq-a09,\r\n\r\nvsp5420-hq-a10, …)\r\n"
            "Access ports have no BPDU guard on vsp5420-hq-a09.\r\n"
            "LOW F-MGT-79E9FF 8 devices (vsp5420-hq-a09)\r\nNTP servers differ between switches.\r\n"
            "Detailed findings\r\n"
            "F-HW-AAAAAA Power, fan or temperature faults: c9300-hq-a03 power supply PSU 1B (member 1,\r\n"
            "slot B: Bad).\r\nConfidence Confirmed\r\nEvidence E-LIVE-11111\r\n"
            "F-SUP-BBBBBB Support has ended (21 Aug 2026) for c9300-hq-a05 (1 serials), although the schedule "
            "still lists them as live devices.\r\nConfidence Confirmed\r\nEvidence E-SUPP-22222\r\n"
            "F-SUP-CCCCCC Hardware whose serials are not on the support schedule (RTG_support_schedule_20261019.xlsx), "
            "which does list other equipment of the same manufacturer: c9300-hq-a06.\r\nConfidence Probable\r\n"
            "Evidence E-SUPP-22222\r\n"
            "F-SEC-13E8DF Access ports have no BPDU guard.\r\nConfidence Confirmed\r\nEvidence E-BACK-1251F\r\n"
            "F-MGT-79E9FF NTP servers differ.\r\nConfidence Confirmed\r\nEvidence E-BACK-C2556\r\n")


def test_report_checks_accept_a_consistent_report(net):
    assert V.validate_report(net, "RTG-HQ", _report_text(net)) == []


@pytest.mark.parametrize("old,new,expected", [
    ("22 of 22 devices", "21 of 22 devices", "devices fully collected"),
    ("284 of 284", "283 of 284", "capabilities complete"),
    ("Findings 5 in total: 2 high, 2 medium, 1 low", "Findings 5 in total: 1 high, 3 medium, 1 low", "findings stated"),
    ("Access ports have no BPDU guard on vsp5420-hq-a09.", "Something else.", "BPDU guard finding is missing"),
    ("Confidence Confirmed\r\nEvidence E-BACK-C2556", "Evidence E-BACK-C2556", "no detailed record with a confidence"),
    ("Evidence E-BACK-1251F", "Evidence (none)", "cites no evidence"),
    (" SYN-EPL-0902", " SYN-EPL-0999", "WAN circuits in the report"),
    ("0 of 22 rows rest on a verified", "3 of 22 rows rest on a verified", "claim a verified vendor source"),
    (" Covered 8x5xNBD", " No matching record 8x5xNBD", "does not reconcile with the design"),
    (" Expired 8x5xNBD", " Covered 8x5xNBD", "does not reconcile with the design"),
    ("c9300-hq-a03 power supply PSU 1B", "c9300-hq-a03 power supply PSU 1A", "no hardware finding for c9300-hq-a03"),
    ("slot B: Bad).", "slot B: Bad); c9300-hq-a04 power supply PSU 1A (member 1, slot A: Bad).",
     "names more than c9300-hq-a03"),
    ("Support has ended (21 Aug 2026)", "Support has ended (21 Sep 2026)", "no expired-support finding for c9300-hq-a05"),
    ("same manufacturer: c9300-hq-a06.", "same manufacturer: c9300-hq-a07.", "no unrecorded-support finding"),
    ("Evidence E-LIVE-11111", "Evidence E-LIVE-11111 Tracking New since 2026-10-26",
     "findings dated after the 2026-10-20 collection"),
    ("software 0 0 2 0 0 0", "software 0 0 0 0 0 0", "core upgrades are not among the changes"),
    ("Compared with the snapshot generated 2026-07-20", "No previous comparable collection", "no comparison with the July"),
    ("Summary of findings", "Spanning tree not collected for: vsp5420-hq-a09\r\nSummary of findings", "spanning tree reported"),
])
def test_report_checks_detect_each_fault(net, old, new, expected):
    text = _report_text(net)
    assert old in text
    problems = V.validate_report(net, "RTG-HQ", text.replace(old, new, 1))
    assert any(expected in p for p in problems), problems


# ------------------------------------------------------------------ support coverage and power supply scenarios
@pytest.mark.parametrize("change,expected", [
    (lambda: N.PSU_FAULTS.update({"c9300-hq-a03": "3B"}), "has no bay 3B"),
    (lambda: N.PSU_FAULTS.update({"hq-prn-01": "1B"}), "not a collected Cisco switch"),
    (lambda: N.SUPPORT_EXCEPTIONS.update({"c9300-hq-a05": ("Expired", "2023-08-22", "2026-12-31")}),
     "must end before the collection"),
    (lambda: N.SUPPORT_EXCEPTIONS.pop("c9300-hq-a06"), "need one expired contract and one device with no record"),
    (lambda: N.SUPPORT_EXCEPTIONS.update({"c9300-hq-a03": None}), "on different devices"),
])
def test_validator_detects_each_risk_scenario_fault(net, monkeypatch, change, expected):
    monkeypatch.setattr(N, "PSU_FAULTS", dict(N.PSU_FAULTS))
    monkeypatch.setattr(N, "SUPPORT_EXCEPTIONS", dict(N.SUPPORT_EXCEPTIONS))
    change()
    problems = V.validate_network(net)
    assert any(expected in p for p in problems), problems


@needs_platform
def test_the_scenarios_in_the_written_evidence(net, written):
    """Expired by its end date, no record at all, every other asset active; one bad supply beside a good one."""
    _, customer = written
    rows = pd.read_excel(customer / "_supplemental" / E.SCHEDULE, dtype=str).set_index("Serial No")
    a05, a06 = N.synthetic_serial("c9300-hq-a05"), N.synthetic_serial("c9300-hq-a06")
    assert rows.loc[a05, "Actual End Date"] == "2026-08-21" and rows.loc[a05, "Device Support Status"] == "Expired"
    assert (pd.Timestamp("2026-10-20") - pd.Timestamp("2026-08-21")).days == 60
    assert a06 not in rows.index
    others = rows.drop(index=a05)
    assert (others["Device Support Status"] == "Active").all() and (others["Actual End Date"] > "2026-10-20").all()
    sys.path.insert(0, PLATFORM)
    import asbuilt_facts as af
    raw = (customer / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a03.txt").read_text(encoding="utf-8")
    env = raw.split("=== show environment all ===\n")[1].split("\n\n=== ")[0]
    assert [(x["name"], x["status"]) for x in af.parse_cisco_environment(env)["power"]] == \
        [("PSU 1A", "ok"), ("PSU 1B", "fault")]
    assert "c9300-hq-a03 uptime is" in raw                     # still running on 1A
    ports = pd.read_excel(customer / "RTG-HQ" / "audits" / "port_status_audit_output_RTG-HQ.xlsx")
    assert (ports[ports["Hostname"] == "c9300-hq-a03"]["Status"] == "connected").any()
    healthy = (customer / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a01.txt").read_text(encoding="utf-8")
    env = healthy.split("=== show environment all ===\n")[1].split("\n\n=== ")[0]
    assert {x["status"] for x in af.parse_cisco_environment(env)["power"]} == {"ok"}   # a healthy pair


SCENARIO_FAULTS = {
    "unrecorded device listed": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE, lambda d: d.loc.__setitem__(
        len(d), dict(d.iloc[0], **{"Serial No": N.synthetic_serial("c9300-hq-a06")}))),
        "is listed although the design records no contract"),
    "expired contract still active": (lambda c: _edit_xlsx(c / "_supplemental" / E.SCHEDULE, lambda d: _set(
        d, d[d["Serial No"] == N.synthetic_serial("c9300-hq-a05")].index, "Actual End Date", "2027-06-30")),
        "record ends 2027-06-30"),
    "healthy switch reports a bad supply": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a04.txt", "OK               Good     Good     715",
        "Bad              Bad      Bad      715"), "c9300-hq-a04: power supplies not OK"),
    "failed supply reported healthy": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a03.txt", "Bad              Bad      Bad      715",
        "OK               Good     Good     715"), "c9300-hq-a03: power supplies not OK [], the design says 1B"),
    "root bridge owned by no collected switch": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a01.txt", E.dotted_mac(N.synthetic_mac("c9500-hq-c01")),
        "0272.7400.0000"), "is no collected switch reporting itself root"),
    "audit root VLANs contradict the switch": (lambda c: _edit_xlsx(
        c / "RTG-HQ" / "audits" / "cisco_switch_audit_output_RTG-HQ.xlsx",
        lambda d: _set(d, d[d["Hostname"] == "c9500-hq-c01"].index, "spanningtree_root", "VLAN0010")),
        "the audit's root VLANs differ"),
}


def test_report_check_reconciles_what_a_device_carries_alone(net):
    ok = _report_text(net).replace("Summary of findings", "c9500-hq-c01 alone carries 2 switches\r\nSummary of findings", 1)
    assert V.validate_report(net, "RTG-HQ", ok) == []        # the north EPL and DC path A end on c01 alone
    bad = _report_text(net).replace("Summary of findings", "c9300-hq-c03 carries 27 switches alone\r\nSummary of findings", 1)
    assert any("alone carries 27; the design attaches 1" in p for p in V.validate_report(net, "RTG-HQ", bad))


def test_report_check_rejects_a_root_outside_the_collected_devices(net):
    text = _report_text(net).replace("Summary of findings", "outside the collected devices 02:72:74:e1:a8:65 CIST\r\n"
                                     "Summary of findings", 1)
    assert any("shown outside the collected devices" in p for p in V.validate_report(net, "RTG-HQ", text))


@pytest.mark.parametrize("name", sorted(SCENARIO_FAULTS))
def test_validator_detects_each_scenario_evidence_fault(net, written, name):
    root, customer = written
    fault, expected = SCENARIO_FAULTS[name]
    fault(customer)
    problems = V.validate_written(net, root, history=False)
    assert any(expected in p for p in problems), problems


# ------------------------------------------------------------------ the access-layer endpoint population
def test_the_endpoint_population_follows_the_plan(net):
    from collections import Counter
    kinds = Counter((d.site, d.endpoint_kind) for d in net.devices.values() if d.role == "endpoint")
    assert kinds[("RTG-HQ", "workstation")] == 222 and kinds[("RTG-HQ", "IP phone")] == 142
    assert kinds[("RTG-SOUTH", "IP phone")] == 0 and kinds[("RTG-SOUTH", "workstation")] == 60   # softphones
    assert kinds[("RTG-NORTH", "camera")] == 0                                                   # no VLAN 80 there
    # wired workstations stay within each site's /24 user VLAN pool
    for site in N.SITES:
        assert kinds[(site, "workstation")] <= N.DHCP_LAST - N.DHCP_FIRST + 1
    assert not any(d.announces for d in net.devices.values() if d.endpoint_kind == "workstation")
    phones = [d for d in net.devices.values() if d.endpoint_kind == "IP phone"]
    assert all(d.lldp_name == "SEP" + d.mac.replace(":", "").upper() for d in phones)


def test_the_july_and_october_endpoints_are_the_same_population(net):
    july = N.as_of_july(N.build())
    assert V.validate_timeline(july, net) == []
    assert sum(d.role == "endpoint" for d in july.devices.values()) == \
        sum(d.role == "endpoint" for d in net.devices.values())


def _ep(n, name):
    return n.devices[name]


def _first_link(n, a, b):
    return next(l for l in n.links if {l.a, l.b} == {a, b})


ENDPOINT_FAULTS = [
    (lambda n: setattr(_ep(n, "hq-ws-0002"), "mac", _ep(n, "hq-ws-0001").mac), "duplicate MAC"),
    (lambda n: setattr(_ep(n, "hq-ws-0002"), "mac", "00:1b:21:00:00:01"), "not a locally administered"),
    (lambda n: setattr(_ep(n, "hq-ph-0002"), "lldp_name", _ep(n, "hq-ph-0001").lldp_name), "duplicate endpoint identity"),
    (lambda n: setattr(_ep(n, "hq-ws-0002"), "mgmt_ip", _ep(n, "hq-ws-0001").mgmt_ip), "duplicate management address"),
    (lambda n: setattr(_ep(n, "hq-ws-0002"), "mgmt_ip", "10.10.20.5"), "outside VLAN 20's endpoint pool"),
    (lambda n: setattr(_first_link(n, "c9300-hq-a01", "hq-prn-03"), "vlans", [20]), "the design says access VLAN 70"),
    (lambda n: setattr(_first_link(n, "c9300-hq-a01", "hq-prn-03"), "mode", "trunk"), "the design says access VLAN 70"),
    (lambda n: setattr(_first_link(n, "c9300-hq-a01", "hq-prn-03"),
                       "a_port" if _first_link(n, "c9300-hq-a01", "hq-prn-03").a == "c9300-hq-a01" else "b_port",
                       "Te1/1/7"), "not an access port"),
    (lambda n: setattr(_first_link(n, "c9300-hq-a01", "hq-prn-03"),
                       "a_port" if _first_link(n, "c9300-hq-a01", "hq-prn-03").a == "c9300-hq-a01" else "b_port",
                       "Gi3/0/12"), "not an access port"),
    (lambda n: setattr(_ep(n, "hq-ws-0001"), "announces", True), "a workstation announces"),
    (lambda n: setattr(n, "links", [l for l in n.links if "hq-ws-0001" not in (l.a, l.b)]),
     "exactly one workstation on its PC port"),
]


@pytest.mark.parametrize("fault,expected", ENDPOINT_FAULTS)
def test_validator_detects_each_endpoint_fault(net, fault, expected):
    problems = _mutate(net, fault)
    assert any(expected in p for p in problems), problems


def test_validator_detects_an_unexpected_change_between_july_and_october(net):
    july = N.as_of_july(N.build())
    july.devices["hq-ws-0007"].mgmt_ip = "10.10.20.249"
    assert any("unexpected change to hq-ws-0007" in p for p in V.validate_timeline(july, net))
    july = N.as_of_july(N.build())
    link = _first_link(july, "c9300-hq-a01", "hq-prn-03")
    link.vlans = [80]
    assert any("unexpected link change" in p for p in V.validate_timeline(july, net))


ENDPOINT_EVIDENCE_FAULTS = {
    "desk port description changed": (lambda c: _edit_text(
        c / "RTG-HQ" / "backups" / "cisco" / E.RUN / f"c9300-hq-a01_backup_{E.RUN}.txt",
        " description Desk A1-001\n", " description spare\n"), "configuration does not match its patched endpoint"),
    "desk port configured as a trunk": (lambda c: _edit_text(
        c / "RTG-HQ" / "backups" / "cisco" / E.RUN / f"c9300-hq-a01_backup_{E.RUN}.txt",
        " description Desk A1-001\n switchport mode access", " description Desk A1-001\n switchport mode trunk"),
        "configuration does not match its patched endpoint"),
    "endpoint port down": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a01.txt", "GigabitEthernet1/0/3 is up, line protocol is up",
        "GigabitEthernet1/0/3 is down, line protocol is down"), "show interfaces does not show it up"),
    "PoE does not match the powered devices": (lambda c: _edit_text(
        c / "RTG-HQ" / "raw" / "cisco_raw_c9300-hq-a01.txt", "1           740.0       138.5       601.5",
        "1           740.0        12.5       727.5"),
        "PoE"),
    "a workstation in the neighbour tables": (lambda c: _edit_xlsx(
        c / "RTG-HQ" / "discovery" / "network_mapping_output_RTG-HQ.xlsx",
        lambda d: _set(d, d[d["Neighbour"].str.startswith("SEP")].index, "Neighbour", "hq-ws-0001")),
        "a silent workstation appears"),
    "a phone missing from the neighbour tables": (lambda c: _edit_xlsx(
        c / "RTG-HQ" / "discovery" / "network_mapping_output_RTG-HQ.xlsx",
        lambda d: _set(d, d[d["Neighbour"].str.startswith("SEP")].index, "Chassis ID", "02:72:75:00:00:00")),
        "is not in the neighbour tables"),
}


@pytest.mark.parametrize("name", sorted(ENDPOINT_EVIDENCE_FAULTS))
def test_validator_detects_each_endpoint_evidence_fault(net, written, name):
    root, customer = written
    fault, expected = ENDPOINT_EVIDENCE_FAULTS[name]
    fault(customer)
    problems = V.validate_written(net, root, history=False)
    assert any(expected in p for p in problems), problems


def test_report_check_reconciles_the_unused_port_count(net):
    text = _report_text(net)
    n = V.unused_ports_up(net, "RTG-HQ")
    bad = text.replace(f"{n} unused ports are left enabled", f"{n - 100} unused ports are left enabled")
    assert any("unused ports left enabled; the evidence has" in p for p in V.validate_report(net, "RTG-HQ", bad))


# ------------------------------------------------------------------ history generation without uncommitted product code
_STUB_EXTRAS = '''
import os
from datetime import datetime
ROOT = os.environ["STUB_ROOT"]
class _Layout:
    def __init__(self, site):
        self.base = os.path.join(ROOT, site)
    def dir(self, name, create=False):
        p = os.path.join(self.base, name)
        os.makedirs(p, exist_ok=True)
        return p
def _layout(site):
    return _Layout(site)
class writing_to:
    def __init__(self, folder):
        self.folder = folder
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
'''
_STUB_SERVICES = '''
import json, os
import asbuilt_extras
from datetime import datetime
LIVE_GATHER = {}
SCOPED = []
def saved_evidence(site):
    return {"mapping": None, "netbox_devices": {}, "l3": {}, "audit": None, "firewalls": []}
def document_from_collection(site, *, audit, firewalls, mapping_results, netbox_devices, filename, wan=None, **kw):
    if REQUIRES_SCOPE and not SCOPED:
        raise RuntimeError("report refused: no evidence scope")
    hist = os.path.join(asbuilt_extras._layout(site).base, "history")
    os.makedirs(hist, exist_ok=True)
    when = asbuilt_extras.datetime.now()          # the engine's own clock, as gather_extras reads it
    with open(os.path.join(hist, "asbuilt_history.json"), "w") as fh:
        json.dump({"documented": when.strftime("%Y-%m-%d %H:%M"), "live_gather": LIVE_GATHER}, fh)
    return filename
'''
_STUB_SCOPE = '''
REQUIRES_SCOPE = True
import contextlib
def report_scope(layout, *, output_dirs, runs_dir=None, supplemental=None, evidence_dirs=()):
    return {"site": layout.base}
@contextlib.contextmanager
def scoped_report(layout, scope):
    SCOPED.append(scope)
    try:
        yield
    finally:
        SCOPED.pop()
'''


@pytest.mark.parametrize("with_scope", [False, True], ids=["committed engine (no report_scope)", "engine with report_scope"])
def test_history_generation_runs_on_either_engine(tmp_path, monkeypatch, with_scope):
    """The July history step (engine.HISTORY_CODE) runs in a subprocess against an engine with or
    without report_scope (P-12): it must not depend on uncommitted product code, and where the
    engine does confine reports to a scope it must still use it."""
    import engine as G
    eng = tmp_path / "engine"
    eng.mkdir()
    (eng / "asbuilt_extras.py").write_text(_STUB_EXTRAS, encoding="utf-8")
    services = _STUB_SERVICES.replace("LIVE_GATHER = {}", "LIVE_GATHER = {}\nREQUIRES_SCOPE = False")
    if with_scope:
        services += _STUB_SCOPE
    (eng / "sysopty_services.py").write_text(services, encoding="utf-8")
    for name in ("asbuilt_pdf", "asbuilt_snapshot", "asbuilt_findings", "pdf_exporter"):
        (eng / f"{name}.py").write_text("from datetime import datetime\n", encoding="utf-8")
    root = tmp_path / "artifacts"
    monkeypatch.setattr(G, "env", lambda: {**os.environ, "STUB_ROOT": str(root)})
    out = G.record_history("RTG-HQ", (2026, 7, 20, 10, 40, 0), engine=eng)
    assert out["history"] == ["asbuilt_history.json"]
    rec = json.loads((root / "RTG-HQ" / "history" / "asbuilt_history.json").read_text(encoding="utf-8"))
    assert rec["documented"] == "2026-07-20 10:40"                 # the engine's clock read the July time
    assert rec["live_gather"] == {"with_netbox": False, "with_maps": False}


def test_history_generation_fails_loudly_when_the_engine_cannot_document(tmp_path, monkeypatch):
    import engine as G
    eng = tmp_path / "engine"
    eng.mkdir()
    (eng / "asbuilt_extras.py").write_text(_STUB_EXTRAS, encoding="utf-8")
    (eng / "sysopty_services.py").write_text(_STUB_SERVICES.replace("LIVE_GATHER = {}", "LIVE_GATHER = {}\nREQUIRES_SCOPE = True"),
                                             encoding="utf-8")       # needs a scope it cannot be given
    for name in ("asbuilt_pdf", "asbuilt_snapshot", "asbuilt_findings", "pdf_exporter"):
        (eng / f"{name}.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(G, "env", lambda: {**os.environ, "STUB_ROOT": str(tmp_path / "artifacts")})
    with pytest.raises(SystemExit, match="history step failed"):
        G.record_history("RTG-HQ", (2026, 7, 20, 10, 40, 0), engine=eng)


# ------------------------------------------------------------------ the interactive map: device types
@needs_platform
def test_the_rtg_map_classifies_every_device_by_type(net, tmp_path, monkeypatch):
    """The enterprise map, built and drawn as the demo stage builds it (engine.TOPOLOGY_CODE) from
    the synthetic evidence: all 228 desk phones are phones, never switches; every switch is a switch
    and no switch is anything else; routers, firewalls, access points, printers, cameras and
    controllers by their type -- on the drawn map's nodes and in its Types summary."""
    sys.path.insert(0, PLATFORM)
    import network_icons as ni
    import network_mapping as nm
    monkeypatch.setattr(nm, "_shared_plotlyjs", lambda page_path: "")   # inline the library: no write to the platform checkout
    spec = json.loads(json.dumps(E.topology_inputs(net, list(N.SITES))))
    g = nm.build_network_topology(nm.dataframe_to_cdp_dict(pd.DataFrame(spec["rows"])), spec["vendor_map"],
                                  spec["platform_map"], spec["ip_map"], spec["l2"], spec["l3"], set(spec["reporting"]))
    nm.generate_topology_outputs(g, N.ORG, output_dir=str(tmp_path), open_html=False, export_visio=False)
    by_name = {str(n).lower(): ni.device_category(g.nodes[n], n) for n in g.nodes}
    for kind in ("router", "firewall"):
        names = [d.hostname for d in net.devices.values() if d.kind == kind]
        assert names and {by_name[h] for h in names} == {kind}, kind
    # the icon view (the demo's default) draws a phone as a phone, never with the switch picture
    icons = {str(n).lower(): ni.icon_kind(g.nodes[n], n) for n in g.nodes}
    assert {icons[d.lldp_name.lower()] for d in net.devices.values() if d.endpoint_kind == "IP phone"} == {"phone"}
    assert {icons[d.hostname] for d in net.devices.values() if d.kind == "router"} == {"router"}
    phones = [d for d in net.devices.values() if d.endpoint_kind == "IP phone"]
    assert len(phones) == 228
    assert {by_name[d.lldp_name.lower()] for d in phones} == {"phone"}
    assert not any(g.nodes[n].get("type") == "switch" for n in g.nodes if str(n).upper().startswith("SEP"))
    switches = [d.hostname for d in net.devices.values() if d.kind == "switch"]
    assert {by_name[h] for h in switches if h in by_name} == {"switch"}
    assert len([h for h in switches if h in by_name]) == len(switches)
    aps = [d.hostname for d in net.devices.values() if d.kind == "ap"]
    assert {by_name[h] for h in aps} == {"ap"} and len(aps) == 60
    expect = {"printer": "printer", "camera": "video", "video recorder": "video", "door controller": "building",
              "BMS controller": "building", "UPS": "building"}
    for d in net.devices.values():
        if d.endpoint_kind in expect and d.hostname in by_name:
            assert by_name[d.hostname] == expect[d.endpoint_kind], d.hostname
    counts = dict(ni.category_counts(g))
    assert counts["Phone"] == 228 and counts["Access point"] == 60 and counts["Switch"] == len(switches)
    assert counts["Router"] == 7 and counts["Firewall"] == 8
    assert "Workstation" not in counts           # workstations announce nothing: they are not on the map
    html = next(tmp_path.glob("*.html")).read_text(encoding="utf-8", errors="replace")
    html = html.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u002f", "/")
    summary = re.search(r"<b>Types</b>: ([^\"<]*)", html).group(1)
    assert summary == ", ".join(f"{label} {n}" for label, n in ni.category_counts(g))   # what is drawn
    assert "Phone 228" in summary and f"Switch {len(switches)}," in summary


def test_the_validator_reads_the_reports_collection_line():
    m = V.COMPLETENESS.search("22 of 22 devices complete in every capability;\n284 of 284 capabilities")
    assert m and m.groups() == ("22", "22", "284", "284")
    assert not V.COMPLETENESS.search("18 of 22 devices; 270 of 276")


def test_a_failed_report_stops_the_build_even_when_it_left_a_pdf(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import engine as G
    pdf = tmp_path / "RTG-HQ" / "run.partial" / "devices_report_RTG-HQ_x.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="outside its evidence scope"))
    with pytest.raises(SystemExit, match="exit 1"):
        G._run_report("RTG-HQ", tmp_path, "X:\\")


def test_the_engine_does_not_inherit_a_python_path(monkeypatch):
    import engine as G
    monkeypatch.setenv("PYTHONPATH", "elsewhere")
    assert "PYTHONPATH" not in G.env()

