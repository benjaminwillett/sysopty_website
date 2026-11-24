"""Consistency checks for the synthetic network and its generated evidence.

    python build/synthetic/validate.py [evidence root]

validate_network() checks the design itself; validate_evidence() checks the files written
for the engine. Both return a list of problems (empty when everything is consistent).
"""
from __future__ import annotations

import ipaddress
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import network as N   # noqa: E402

DOC_RANGES = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
SERVICES_NET = ipaddress.ip_network("10.21.100.0/24")
PORT_RE = {
    "cisco": re.compile(r"^(Gi|Te|Twe|Hu)\d/\d/\d{1,2}$"),
    "extreme": re.compile(r"^\d/\d{1,2}$"),
    "palo": re.compile(r"^(ethernet1/\d{1,2}|ae\d)$"),
    "fortinet": re.compile(r"^(port\d{1,2}|x\d|wan\d?|lan\d|dmz)$"),
}
NEIGHBOUR_PORT_RE = {"ap": re.compile(r"^(Gi0|eth0)$"), "router": re.compile(r"^Gi0/0/\d$"),
                     "endpoint": re.compile(r"^eth0$"), "phone": re.compile(r"^(Port 1|PC Port)$")}


# The report's collection line, tolerating a PDF line wrap anywhere in it.
COMPLETENESS = re.compile(r"(\d+)\s+of\s+(\d+)\s+devices\s+complete\s+in\s+every\s+capability;\s+(\d+)\s+of\s+(\d+)\s+capabilities")


def _public(ip) -> bool:
    return not ip.is_private and not ip.is_loopback and not ip.is_link_local


def validate_network(net) -> list[str]:
    p = []
    devs = net.devices
    # identities
    mgmt = [d.mgmt_ip for d in devs.values() if d.mgmt_ip]
    p += [f"duplicate management address {ip}" for ip, n in Counter(mgmt).items() if n > 1]
    serials = [N.synthetic_serial(d.hostname, m) for d in devs.values() if d.collected for m in range(1, d.members + 1)]
    p += [f"duplicate serial {s}" for s, n in Counter(serials).items() if n > 1]
    p += [f"serial format {s}" for s in serials if not re.fullmatch(r"SYN[0-9A-F]{8}", s)]
    macs = [N.synthetic_mac(h) for h in devs]
    p += [f"duplicate MAC {m}" for m, n in Counter(macs).items() if n > 1]
    p += [f"MAC not locally administered {m}" for m in macs if not int(m.split(":")[0], 16) & 0x02]
    for d in devs.values():
        if d.hostname != d.hostname.lower():
            p.append(f"hostname not lowercase: {d.hostname}")
        if d.collected and d.kind in ("switch", "firewall") and not (d.model and d.software and d.room and d.mgmt_ip):
            p.append(f"inventory fields missing for {d.hostname}")
    # links: endpoints exist, ports valid and used once, VLANs belong to both sites
    used = Counter()
    for l in net.links:
        for host, port in ((l.a, l.a_port), (l.b, l.b_port)):
            if host not in devs:
                p.append(f"dangling link endpoint {host}")
                continue
            d = devs[host]
            rx = PORT_RE.get(d.vendor) if d.kind in ("switch", "firewall") else \
                NEIGHBOUR_PORT_RE.get("phone" if d.endpoint_kind == "IP phone" else d.kind)
            if rx and not rx.match(port):
                p.append(f"{host}: port {port} does not fit {d.vendor} {d.kind} naming")
            used[(host, port)] += 1
        for host in (l.a, l.b):
            d = devs.get(host)
            if d and d.kind == "switch":
                missing = set(l.vlans) - set(N.SITE_VLANS[d.site]) - {10}
                if missing:
                    p.append(f"{host}: link carries VLANs {sorted(missing)} not defined at {d.site}")
        if l.mode == "access" and len(l.vlans) != 1:
            p.append(f"access link {l.a} {l.a_port} carries {l.vlans}")
    p += [f"{h} port {pt} used by {n} links" for (h, pt), n in used.items() if n > 1]
    # addressing: every interface address valid, inside its VLAN's subnet, never assigned twice
    addrs = Counter()
    for d in devs.values():
        for ifc, a in d.svis.items():
            iface = ipaddress.ip_interface(a)
            vid = int(ifc[4:])
            if vid < 256 and iface.network != N.subnet(d.site, vid) and not iface.ip.exploded.startswith("10.10.250."):
                p.append(f"{d.hostname} {ifc} {a} outside VLAN {vid} subnet {N.subnet(d.site, vid)}")
            if iface.ip in (iface.network.network_address, iface.network.broadcast_address):
                p.append(f"{d.hostname} {ifc} {a} is a network or broadcast address")
            addrs[str(iface.ip)] += 1
        for vip, _ in d.hsrp.values():
            pass
        for name, zone, tag, a in d.fw_interfaces:
            if a == "ha":
                continue
            iface = ipaddress.ip_interface(a)
            if _public(iface.ip) and not any(iface.ip in r for r in DOC_RANGES):
                p.append(f"{d.hostname} {name} uses a non-documentation public address {a}")
            if not zone:
                p.append(f"{d.hostname} {name} has an address but no zone")
            if name.startswith("ae1.") and str(tag) != name.split(".")[1]:
                p.append(f"{d.hostname} {name} tag {tag} does not match its sub-interface number")
            if d.ha_state != "passive":       # the passive unit mirrors the active unit's addresses
                addrs[str(iface.ip)] += 1
    p += [f"address {a} assigned {n} times" for a, n in addrs.items() if n > 1 and not a.startswith("198.51.100.2")]
    vips = Counter(vip for d in devs.values() for vip, _ in d.hsrp.values())
    p += [f"HSRP address {v} is also an interface address" for v in vips if v in addrs]
    # HSRP groups are pairs on the same subnet
    for v, n in vips.items():
        if n != 2:
            p.append(f"HSRP address {v} has {n} members")
    # firewall zones: tagged sub-interfaces ride a bundle whose member links carry that VLAN
    for d in devs.values():
        tags = {int(t) for n, z, t, a in d.fw_interfaces if n.startswith("ae1.")}
        if not tags:
            continue
        carried = set()
        for port, other, oport, l in N.neighbours(net, d.hostname):
            if l.lag:
                carried |= set(l.vlans)
        if tags - carried:
            p.append(f"{d.hostname}: zones on VLANs {sorted(tags - carried)} not carried by its ae1 members")
    # services: every receiver is in the services subnet and is not a device address
    for d in devs.values():
        if not d.collected:
            continue
        svc = N.services(d)
        for ip in svc["syslog"] + [h for _, h in svc["traps"]] + svc["ntp"] + N.DNS + N.TACACS:
            if ipaddress.ip_address(ip) not in SERVICES_NET:
                p.append(f"{d.hostname}: service address {ip} outside {SERVICES_NET}")
            if ip in addrs:
                p.append(f"{d.hostname}: service address {ip} collides with an interface")
    # topology: every collected switch reaches its site's core (no islands inside a site)
    for site in N.SITES:
        switches = {d.hostname for d in net.site_devices(site) if d.kind == "switch"}
        if not switches:
            continue
        start = sorted(switches)[0]
        seen, todo = {start}, [start]
        while todo:
            h = todo.pop()
            for _, o, _, _ in N.neighbours(net, h):
                if o in switches and o not in seen:
                    seen.add(o)
                    todo.append(o)
        if seen != switches:
            p.append(f"{site}: switches not connected to the rest: {sorted(switches - seen)}")
    p += validate_wan(net) + validate_ha(net) + validate_risks(net) + validate_endpoints(net)
    return p


def _access_port(d, port) -> bool:
    """The port exists on the switch and is an access (not uplink) port of its platform."""
    short, _long, prefix, first, last = N.PLATFORMS[d.platform][4]["access"]
    if d.vendor == "extreme":
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", port)
        return bool(m) and first <= int(m.group(1)) <= last
    m = re.fullmatch(re.escape(short) + r"(\d+)/0/(\d+)", port)
    return bool(m) and 1 <= int(m.group(1)) <= d.members and first <= int(m.group(2)) <= last


def validate_endpoints(net) -> list[str]:
    """The access-layer endpoints: unique identities, addresses in their VLAN's pool, patched to an
    existing access port (never an uplink) in the VLAN their kind belongs to, carried by the
    switch's uplinks; phones with one PC behind them; only workstations silent on CDP/LLDP."""
    p = []
    devs = net.devices
    macs = Counter(N.device_mac(d) for d in devs.values())
    p += [f"duplicate MAC {m}" for m, n in macs.items() if n > 1]
    p += [f"MAC not a locally administered unicast address {m}" for m in macs
          if not int(m.split(":")[0], 16) & 0x02 or int(m.split(":")[0], 16) & 0x01]
    names = Counter((d.lldp_name or d.hostname).lower() for d in devs.values())
    p += [f"duplicate endpoint identity {n}" for n, c in names.items() if c > 1]
    for d in devs.values():
        if d.role != "endpoint" or d.endpoint_kind not in N.ENDPOINT_VLAN:
            continue
        if d.announces != (d.endpoint_kind != "workstation"):
            p.append(f"{d.hostname}: a {d.endpoint_kind} {'announces' if d.announces else 'does not announce'} CDP/LLDP")
        if d.endpoint_kind == "IP phone":
            behind = [o for port, o, _, _ in N.neighbours(net, d.hostname) if port == "PC Port"]
            if len(behind) != 1 or devs[behind[0]].endpoint_kind != "workstation":
                p.append(f"{d.hostname}: a desk phone needs exactly one workstation on its PC port")
        sw_links = [(port, o, op, l) for port, o, op, l in N.neighbours(net, d.hostname) if devs[o].kind == "switch"]
        if d.endpoint_kind == "workstation" and not sw_links:
            ph = [o for port, o, _, _ in N.neighbours(net, d.hostname) if devs[o].endpoint_kind == "IP phone"]
            sw_links = [(port, o, op, l) for x in ph for port, o, op, l in N.neighbours(net, x) if devs[o].kind == "switch"]
        if len(sw_links) != 1:
            p.append(f"{d.hostname}: not patched to exactly one access switch port")
            continue
        _, swn, swport, link = sw_links[0]
        sw = devs[swn]
        if sw.site != d.site or not sw.collected:
            p.append(f"{d.hostname}: patched to {swn}, not a collected switch at {d.site}")
        if not _access_port(sw, swport):
            p.append(f"{d.hostname}: on {swn} {swport}, which is not an access port of a {sw.model}")
        vlan = N.endpoint_vlan(d.site, "workstation" if d.endpoint_kind == "IP phone" else d.endpoint_kind)
        # the July state deliberately had the door controller in the user VLAN (network.JULY_CHANGES)
        allowed = {vlan} | ({20} if any(c == "access VLAN" and h == d.hostname for c, h, _ in N.JULY_CHANGES) else set())
        if link.mode != "access" or len(link.vlans) != 1 or link.vlans[0] not in allowed:
            p.append(f"{d.hostname}: {swn} {swport} is {link.mode} {link.vlans}, the design says access VLAN {vlan}")
        uplinked = {v for _, o, _, l in N.neighbours(net, swn) if l.mode == "trunk" for v in l.vlans} \
            | {v for v in N.SITE_VLANS[d.site] if sw.role != "access"}      # a core/distribution switch routes them
        if link.vlans and link.vlans[0] not in uplinked:
            p.append(f"{d.hostname}: VLAN {link.vlans[0]} is not carried by {swn}'s uplinks")
        # the address is in the VLAN the device actually sits in (a phone: the voice VLAN)
        own_vlan = N.endpoint_vlan(d.site, "IP phone") if d.endpoint_kind == "IP phone" else (link.vlans or [vlan])[0]
        if d.mgmt_ip:
            ip = ipaddress.ip_address(d.mgmt_ip)
            sub = N.subnet(d.site, own_vlan)
            if ip not in sub or not N.DHCP_FIRST <= int(str(ip).split(".")[-1]) <= N.DHCP_LAST:
                p.append(f"{d.hostname}: address {ip} is outside VLAN {own_vlan}'s endpoint pool")
        else:
            p.append(f"{d.hostname}: no address")
    # port capacity: what each access switch has patched fits its access ports
    for sw in devs.values():
        if sw.kind == "switch" and sw.role == "access":
            g = N.PLATFORMS[sw.platform][4]["access"]
            cap = (g[4] - g[3] + 1) * (sw.members if sw.vendor == "cisco" else 1)
            used = sum(1 for port, o, _, l in N.neighbours(net, sw.hostname) if _access_port(sw, port))
            if used > cap:
                p.append(f"{sw.hostname}: {used} access ports patched, {cap} exist")
    return p


def validate_timeline(july, october) -> list[str]:
    """Between the July and October designs only the recorded changes (network.JULY_CHANGES) differ:
    no endpoint, link or address changes anything else."""
    p = []
    named = {h for _, h, _ in N.JULY_CHANGES}
    key = lambda l: tuple(sorted([(l.a, l.a_port), (l.b, l.b_port)])) + (tuple(l.vlans), l.mode)
    for side, a, b in (("July", july, october), ("October", october, july)):
        for l in {key(x): x for x in a.links}.keys() - {key(x) for x in b.links}:
            if not {l[0][0], l[1][0]} & named:
                p.append(f"unexpected link change, only in {side}: {l[0]} - {l[1]}")
    for h in set(july.devices) ^ set(october.devices):
        if h not in named:
            p.append(f"unexpected device change: {h}")
    for h in set(july.devices) & set(october.devices):
        a, b = july.devices[h], october.devices[h]
        if h not in named and (a.mgmt_ip, N.device_mac(a), a.software) != (b.mgmt_ip, N.device_mac(b), b.software):
            p.append(f"unexpected change to {h} between July and October")
    return p


COLLECTION_DATE = "2026-10-20"


def validate_risks(net) -> list[str]:
    """The deliberate operational risks: a power supply fault on a collected Cisco switch with a bay
    that exists, an expired contract that ended before the collection, and a device with no record,
    each a different collected device."""
    p = []
    for h, bay in N.PSU_FAULTS.items():
        d = net.devices.get(h)
        if d is None or not (d.collected and d.vendor == "cisco" and d.kind == "switch"):
            p.append(f"PSU fault on {h}: not a collected Cisco switch")
            continue
        m = re.fullmatch(r"(\d+)([AB])", bay)
        if not m or int(m.group(1)) > d.members:
            p.append(f"PSU fault on {h}: the switch has no bay {bay}")
    # (the July state has no fault; validate_report requires the October finding for each one)
    p +=[f"{d.hostname}: PSU fault {d.psu_fault} not in the design's list" for d in net.devices.values()
          if d.psu_fault and N.PSU_FAULTS.get(d.hostname) != d.psu_fault]
    for h, rec in N.SUPPORT_EXCEPTIONS.items():
        d = net.devices.get(h)
        if d is None or not d.collected or d.kind not in ("switch", "firewall"):
            p.append(f"support exception {h}: not a collected switch or firewall")
        elif rec is not None and not (rec[0] == "Expired" and rec[1] < rec[2] < COLLECTION_DATE):
            p.append(f"support exception {h}: an expired contract must end before the collection")
    kinds = [rec is None for rec in N.SUPPORT_EXCEPTIONS.values()]
    if True not in kinds or False not in kinds:
        p.append("support exceptions: need one expired contract and one device with no record")
    if set(N.SUPPORT_EXCEPTIONS) & set(N.PSU_FAULTS):
        p.append("the support and power supply scenarios must be on different devices")
    return p


def validate_wan(net) -> list[str]:
    """Carrier services (network.WAN_SERVICES) terminate where the model connects them."""
    p, by_circuit = [], {}
    for site, service, kind, circuit, bandwidth, ends in N.WAN_SERVICES:
        if site not in N.SITES:
            p.append(f"WAN {circuit}: unknown site {site}")
        if not re.fullmatch(r"SYN-[A-Z]{2,3}-[A-Z0-9-]{2,12}", circuit):
            p.append(f"WAN {circuit}: circuit identifier is not in the synthetic format")
        by_circuit.setdefault(circuit, set()).add((service, kind, bandwidth, ends))
        for e in ends:
            if e not in net.devices:
                p.append(f"WAN {circuit}: terminating device {e} does not exist")
        if any(e not in net.devices for e in ends):
            continue
        if kind == "Internet":
            cpe = net.devices[ends[0]]
            if len(ends) != 1 or cpe.kind != "router" or cpe.site != site or cpe.collected:
                p.append(f"WAN {circuit}: internet service must end on one uncollected carrier CPE at {site}")
            elif not any(l.purpose == "carrier CPE" and net.devices[o].kind == "switch"
                         for _, o, _, l in N.neighbours(net, cpe.hostname)):
                p.append(f"WAN {circuit}: carrier CPE {cpe.hostname} is not connected to a switch")
        elif kind in ("EPL", "Dark fibre"):
            a, b = ends
            if site not in (net.devices[a].site, net.devices[b].site):
                p.append(f"WAN {circuit}: listed at {site}, which neither end is at")
            if not any(o == b and l.purpose == N.WAN_PURPOSE[kind] for _, o, _, l in N.neighbours(net, a)):
                p.append(f"WAN {circuit}: no {N.WAN_PURPOSE[kind]} link between {a} and {b}")
        elif kind == "Addressing":
            block = ipaddress.ip_network(service.split()[-1])
            if not any(block.subnet_of(r) for r in DOC_RANGES):
                p.append(f"WAN {circuit}: address block {block} is not a documentation range")
            untrust = [ipaddress.ip_interface(a).ip for d in net.site_devices(site)
                       for n, z, t, a in d.fw_interfaces if z == "untrust"]
            if untrust and not any(ip in block for ip in untrust):
                p.append(f"WAN {circuit}: address block {block} does not hold the {site} firewall address")
        else:
            p.append(f"WAN {circuit}: unknown service type {kind}")
    p += [f"WAN {c}: listed with different details at its two ends" for c, v in by_circuit.items() if len(v) > 1]
    # every carrier CPE carries a listed internet service
    listed = {e for _, _, k, _, _, ends in N.WAN_SERVICES if k == "Internet" for e in ends}
    p += [f"carrier CPE {d.hostname} has no service in the carrier export" for d in net.devices.values()
          if d.kind == "router" and d.hostname not in listed]
    return p


def validate_ha(net) -> list[str]:
    """HA pairs: reciprocal peers, one active and one passive, same model and software."""
    p = []
    for d in net.devices.values():
        if not d.ha_peer:
            continue
        peer = net.devices.get(d.ha_peer)
        if peer is None or peer.ha_peer != d.hostname:
            p.append(f"HA: {d.hostname} and {d.ha_peer} are not each other's peer")
            continue
        if {d.ha_state, peer.ha_state} != {"active", "passive"}:
            p.append(f"HA: {d.hostname}/{peer.hostname} states {d.ha_state}/{peer.ha_state}")
        if (d.model, d.software) != (peer.model, peer.software):
            p.append(f"HA: {d.hostname} and {peer.hostname} differ in model or software")
    return p


SECRET_RE = re.compile(r"(?im)^\s*(?:enable\s+)?(?:password|secret|key-string|pre-shared-key|community)\s+(?!\*{4})\S+")


def validate_evidence(root: Path, blocklist=()) -> list[str]:
    """Checks the written evidence: no credentials, no blocked words, only synthetic MACs/serials."""
    p = []
    words = [w.lower() for w in blocklist]
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in (".txt", ".html", ".json", ".csv", ".xlsx"):
            continue
        if f.suffix == ".html":
            continue                                   # the engine's own map output; checked by the leak check
        if f.suffix.lower() == ".xlsx":                # workbooks: every cell, as text
            import pandas as pd
            text = "\n".join(pd.read_excel(f, sheet_name=None, dtype=str).get(k).fillna("").to_csv(index=False)
                             for k in pd.read_excel(f, sheet_name=None, dtype=str))
        else:
            text = f.read_text(encoding="utf-8", errors="replace")
        for m in SECRET_RE.finditer(text):
            p.append(f"{f.name}: looks like a credential: {m.group(0).strip()[:40]}")
        # A bridge identifier (2 priority octets + MAC, "80:00:02:72:74:..") is checked by its MAC.
        bridge = r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){7}[0-9a-f]{2}(?![0-9a-f:])"
        macs = [b.split(":", 2)[2] for b in re.findall(bridge, text)] + \
            re.findall(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.sub(bridge, " ", text))
        for mac in macs:
            first = int(mac.split(":")[0], 16)
            if not first & 0x02:
                p.append(f"{f.name}: MAC {mac} is not locally administered")
        low = text.lower()
        for i, w in enumerate(words):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                p.append(f"{f.name}: blocked word #{i}")
    return p


def validate_written(net, root: Path, history: bool = True) -> list[str]:
    """The written evidence agrees with the design: the supplied carrier export and support
    schedule, the port status audit, the stack and HA output, the recorded history. root: the
    artifacts folder; history=False for evidence written without the engine's July document step."""
    import json
    import pandas as pd
    import evidence as E
    p = []
    customer = [c for c in root.iterdir() if c.is_dir() and not c.name.startswith("_")]    # _assets: the shared map library
    if len(customer) != 1:
        return [f"expected one customer folder under {root}, found {len(customer)}"]
    customer = customer[0]
    sup = customer / "_supplemental"
    # each of the engine's supplied-file patterns (evidence_boundary) matches exactly the intended file
    import fnmatch
    names = [f.name for f in sup.iterdir()] if sup.exists() else []
    for patterns, want in ((("*Customer_Portal_Data_Services*.csv", "*wan*export*.csv"), E.WAN_EXPORT),
                           (("*Device Schedule*.xls*", "*support*schedule*.xls*"), E.SCHEDULE)):
        hits = sorted(n for n in names if any(fnmatch.fnmatch(n.lower(), x.lower()) for x in patterns))
        if hits != [want]:
            p.append(f"supplied files matching {patterns[-1]}: {hits} (expected only {want})")
    if (sup / E.SCHEDULE).exists() and not (sup / E.SCHEDULE_RECORD).exists():
        p.append(f"support schedule verification record missing (the engine reads {E.SCHEDULE_RECORD})")
    # carrier export: exactly the designed services, nothing more
    wan = sup / E.WAN_EXPORT
    if not wan.exists():
        p.append("carrier export missing")
    else:
        rows = pd.read_csv(wan, dtype=str).fillna("")
        want = {(s, c) for s, _, _, c, _, _ in N.WAN_SERVICES}
        got = set(zip(rows["Site Name"], rows["Circuit ID"]))
        p += [f"carrier export: {s} {c} not in the design" for s, c in sorted(got - want)]
        p += [f"carrier export: {s} {c} missing" for s, c in sorted(want - got)]
    # support schedule: one record per collected switch unit and firewall, by serial
    sched = sup / E.SCHEDULE
    if not sched.exists():
        p.append("support schedule missing")
    else:
        rows = pd.read_excel(sched, dtype=str).fillna("")
        units = {N.synthetic_serial(d.hostname, m): d.hostname for d in net.devices.values()
                 if d.collected and d.kind in ("switch", "firewall")
                 for m in range(1, (d.members if d.kind == "switch" else 1) + 1)}
        unrecorded = {s for s, h in units.items() if h in N.SUPPORT_EXCEPTIONS and N.SUPPORT_EXCEPTIONS[h] is None}
        want = set(units) - unrecorded
        got = list(rows["Serial No"])
        p += [f"support schedule: serial {s} listed {n} times" for s, n in Counter(got).items() if n > 1]
        p += [f"support schedule: {units[s]} is listed although the design records no contract for it"
              for s in sorted(set(got) & unrecorded)]
        p += [f"support schedule: serial {s} is no collected asset" for s in sorted(set(got) - set(units))]
        p += [f"support schedule: asset serial {s} has no record" for s in sorted(want - set(got))]
        for _, r in rows.iterrows():
            start, end = pd.to_datetime(r["Start Date"], errors="coerce"), pd.to_datetime(r["Actual End Date"], errors="coerce")
            if pd.isna(start) or pd.isna(end) or end <= start:
                p.append(f"support schedule: {r['Serial No']} has invalid dates")
                continue
            host = units.get(r["Serial No"])
            design = N.SUPPORT_EXCEPTIONS.get(host) or ("Active", None, None)
            expired = end < pd.Timestamp(COLLECTION_DATE)
            if expired != (design[0] == "Expired") or (design[2] and r["Actual End Date"] != design[2]):
                p.append(f"support schedule: {host} record ends {r['Actual End Date']}, the design says "
                         f"{design[0]}{' ' + design[2] if design[2] else ''}")
            if r["Device Support Status"] != design[0]:
                p.append(f"support schedule: {host} status {r['Device Support Status']}, the design says {design[0]}")
        side = sup / E.SCHEDULE_RECORD
        if side.exists():
            v = json.loads(side.read_text(encoding="utf-8"))
            if set(v) != {"verified_by", "verified_on", "source"} or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["verified_on"]):
                p.append("support schedule verification record malformed")
            if re.search(r"(?i)end.of.(life|support|sale)|lifecycle|eol", json.dumps(v)):
                p.append("support schedule verification record claims lifecycle verification")
    # no other verification records: lifecycle dates are never marked verified by the build
    p += [f"unexpected verification record {f.name}" for f in root.rglob("*.verified.json") if f.parent != sup
          or f.name != E.SCHEDULE_RECORD]
    # history: only HQ has an earlier collection, recorded in July from the July state of the design
    for site in N.SITES:
        snaps = sorted((customer / site / "history" / "snapshots").glob("snapshot_*.json"))
        if site != "RTG-HQ":
            p += [f"{site}: unexpected history snapshot {s.name}" for s in snaps]
            continue
        if history and not snaps:
            p.append(f"{site}: no earlier collection recorded")
        for s in snaps:
            snap = json.loads(s.read_text(encoding="utf-8"))
            if not str(snap.get("generated", "")).startswith("2026-07-20"):
                p.append(f"{site}: snapshot {s.name} is not the July collection ({snap.get('generated')})")
            soft = {str(d.get("name")).lower(): d.get("software") for d in (snap.get("devices") or {}).values()}
            july = N.as_of_july(N.build())
            p += [f"{site}: July snapshot software of {h} is {soft.get(h)}, the July design says {july.devices[h].software}"
                  for h in ("c9500-hq-c01", "c9500-hq-c02", "c9300-hq-a01") if soft.get(h) != july.devices[h].software]
            if any(str(d.get("name")).lower() == "hq-blb-ap24" for d in (snap.get("devices") or {}).values()):
                p.append(f"{site}: the July snapshot holds an access point installed later")
        register = customer / site / "history" / "asbuilt_findings.json"
        if register.exists():
            for fid, f in json.loads(register.read_text(encoding="utf-8")).items():
                if not str(f.get("first_detected", "")) < "2026-10-20":
                    p.append(f"{site}: finding {fid} first detected {f.get('first_detected')}, after the July collection")
    for site in N.SITES:
        # CDP/LLDP: what announces itself is listed under its announced name and own MAC; nothing silent is
        mapping = pd.read_excel(customer / site / "discovery" / f"network_mapping_output_{site}.xlsx", dtype=str).fillna("")
        seen = {(r["Neighbour"], r["Chassis ID"]) for _, r in mapping.iterrows()}
        for d in net.site_devices(site):
            if d.role != "endpoint":
                continue
            listed = (d.lldp_name or d.hostname, N.device_mac(d)) in seen
            if d.announces and not listed:
                p.append(f"{d.hostname}: announces CDP/LLDP but is not in the neighbour tables as {d.lldp_name or d.hostname}")
            if not d.announces and any(n in (d.hostname, d.lldp_name) for n, _ in seen if n):
                p.append(f"{d.hostname}: a silent {d.endpoint_kind} appears in the CDP/LLDP neighbour tables")
    for site in N.SITES:
        base = customer / site
        ports = base / "audits" / f"port_status_audit_output_{site}.xlsx"
        switches = [d for d in net.site_devices(site) if d.collected and d.kind == "switch"]
        if not ports.exists():
            p.append(f"{site}: port status audit missing")
        else:
            rows = pd.read_excel(ports, dtype=str).fillna("")
            up = rows[rows["Status"].isin(("connected", "upup"))]
            bad = set(rows["Status"]) - {"connected", "notconnect", "upup", "updown"}
            p += [f"{site}: port status {b!r} not a collector value" for b in sorted(bad)]
            for d in switches:
                linked = set(E.port_vlans(net, d.hostname))
                seen = set(up[up["Hostname"] == d.hostname]["Port"])
                p += [f"{d.hostname}: port {x} up in the port status audit without a link" for x in sorted(seen - linked)]
                p += [f"{d.hostname}: linked port {x} not up in the port status audit" for x in sorted(linked - seen)]
                if rows[rows["Hostname"] == d.hostname]["Port"].duplicated().any():
                    p.append(f"{d.hostname}: a port listed twice in the port status audit")
        for d in switches:
            if d.vendor == "cisco":
                raw = (base / "raw" / f"cisco_raw_{d.hostname}.txt").read_text(encoding="utf-8")
                temps = set(re.findall(r"(?m)^Switch (\d+): SYSTEM TEMPERATURE is OK$", raw))
                if temps != {str(m) for m in range(1, d.members + 1)}:
                    p.append(f"{d.hostname}: temperature not reported for every stack member")
                # spanning-tree roots: every root a collected switch at the site that reports itself root
                if "=== show spanning-tree root ===" in raw:
                    table = raw.split("=== show spanning-tree root ===\n", 1)[1].split("\n\n=== ", 1)[0]
                    own = {d2.hostname: dict(re.findall(r"(?m)^VLAN0*(\d+)\s+\d+\s+(\S+)\s+0\b",
                           (base / "raw" / f"cisco_raw_{d2.hostname}.txt").read_text(encoding="utf-8")))
                           for d2 in switches if d2.vendor == "cisco"}
                    for vlan, mac, cost in re.findall(r"(?m)^VLAN0*(\d+)\s+\d+\s+(\S+)\s+(\d+)", table):
                        owner = next((h for h in own if E.dotted_mac(N.synthetic_mac(h)) == mac), None)
                        if owner is None or own[owner].get(vlan) != mac:
                            p.append(f"{d.hostname}: VLAN {vlan} root {mac} is no collected switch reporting itself root")
                    audit = pd.read_excel(base / "audits" / f"cisco_switch_audit_output_{site}.xlsx", dtype=str)
                    said = set(re.findall(r"VLAN0*(\d+)", str(audit[audit["Hostname"] == d.hostname]["spanningtree_root"].iloc[0])))
                    if said != {v for v, m in own[d.hostname].items() if m == E.dotted_mac(N.synthetic_mac(d.hostname))}:
                        p.append(f"{d.hostname}: the audit's root VLANs differ from its own spanning-tree root output")
                # endpoint ports: configured as the design patches them, and up in show interfaces
                run = sorted((base / "backups" / "cisco").iterdir())[-1]
                cfg = (run / f"{d.hostname}_backup_{run.name}.txt").read_text(encoding="utf-8")
                for port, (mode, vlans, desc, _) in E.port_vlans(net, d.hostname).items():
                    if mode != "access":
                        continue
                    stanza = cfg.split(f"interface {E.long_name(port)}\n", 1)[-1].split("!", 1)[0] \
                        if f"interface {E.long_name(port)}\n" in cfg else ""
                    if f" description {desc}\n" not in stanza or " switchport mode access" not in stanza \
                            or f" switchport access vlan {vlans[0]}\n" not in stanza:
                        p.append(f"{d.hostname}: {port} configuration does not match its patched endpoint")
                    if f"{E.long_name(port)} is up, line protocol is up" not in raw:
                        p.append(f"{d.hostname}: {port} has an endpoint but show interfaces does not show it up")
                # PoE: what each member reports drawing is what its powered devices draw
                used = dict(re.findall(r"(?m)^(\d)\s+740\.0\s+(\d+\.\d)\s", raw))      # malformed: not read
                for m in range(1, d.members + 1):
                    want = round(sum(w for port, _, w, _ in E.poe_loads(net, d) if port[2:].split("/")[0] == str(m)), 1)
                    if abs(float(used.get(str(m), -1)) - want) > 0.05:
                        p.append(f"{d.hostname}: member {m} PoE {used.get(str(m))} W, its powered devices draw {want} W")
                # power supplies: both bays of every member filled; only the design's faulty bay is not OK
                bays = dict(re.findall(r"(?m)^(\d+[AB])\s+PWR-\S+\s+\S+\s+(\S+)", raw))
                if set(bays) != {f"{m}{b}" for m in range(1, d.members + 1) for b in "AB"}:
                    p.append(f"{d.hostname}: power supply bays reported {sorted(bays)}")
                bad = {b for b, s in bays.items() if s != "OK"}
                if bad != ({d.psu_fault} if d.psu_fault else set()):
                    p.append(f"{d.hostname}: power supplies not OK {sorted(bad)}, the design says {d.psu_fault or 'none'}")
                if d.psu_fault and not re.search(r"(?m)^\S+ uptime is \d+ weeks", raw):
                    p.append(f"{d.hostname}: the switch with the failed supply does not report running")
        for d in net.site_devices(site):
            if d.kind == "firewall" and d.collected and d.ha_peer:
                raw = (base / "raw" / f"palo_raw_{d.hostname}.txt").read_text(encoding="utf-8")
                local, _, peer = raw.partition("Peer Information:")
                lv = re.search(r"Build Release\s*:\s*(\S+)", local)
                pv = re.search(r"Build Release\s*:\s*(\S+)", peer)
                match = re.search(r"Build Compatibility\s*:\s*(\S+)", peer)
                if not (lv and pv and match):
                    p.append(f"{d.hostname}: HA versions not reported")
                elif (lv.group(1) == pv.group(1)) != (match.group(1) == "Match") or \
                        pv.group(1) != net.devices[d.ha_peer].software:
                    p.append(f"{d.hostname}: HA peer version and compatibility disagree")
    return p


def unused_ports_up(net, site) -> int:
    """Enabled ports with nothing connected, as the engine counts them from the port status audit
    (asbuilt_extras.unused_ports_up): not connected, not an empty optic cage, not an aggregate."""
    n = 0
    for r in E_port_status_rows(net, site):
        kind = r["Type"].strip().lower()
        if r["Status"] in ("notconnect", "updown") and kind not in ("not present", "unknown", "") \
                and "none" not in kind and not re.match(r"(?i)^(po\d|port-channel|fa0$|mgmt|vlan|lag|mlt)", r["Port"]):
            n += 1
    return n


def E_port_status_rows(net, site):
    import evidence as E
    return E.port_status_rows(net, site)


def validate_report(net, site: str, text: str, history: bool = True) -> list[str]:
    """The generated report agrees with the design and its evidence: device and capability counts
    reconcile, every finding has a confidence and a detailed record, the medium BPDU guard finding
    at HQ stands, the WAN section lists exactly the supplied circuits, no lifecycle row claims a
    verified vendor source, support coverage (covered, expired, unrecorded) reconciles with the
    design, the failed power supply and the support exceptions are each found and name nothing
    else, and HQ compares with July."""
    import pandas as pd
    p = []
    text = re.sub(r"[\r\n]+", "\n", text)            # PDF text lines end in \r\n
    devices = [d for d in net.site_devices(site) if d.collected and d.kind in ("switch", "firewall")]
    m = COMPLETENESS.search(text)
    if not m:
        p.append(f"{site}: collection completeness not stated")
    else:
        done, total, caps, cap_total = map(int, m.groups())
        if (done, total) != (len(devices), len(devices)):
            p.append(f"{site}: {done} of {total} devices fully collected; the design has {len(devices)} collected devices")
        if caps != cap_total:
            p.append(f"{site}: {caps} of {cap_total} capabilities complete")
    # findings: the stated totals reconcile with the register, each with confidence and detail
    m = re.search(r"Findings (\d+) in total: (\d+) high, (\d+) medium, (\d+) low, (\d+) info", text)
    summary = text.split("Summary of findings", 1)[-1].split("Detailed findings", 1)[0]
    rows = re.findall(r"(?m)^(HIGH|MEDIUM|LOW|INFO) (F-[A-Z]+-[0-9A-F]{6})\b", summary)
    if not m:
        p.append(f"{site}: findings total not stated")
    else:
        total, *by = map(int, m.groups())
        counts = [sum(1 for s, _ in rows if s == x) for x in ("HIGH", "MEDIUM", "LOW", "INFO")]
        if total != len(rows) or by != counts:
            p.append(f"{site}: findings stated {total} ({by}) but the register lists {len(rows)} ({counts})")
    detail = text.split("Detailed findings", 1)[-1]
    ids = [fid for _, fid in rows]
    for fid in ids:
        start = detail.find(fid)
        ends = [i for i in (detail.find(o, start + 1) for o in ids if o != fid) if i > start]
        block = detail[start:min(ends, default=len(detail))] if start >= 0 else ""
        if not re.search(r"Confidence ", block):
            p.append(f"{site}: finding {fid} has no detailed record with a confidence")
        elif not re.search(r"\bE-[A-Z]{4}-[0-9A-F]{5}\b|Insufficient evidence|not collected", block):
            p.append(f"{site}: finding {fid} cites no evidence")
    if site == "RTG-HQ" and not re.search(r"(?m)^MEDIUM F-SEC-[0-9A-F]{6} .*\n(?:.*\n){0,2}Access ports have no BPDU guard", summary):
        p.append(f"{site}: the medium BPDU guard finding is missing")
    # WAN: exactly the supplied circuits for this site
    want = {c for s, _, _, c, _, _ in N.WAN_SERVICES if s == site}
    got = set(re.findall(r"\bSYN-(?:INT|EPL|DF|IPB)-[A-Z0-9-]+\b", text))
    if got != want:
        p.append(f"{site}: WAN circuits in the report {sorted(got)} differ from the supplied export {sorted(want)}")
    # lifecycle: nothing claims a verified vendor source
    m = re.search(r"(\d+) of (\d+) rows rest on a verified vendor source", text)
    if m and m.group(1) != "0":
        p.append(f"{site}: {m.group(1)} lifecycle rows claim a verified vendor source")
    # support schedule: every asset classified as the design says, and the totals reconcile
    expect = {}
    for d in devices:
        rec = N.SUPPORT_EXCEPTIONS.get(d.hostname, ("Covered",))
        status = "No matching record" if rec is None else "Expired" if rec[0] == "Expired" else "Covered"
        expect[status] = expect.get(status, 0) + (d.members if d.kind == "switch" else 1)
    row = r"(?m)^\S+ (?:\d+|-) (?:Cisco|Extreme Networks|Palo Alto Networks) \S+ SYN[0-9A-F]{8} "
    got = {s: len(re.findall(row + re.escape(s) + " ", text)) for s in ("Covered", "Expired", "No matching record")}
    if {k: v for k, v in got.items() if v} != expect:
        p.append(f"{site}: support coverage {got} does not reconcile with the design {expect}")
    # the deliberate risks are each found, with their facts, and name nothing else
    flat = re.sub(r"\s+", " ", detail)
    for h, bay in N.PSU_FAULTS.items():
        if net.devices[h].site != site:
            continue
        m = re.search(r"Power, fan or temperature faults: ([^.]*)\.", flat)
        want = f"{h} power supply PSU {bay} (member {bay[:-1]}, slot {bay[-1]}: Bad)"
        if not m or want not in m.group(1):
            p.append(f"{site}: no hardware finding for {h} PSU {bay}")
        elif m.group(1) != want:
            p.append(f"{site}: the hardware finding names more than {h} PSU {bay}: {m.group(1)}")
    for h, rec in N.SUPPORT_EXCEPTIONS.items():
        if net.devices[h].site != site:
            continue
        if rec is None:
            m = re.search(r"Hardware whose serials are not on the support schedule[^:]*: ([^.]*)\.", flat)
            if not m or m.group(1) != h:
                p.append(f"{site}: no unrecorded-support finding for {h} alone")
        else:
            end = pd.Timestamp(rec[2]).strftime("%d %b %Y")
            m = re.search(r"Support has ended \(([^)]*)\) for (\S+) \(", flat)
            if not m or (m.group(1), m.group(2)) != (end, h):
                p.append(f"{site}: no expired-support finding for {h} ending {end}")
    # the unused-port finding is the count the port status evidence gives
    m = re.search(r"(\d+) unused ports are left enabled", text)
    want = unused_ports_up(net, site)
    if (int(m.group(1)) if m else 0) != want:
        p.append(f"{site}: the report counts {m.group(1) if m else 0} unused ports left enabled; the evidence has {want}")
    # finding chronology: dated by the evidence, never after the collection (not the regeneration day)
    late = sorted({d for d in re.findall(r"\b(?:New|Open) since (\d{4}-\d{2}-\d{2})", text) if d > COLLECTION_DATE})
    if late:
        p.append(f"{site}: findings dated after the {COLLECTION_DATE} collection: {late}")
    if any(d.vendor == "cisco" and d.kind == "switch" and d.hostname.endswith("-c01") for d in devices) \
            and re.search(r"outside the collected devices (?:[0-9a-f]{2}:){5}[0-9a-f]{2}", text):   # a table row
        p.append(f"{site}: a spanning-tree root is shown outside the collected devices, but the design's root is collected")
    # "X carries N switches alone" for a core switch at a site with two or more cores: N is what the
    # design attaches to that core and to no other switch at the site (the rest reaches the other core)
    cores = {d.hostname for d in devices if d.kind == "switch" and re.search(r"-c\d\d$", d.hostname)}   # engine tiering
    site_switches = {d.hostname for d in devices if d.kind == "switch"}
    alone = {}
    for d in net.devices.values():
        if d.kind not in ("switch", "router", "firewall") or d.hostname in site_switches:
            continue
        att = {o for _, o, _, l in N.neighbours(net, d.hostname) if o in site_switches and l.kind != "ha"}
        if len(att) == 1:
            alone[next(iter(att))] = alone.get(next(iter(att)), 0) + 1
    for host, n in set(re.findall(r"(\S+) alone carries (\d+) (?:switches|devices?)", text)
                       + re.findall(r"(\S+) carries (\d+) (?:switches|devices?) alone", text)):
        if len(cores) >= 2 and host in cores and int(n) != alone.get(host, 0):
            p.append(f"{site}: the report says {host} alone carries {n}; the design attaches {alone.get(host, 0)} to it alone")
    if re.search(r"Spanning tree not collected for:", text):
        p.append(f"{site}: spanning tree reported not collected for a collected switch")
    if site == "RTG-HQ" and history:
        if not re.search(r"Compared with the snapshot generated 2026-07-20", text):
            p.append(f"{site}: no comparison with the July collection")
        elif not re.search(r"(?m)^software 0 0 2 0 0 0$", text):
            p.append(f"{site}: the two core upgrades are not among the changes")
    return p


if __name__ == "__main__":
    net = N.build()
    problems = validate_network(net)
    if len(sys.argv) > 1:
        problems += validate_evidence(Path(sys.argv[1]))
    for x in problems:
        print("PROBLEM:", x)
    print(f"{len(net.devices)} devices, {len(net.links)} links: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
