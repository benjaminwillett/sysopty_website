"""Writes the synthetic network (network.py) as saved Sysopty evidence, one folder per site.

The files follow the formats the product's collectors write and its offline report reads
(documented in SYNTHETIC_EVIDENCE_GENERATOR.md): switch audit workbooks, the CDP/LLDP mapping
workbook, raw command output, configuration backups, and the inputs for the product's own
topology builder. Every value is generated from the network model; no collected output is
copied. Secrets are never generated: SNMP and AAA keys are absent or placeholders.
"""
from __future__ import annotations

import ast
import json
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

import network as N

RUN = "20261020_020000"           # the fictional collection run (backups folder name)
CLOCK = "10:15:02.123 AEST Tue Oct 20 2026"
COLLECTED = (2026, 10, 20, 10, 15)    # when the files were written (their modification time)
COUNTER_FRACTION = 1.0           # interface counters relative to the October collection


def uptime_days(d) -> int:
    """At the October collection: the HQ cores were reloaded for their upgrade on 15 Aug 2026."""
    return 66 if d.hostname in ("c9500-hq-c01", "c9500-hq-c02") else 200


def cisco_uptime(d) -> str:
    n = uptime_days(d)
    return f"{n // 7} weeks, {n % 7} days, 3 hours, 11 minutes"


@contextmanager
def collection(run, clock, collected, uptime, counter_fraction):
    """Writes an earlier collection: its run name, device clock, file times, uptimes and counters."""
    global RUN, CLOCK, COLLECTED, COUNTER_FRACTION, uptime_days
    saved = RUN, CLOCK, COLLECTED, COUNTER_FRACTION, uptime_days
    RUN, CLOCK, COLLECTED, COUNTER_FRACTION, uptime_days = run, clock, collected, counter_fraction, uptime
    try:
        yield
    finally:
        RUN, CLOCK, COLLECTED, COUNTER_FRACTION, uptime_days = saved


SUPPLIED = (2026, 10, 19, 16, 30)      # when the customer exported its supplied files


def set_collection_times(folder: Path, written_after: float, when=None):
    """The files this collection wrote (modified after written_after) carry the collection's time,
    as the collector's own files would; earlier collections' backups and the history keep theirs."""
    import os
    import time
    t = time.mktime((*(when or COLLECTED), 0, 0, 0, -1))
    for f in folder.rglob("*"):
        if f.is_file() and f.stat().st_mtime >= written_after - 1 and "history" not in f.relative_to(folder).parts:
            os.utime(f, (t, t))
PORT_NAMES_CISCO = {"Gi": "GigabitEthernet", "Te": "TenGigabitEthernet", "Twe": "TwentyFiveGigE", "Hu": "HundredGigE"}


def long_name(port: str) -> str:
    for short, long in sorted(PORT_NAMES_CISCO.items(), key=lambda kv: -len(kv[0])):
        if port.startswith(short) and port[len(short):len(short) + 1].isdigit():
            return long + port[len(short):]
    return port


def location(d: N.Device) -> str:
    return f"{d.site} | {d.room} | {N.SITES[d.site]['address']}"


def capabilities(d: N.Device) -> str:
    return {"switch": "Bridge, Router", "firewall": "Router", "router": "Router",
            "ap": "Bridge, WLAN Access Point"}.get(d.kind, "Station Only")


def site_services(site):
    return N.SITE_SERVICES[site]


# ------------------------------------------------------------------ per-device facts
def port_vlans(net, host):
    """{short port: (mode, [vlans], description)} for a switch's connected ports."""
    out = {}
    for port, other, oport, link in N.neighbours(net, host):
        o = net.devices[other]
        if link.kind == "ha":
            continue
        desc = {"ap": f"AP {other}", "endpoint": f"{o.endpoint_kind} {other}",
                "router": f"WAN CPE {other} (carrier managed)", "firewall": f"{other} {oport}"}.get(
            o.kind if o.kind != "switch" else "", f"{link.purpose} {other} {oport}")
        if o.role == "endpoint":
            desc = o.port_description or f"{o.endpoint_kind} {other}"
        out[port] = (link.mode, list(link.vlans), desc[:60], link.lag)
    return out


def switch_vlans(net, d: N.Device):
    """VLANs on this switch with the access ports in each."""
    vids = set()
    pv = port_vlans(net, d.hostname)
    for mode, vlans, _, _ in pv.values():
        vids.update(vlans)
    vids.update(int(i[4:]) for i in d.svis)
    vids &= set(N.SITE_VLANS[d.site]) | {10}
    vids.add(1)
    rows = []
    for v in sorted(vids):
        ports = [p for p, (mode, vlans, _, _) in pv.items() if mode == "access" and vlans == [v]]
        rows.append((v, "default" if v == 1 else N.VLAN_NAMES.get(v, f"VLAN{v:04d}"), ports))
    return rows


# ------------------------------------------------------------------ audit workbooks
def audit_rows(net, site, vendor):
    rows = []
    for d in sorted(net.site_devices(site), key=lambda x: x.hostname):
        if not (d.collected and d.kind == "switch" and d.vendor == vendor):
            continue
        svc = N.services(d)
        vl = switch_vlans(net, d)
        for m in range(1, d.members + 1):
            if vendor == "cisco":
                vlans = str([{"VLAN": str(v), "Name": n, "Status": "active", "Ports": ", ".join(p)} for v, n, p in vl])
                ifip = str([{"interface": k, "ip": v.split("/")[0]} for k, v in d.svis.items()])
                roots = ", ".join(f"VLAN{v:04d}" for v, (r, _, _, _) in stp_roots(net, d).items()
                                  if r == d.hostname) or "none"
                ntp, dns, logging = str(svc["ntp"]), str(N.DNS), str(svc["syslog"])
            else:
                vlans = ", ".join(str({"Name": n, "VID": str(v), "VR": None}) for v, n, _ in vl)
                ifip = ", ".join(f"{k}={v}" for k, v in d.svis.items())
                roots = ""
                ntp, dns, logging = ", ".join(svc["ntp"]), ", ".join(N.DNS), ", ".join(svc["syslog"])
            rows.append({
                "Hostname": d.hostname, "DNS IP": d.mgmt_ip, "Connection Method": "ssh",
                "Auth Status": "Success", "Privilege Level": "15",
                "Stack Member Number": str(m), "uptime": cisco_uptime(d),
                "Free Ports": "", "Stack Member Role": "Active" if m == 1 else "Standby",
                "Hardware Version": "V02", "Stack Member Current State": "Ready",
                "MAC": N.synthetic_mac(d.hostname, m), "Priority": "15" if m == 1 else "14",
                "Model": d.model, "Serial": N.synthetic_serial(d.hostname, m), "OS Version": d.software,
                "ntp": ntp, "name-server": dns, "vtp_mode": "Transparent" if vendor == "cisco" else "",
                "vtp_domain": "RTG" if vendor == "cisco" else "",
                "spanningtree_mode": "rapid-pvst" if vendor == "cisco" else "",
                "spanningtree_root": roots, "logging": logging, "Location": location(d), "Clock": CLOCK,
                "cdp": "enabled" if vendor == "cisco" else "", "Vlans": vlans, "interface_ip": ifip,
                **({"lldp": "enabled"} if vendor == "extreme" else {}),
            })
    return rows


# ------------------------------------------------------------------ CDP/LLDP mapping workbook
ENDPOINT_PLATFORM = {"printer": "HP LaserJet Enterprise M507", "door controller": "Access controller",
                     "video recorder": "Network video recorder", "UPS": "UPS network card",
                     "IP phone": "Cisco IP Phone 8845", "camera": "IP camera",
                     "BMS controller": "Building management controller"}
POE_WATTS = {"ap": (15.4, 4), "IP phone": (6.3, 2), "camera": (12.9, 3)}     # (watts drawn, class)


def poe_loads(net, d: N.Device):
    """[(port, device, watts, class)]: what each powered device on the switch draws."""
    out = []
    for p, o, _, _ in sorted(N.neighbours(net, d.hostname)):
        od = net.devices[o]
        load = POE_WATTS.get("ap" if od.kind == "ap" else od.endpoint_kind)
        if load:
            out.append((p, od, *load))
    return out


def mapping_rows(net, site):
    rows = []
    for l in net.links:
        for a, ap, b, bp in ((l.a, l.a_port, l.b, l.b_port), (l.b, l.b_port, l.a, l.a_port)):
            da, db = net.devices[a], net.devices[b]
            if da.site != site or not da.collected:
                continue
            if da.kind == "firewall" and l.kind != "ha":
                continue                           # firewall rows come from the switches' view
            if not db.announces:
                continue                           # a workstation sends no CDP/LLDP
            row = {
                "Hostname": a, "Switch Interface": ap, "Local Member Ports": "", "Neighbour": db.lldp_name or b,
                "Switch Port ID": bp, "Neighbour Member Ports": "",
                "Firewall Hostname": b if db.kind == "firewall" else "",
                "Firewall Interface": bp if db.kind == "firewall" else "",
                "Platform": db.platform_string, "Media Type": l.media,
                "Data Source": "inferred_ha_peer" if l.kind == "ha" else "",
                "Neighbour Source": "lldp_system_name", "Chassis ID": N.device_mac(db),
                "Port Description": l.purpose if l.kind == "ha" else "",
                "Neighbour Address": db.mgmt_ip, "Neighbour Capabilities": capabilities(db),
                "Neighbour Vendor": {"cisco": "Cisco", "extreme": "Extreme Networks", "palo": "Palo Alto Networks",
                                     "fortinet": "Fortinet"}.get(db.vendor, ""),
            }
            if db.role == "endpoint":
                row.update(Platform=ENDPOINT_PLATFORM[db.endpoint_kind],
                           **{"Neighbour Capabilities": "Host, Phone" if db.endpoint_kind == "IP phone" else "Station Only",
                              "Neighbour Vendor": "Cisco" if db.endpoint_kind == "IP phone" else ""})
            rows.append(row)
    return rows


# ------------------------------------------------------------------ raw command output
def cisco_raw(net, d: N.Device) -> str:
    pv = port_vlans(net, d.hostname)
    def psu_row(m, bay, serial_index):
        # A failed supply: Status, Sys Pwr and PoE Pwr all "Bad" (IOS-XE Catalyst 9300 format).
        bad = d.psu_fault == f"{m}{bay}"
        return (f"{m}{bay}  PWR-C1-715WAC       {N.synthetic_serial(d.hostname, serial_index + m)[:11]}  "
                f"{'Bad' if bad else 'OK':<17}{'Bad' if bad else 'Good':<9}{'Bad' if bad else 'Good':<9}715")
    psu = "\n".join(f"{psu_row(m, 'A', 10)}\n{psu_row(m, 'B', 20)}" for m in range(1, d.members + 1))
    loads = poe_loads(net, d)
    poe_rows = "\n".join(f"{p:<9} auto   on         {w:<7} {(od.model or ENDPOINT_PLATFORM.get(od.endpoint_kind, ''))[:18]:<18}  "
                         f"{c}     30.0" for p, od, w, c in loads)
    used_by = {m: round(sum(w for p, _, w, _ in loads if p[2:].split("/")[0] == str(m)), 1)
               for m in range(1, d.members + 1)}
    ifaces = []
    for p, (mode, vlans, desc, lag) in sorted(pv.items()):
        speed = "1000Mb/s" if p.startswith("Gi") else "10Gb/s" if p.startswith("Te") else \
            "25Gb/s" if p.startswith("Twe") else "100Gb/s"
        ifaces.append(f"{long_name(p)} is up, line protocol is up (connected)\n"
                      f"  Hardware is {long_name(p).rstrip('0123456789/')}, address is {N.synthetic_mac(d.hostname + p)}\n"
                      f"  Description: {desc}\n"
                      f"  Full-duplex, {speed}, media type is {'10/100/1000BaseTX' if p.startswith('Gi') else 'SFP'}\n"
                      f"     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored\n"
                      f"     0 output errors, 0 collisions, 0 interface resets")
    for svi, ip in d.svis.items():
        ifaces.append(f"{svi} is up, line protocol is up\n  Hardware is Ethernet SVI\n"
                      f"  Internet address is {ip}")
    ospf = N.ospf_neighbours(net, d.hostname)
    ospf_rows = "\n".join(f"{N.router_id(net, o):<15} 1   FULL/BDR        00:00:3{i}    {ip:<15} {ifc}"
                          for i, (o, ip, ifc) in enumerate(ospf))
    gw = next((ip.split("/")[0] for k, ip in d.svis.items() if k == "Vlan10"), d.mgmt_ip)
    gw = ".".join(gw.split(".")[:3] + ["1"])
    return "\n\n".join([
        "=== show version | include uptime ===\n"
        f"{d.hostname} uptime is {cisco_uptime(d)}",
        "=== show environment all ===\n"
        + "\n".join(f"Switch {m} FAN 1 is OK\nSwitch {m} FAN 2 is OK\nSwitch {m} FAN 3 is OK\n"
                    f"Switch {m}: SYSTEM TEMPERATURE is OK"
                    for m in range(1, d.members + 1))
        + "\n"
        "SW  PID                 Serial#     Status           Sys Pwr  PoE Pwr  Watts\n"
        "--  ------------------  ----------  ---------------  -------  -------  -----\n" + psu,
        "=== show power inline ===\nModule   Available     Used     Remaining\n"
        "          (Watts)     (Watts)    (Watts)\n------   ---------   --------   ---------\n"
        + "\n".join(f"{m}           740.0       {used_by[m]:5.1f}       {740.0 - used_by[m]:5.1f}"
                    for m in range(1, d.members + 1))
        + "\nInterface Admin  Oper       Power   Device              Class Max\n" + poe_rows,
        *(["=== show spanning-tree root ===\n" + stp_root_table(net, d)] if stp_root(net, d) else []),
        "=== show ip default-gateway ===\n" + (gw if not d.hsrp else "IP routing is enabled"),
        "=== show ip ospf neighbor ===\n" + (
            "\nNeighbor ID     Pri   State           Dead Time   Address         Interface\n" + ospf_rows
            if ospf else ""),
        "=== show ip protocols ===\n" + ('*** IP Routing is NSF aware ***\n\nRouting Protocol is "ospf 1"\n'
                                         f"  Router ID {d.mgmt_ip}\n" if ospf else ""),
        "=== show interfaces ===\n" + "\n".join(ifaces) + f"\n{d.hostname}#",
    ]) + "\n"


def dotted_mac(mac: str) -> str:
    h = mac.replace(":", "")
    return f"{h[0:4]}.{h[4:8]}.{h[8:12]}"


def stp_root(net, d: N.Device):
    """The site's spanning-tree root for a Cisco switch: the site's Cisco -c01 core, configured with
    priority 24576 for every VLAN (spanning-tree vlan 1-4094 priority 24576); None at a site without one."""
    return next((x for x in net.site_devices(d.site) if x.vendor == "cisco" and x.kind == "switch"
                 and x.collected and x.hostname.endswith("-c01")), None)


def stp_roots(net, d: N.Device) -> dict:
    """{vlan: (root host, root priority, cost, root port)} for a Cisco switch. The site's -c01 core is
    root for every VLAN it carries; a VLAN it does not carry has this switch as its own root, at the
    secondary priority 28672 (spanning-tree vlan 1-4094 priority 28672 on the other switches' template)."""
    root = stp_root(net, d)
    if root is None:                     # no designed root at this site (the branch): not reported
        return {}
    up = sorted((p, o) for p, o, _, l in N.neighbours(net, d.hostname) if l.mode == "trunk"
                and net.devices[o].kind == "switch" and net.devices[o].site == d.site)
    direct = next((p for p, o in up if o == root.hostname), None)
    via = direct or next((p for p, o in up if net.devices[o].role in ("core", "distribution")), "")
    carried = {v for v, _, _ in switch_vlans(net, root)}
    out = {}
    for v, _, _ in switch_vlans(net, d):
        if root.hostname == d.hostname:
            out[v] = (d.hostname, 24576 + v, 0, "")
        elif v in carried:
            out[v] = (root.hostname, 24576 + v, 2 if direct else 4, long_name(via))
        else:
            out[v] = (d.hostname, 28672 + v, 0, "")
    return out


def stp_root_table(net, d: N.Device) -> str:
    """'show spanning-tree root' (IOS-XE): per VLAN the root's ID, the cost to it and the root port.
    The root shows cost 0 and no root port; the others reach it over their uplink towards it."""
    head = ("Vlan                   Root ID          Cost    Time  Age Dly  Root Port\n"
            "---------------- -------------------- --------- ----- --- ---  ------------\n")
    return head + "\n".join(
        f"VLAN{v:04d}         {prio:<5} {dotted_mac(N.synthetic_mac(r))}  {cost:>8}    2   20  15  {port}".rstrip()
        for v, (r, prio, cost, port) in stp_roots(net, d).items())


def extreme_l3_raw(net, d: N.Device) -> str:
    blocks = []
    for i, (p, o, op, l) in enumerate(sorted((x for x in N.neighbours(net, d.hostname)
                                              if net.devices[x[1]].announces)), start=1):
        od = net.devices[o]
        caps = "Bridge(4), Router(16)" if od.kind == "switch" else \
            "Bridge(4), WLAN Access Point(16)" if od.kind == "ap" else "Router(16)" if od.kind in ("router", "firewall") \
            else "Station Only(128)"
        fa = "\n  Fabric Attach:\n    Type: 6" if od.kind == "ap" else ""
        poe = "\n  DOT3_AT:\n    Allocated: 154" if od.kind == "ap" else ""
        blocks.append(f"LLDP neighbor with index {i} discovered on port {p}:\n"
                      f"  Chassis:\n    ID: {N.device_mac(od)}\n    Name: {od.lldp_name or o}\n"
                      f"    Description: {od.platform_string}\n    Capabilities: {caps}\n"
                      f"  Port index: {i}\n    ID: {op}\n    Description: {op}{fa}{poe}")
    psu = (f"Power Supply Info :\n        Ps#1 Status            : UP\n        Ps#1 Type              : AC\n"
           f"        Ps#1 Description       : AC Power Supply\n        Ps#1 Serial Number     : {N.synthetic_serial(d.hostname, 31)}\n"
           f"        Ps#1 Part Number       : XN-ACPWR-715W-FB\n"
           f"        Ps#2 Status            : UP\n        Ps#2 Type              : AC\n"
           f"        Ps#2 Description       : AC Power Supply\n        Ps#2 Serial Number     : {N.synthetic_serial(d.hostname, 32)}\n"
           f"        Ps#2 Part Number       : XN-ACPWR-715W-FB\n")
    sysinfo = (f"General Info :\n\n        SysDescr     : {d.model} ({d.software})\n        SysName      : {d.hostname}\n"
               f"        SysUpTime    : {uptime_days(d)} day(s), 03:11:07\n        SysLocation  : {location(d)}\n\n"
               f"Chassis Info:\n\n        Chassis            : {d.model}\n        Serial#            : "
               f"{N.synthetic_serial(d.hostname)}\n\n{psu}\nTemperature Info :\n\n"
               f"        Chip                       41              85              100\n"
               f"        Front                      27              60               75\n"
               f"        Rear                       33              65               80\n\nFan Info :\n\n"
               + "".join(f"        Tray 1 Fan {i}   up   lowSpeed   4800   unknown\n" for i in range(1, 5)))
    drawn = sum(w for _, _, w, _ in poe_loads(net, d))
    poe = (f"Unit 1 PoE Main Status\n  Available DTE Power         : 740 watts\n"
           f"  Power Consumption           : {drawn:.1f} watts\n") if "5420" in d.model else ""
    isis = [(o, op) for p, o, op, l in N.neighbours(net, d.hostname) if net.devices[o].vendor == "extreme"
            and net.devices[o].kind == "switch" and net.devices[o].site == d.site]
    isis_rows = "\n".join(f"Port{p:<10} 1  UP        1d 03:11:07    127   {N.synthetic_mac(o).replace(':', '')[:4]}."
                          f"{N.synthetic_mac(o).replace(':', '')[4:8]}.{N.synthetic_mac(o).replace(':', '')[8:]}  {o}"
                          for p, o, op, l in N.neighbours(net, d.hostname) if (o, op) in isis)
    # Port tables for every port on the switch (connected ports up, the rest down).
    pv = port_vlans(net, d.hostname)
    ports = [f"{g[2]}{n}" for g in N.PLATFORMS[d.platform][4].values() for n in range(g[3], g[4] + 1)]
    state_rows, name_rows = [], []
    for i, p in enumerate(ports, start=192):
        up = p in pv
        fibre = voss_fibre(d, p)
        media = ("10GbSR" if up else "GbicNone") if fibre else "1000BaseTX"
        state_rows.append(f"{p:<9}{i:<7}{media:<12}true   false   1950   {N.synthetic_mac(d.hostname + p)}   up     "
                          f"{'up' if up else 'down'}")
        name = pv[p][2][:18].replace(" ", "-") if up else ""
        name_rows.append(f"{p:<9}{name:<20}{media:<12}{'up' if up else 'down':<9}{'full' if up else 'half':<7}"
                         f"{('10000' if fibre else '1000') if up else '0':<8}"
                         f"{'Trunk' if up and pv[p][0] == 'trunk' else 'Access'}")
    rule = "=" * 98
    port_state = (f"{rule}\n                                          Port Interface\n{rule}\n"
                  "PORT     INDEX  DESCRIPTION LINKTRAP PORTLOCK MTU    PHYSICAL ADDRESS    STATUS ADMIN  OPERATE\n"
                  + "-" * 98 + "\n" + "\n".join(state_rows) + f"\n{d.hostname}:1#")
    port_names = (f"{rule}\n                                          Port Name\n{rule}\n"
                  "PORT     NAME                DESCRIPTION OPERATE  OPERATE OPERATE VLAN\n"
                  "NUM                                      STATUS   DUPLX   SPEED\n" + "-" * 98 + "\n"
                  + "\n".join(name_rows) + f"\n{d.hostname}:1#")
    nick = f"0.{N.SITES[d.site]['octet']:02x}.{int(d.mgmt_ip.split('.')[-1]):02x}"
    spbm = (f"SPBM INSTANCE        : 1\nB-VID                : 4051,4052\nPRIMARY B-VID        : 4051\n"
            f"NICK-NAME            : {nick}\nLSDB TRAP            : disable\n")
    out = [f"=== lldp_detail_out ({sum(len(b) for b in blocks)} chars) ===\n" + "\n".join(blocks),
           f"=== port_state_out ({len(port_state)} chars) ===\n" + port_state,
           f"=== port_name_out ({len(port_names)} chars) ===\n" + port_names,
           f"=== isis_spbm_out ({len(spbm)} chars) ===\n" + spbm,
           f"=== sysinfo_out ({len(sysinfo)} chars) ===\n" + sysinfo,
           f"=== isis_adj_out ({len(isis_rows)} chars) ===\nISIS Adjacencies\n"
           "INTERFACE    L STATE     UPTIME         PRI HOLDTIME SYSID          HOST-NAME\n" + isis_rows]
    if poe:
        out.append(f"=== poe_out ({len(poe)} chars) ===\n" + poe)
    return "\n\n".join(out) + "\n"


def palo_raw(net, fw: N.Device) -> str:
    hw = sorted({p for p, _, _, l in N.neighbours(net, fw.hostname)} | {i[0] for i in fw.fw_interfaces
                                                                        if i[0].startswith("ethernet")},
                key=lambda p: [int(x) for x in p.replace("ethernet", "").split("/")])
    ae_members = sorted({p for p, o, op, l in N.neighbours(net, fw.hostname) if l.lag})
    hw_rows = "\n".join(f"{p:<24}{16 + int(p.split('/')[1]):<6}{'10000/full/up' if p in ae_members else '1000/full/up':<30}"
                        f"{N.synthetic_mac(fw.hostname + p)}" for p in hw)
    ae = f"ae1     members:\n        {' '.join(ae_members)}\n" if ae_members else ""
    header = (f"{'name':<20}{'id':<6}{'vsys':<5}{'zone':<17}{'forwarding':<25}{'tag':<7}{'address':<30}")
    rows = []
    for i, (name, zone, tag, address) in enumerate(fw.fw_interfaces):
        rows.append(f"{name:<20}{256 + i:<6}{'1':<5}{zone:<17}{('ha' if address == 'ha' else 'vr:default'):<25}"
                    f"{tag:<7}{('N/A' if address == 'ha' else address):<30}")
    zones = sorted({z for _, z, _, a in fw.fw_interfaces if z})
    ha = ""
    if fw.ha_peer:
        ports = [n for n, _, _, a in fw.fw_interfaces if a == "ha"]
        ha = ("\nGroup 1:\n  Mode: Active-Passive\n  Local Information:\n"
              f"    Version                       : 1\n    Mode                          : Active-Passive\n"
              f"    State                         : {fw.ha_state} (last {uptime_days(fw)} days)\n    Priority                      : "
              f"{'100' if fw.ha_state == 'active' else '110'}\n    Preemptive                    : no\n"
              + palo_versions(fw) +
              f"    Running Configuration         : synchronized\n"
              f"    HA1 Control Link Information:\n      IP Address                  : 192.0.2.{1 if fw.ha_state == 'active' else 2}/30\n"
              f"      Interface                   : {ports[0]}\n"
              f"    HA2 Data Link Information:\n      Interface                   : {ports[1]}\n"
              f"  Peer Information:\n    Connection status             : up\n"
              f"    State                         : {'passive' if fw.ha_state == 'active' else 'active'}\n"
              + palo_versions(net.devices[fw.ha_peer])
              + "".join(f"    {k + ' Compatibility':<30}: Match\n"
                        for k in ("Build", "Application Content", "Anti-Virus", "Threat Content", "URL Database"))
              +
              f"    HA1 Control Link Information:\n      Interface                   : {ports[0]}\n"
              f"    HA2 Data Link Information:\n      Interface                   : {ports[1]}\n")
    default = next(a for n, z, t, a in fw.fw_interfaces if z == "untrust")
    gw = ".".join(default.split("/")[0].split(".")[:3] + [str(int(default.split("/")[0].split(".")[3]) - 1)])
    static = "\n".join(f"{dst:<20}{gw:<18}{'10':<8}{'A S':<8}{'':<10}{'ethernet1/1'}" for dst in ("0.0.0.0/0",))
    rules = "\n".join(f'"{z}-to-untrust; index: {i}" {{\n        from {z};\n        to untrust;\n'
                      f'        source any;\n        destination any;\n        action allow;\n}}'
                      for i, z in enumerate(zones, start=1) if z != "untrust")
    untrust = default.split("/")[0]
    nat = "\n".join(f'"{z}-outbound; index: {i}" {{\n        nat-type ipv4;\n        from {z};\n'
                     f'        source any;\n        to untrust;\n        to-interface ethernet1/1 ;\n'
                     f'        destination any;\n        service any/any/any;\n'
                     f'        translate-to "src: {untrust} (dynamic-ip-and-port) (pool idx: {i})";\n'
                     f'        terminal no;\n}}'
                     for i, z in enumerate((z for z in zones if z not in ("untrust", "dmz")), start=1))
    return "\n\n".join([
        "=== show system info ===\n"
        f"hostname: {fw.hostname}\nip-address: {fw.mgmt_ip}\nnetmask: 255.255.255.0\nmodel: {fw.model}\n"
        f"serial: {N.synthetic_serial(fw.hostname)}\nsw-version: {fw.software}\napp-version: {APP_CONTENT}\n"
        f"threat-version: {APP_CONTENT}\nav-version: {AV_CONTENT}\nurl-db: paloaltonetworks\n"
        f"url-filtering-version: {URL_DB}\nuptime: {uptime_days(fw)} days, 3:11:07",
        "=== show interface all ===\n"
        f"total configured hardware interfaces: {len(hw)}\n\n"
        f"{'name':<24}{'id':<6}{'speed/duplex/state':<30}mac address\n{'-' * 80}\n{hw_rows}\n\n"
        f"aggregation groups: {1 if ae else 0}\n\n{ae}\n"
        f"total configured logical interfaces: {len(rows)}\n\n{header}\n"
        f"{'-' * 19} {'-' * 5} {'-' * 4} {'-' * 16} {'-' * 24} {'-' * 6} {'-' * 29}\n" + "\n".join(rows),
        "=== show high-availability all ===\n" + (ha or "HA not enabled"),
        "=== show logging-status ===\n"
        f"Connection IP           : lr-{N.LOG_COLLECTOR}\nConnection Status       : lr - Active",
        "=== show routing route type static ===\n"
        "VIRTUAL ROUTER: default (id 1)\n  ==========\n"
        f"{'destination':<20}{'nexthop':<18}{'metric':<8}{'flags':<8}{'age':<10}interface\n" + static,
        "=== show routing route destination 0.0.0.0/0 ===\n"
        "VIRTUAL ROUTER: default (id 1)\n  ==========\n"
        f"{'destination':<20}{'nexthop':<18}{'metric':<8}{'flags':<8}{'age':<10}interface\n" + static,
        "=== show routing summary ===\nVIRTUAL ROUTER: default (id 1)\n  ==========\n"
        f"Route Table:\n    All Routes (total): {len(fw.fw_interfaces) + 2}",
        "=== show system environmentals ===\n---Thermal---\n"
        # The first True/False on a row is the alarm flag: False = no alarm.
        "        Slot 1  Temperature near CPU      False  40.1  0.0  70.0\n---Fans---\n"
        "        Slot 1  Fan #1 RPM                False  6000  1500\n"
        "        Slot 1  Fan #2 RPM                False  6020  1500\n---Power Supplies---\n"
        "        Slot 1  Power Supply #1 (left)    False  True  True\n"
        "        Slot 1  Power Supply #2 (right)   False  True  True",
        "=== show lldp neighbors all ===\n" + "\n".join(
            f"{p}\n    Chassis ID: {N.synthetic_mac(o)}\n    Port ID: {op}\n    System name: {o}\n"
            f"    System description: {net.devices[o].platform_string}"
            for p, o, op, l in sorted(N.neighbours(net, fw.hostname)) if l.kind != "ha"),
        "=== request license info ===\n"
        "License entry:\nFeature: Threat Prevention\nDescription: Threat Prevention\n"
        "Issued: October 01, 2026\nExpires: October 01, 2027\nExpired?: no\n\n"
        "License entry:\nFeature: Advanced URL Filtering\nDescription: URL filtering\n"
        "Issued: October 01, 2026\nExpires: October 01, 2027\nExpired?: no",
        "=== show running security-policy ===\n" + rules,
        "=== show running nat-policy ===\n" + nat,
        "=== show vpn tunnel ===\n"
        "TnID     Name(Gateway)                                   Local Proxy IP        Ptl:Port  "
        "Remote Proxy IP       Ptl:Port  Proposals\n" + "-" * 120 + "\n\nShow IPSec tunnel config: total 0 tunnels found.",
    ]) + "\n"


APP_CONTENT, AV_CONTENT, URL_DB = "8925-9201", "5012-5532", "20261019.20123"


def palo_versions(fw: N.Device) -> str:
    """The software and content versions 'show high-availability all' reports for one firewall."""
    return "".join(f"    {k:<30}: {v}\n" for k, v in (
        ("Build Release", fw.software), ("URL Database", URL_DB), ("Application Content", APP_CONTENT),
        ("Anti-Virus", AV_CONTENT), ("Threat Content", APP_CONTENT)))


def voss_fibre(d: N.Device, port: str) -> bool:
    """SFP/SFP28 cages: every port of a 7520-48Y; the uplink ports of the others."""
    return d.platform == "vsp7520" or port.startswith("2/") or int(port.split("/")[1]) > 48


def voss_stp(net, d: N.Device):
    """(root bridge host, root port, cost, {port: (role, state)}) for a Fabric Engine switch.

    MSTP runs on the access side only: Fabric Connect (IS-IS) links to other Fabric Engine switches
    at the site do not take part. A switch dual-homed to the Cisco cores sees the spanning-tree
    root (the first core, root for the user VLANs) on its first uplink and blocks the second; a
    switch with no spanning-tree neighbour is its own CIST root."""
    fabric = {p for p, o, _, _ in N.neighbours(net, d.hostname)
              if net.devices[o].vendor == "extreme" and net.devices[o].kind == "switch"
              and net.devices[o].site == d.site}
    to_cisco = sorted((p, o) for p, o, _, l in N.neighbours(net, d.hostname)
                      if net.devices[o].vendor == "cisco" and net.devices[o].kind == "switch"
                      and net.devices[o].site == d.site)
    root = next((o for _, o in to_cisco if o.endswith("-c01")), d.hostname)
    root_port = next((p for p, o in to_cisco if o == root), None)
    roles = {}
    for p in sorted(port_vlans(net, d.hostname)):
        if p in fabric:
            continue
        if p == root_port:
            roles[p] = ("Root", "Forwarding")
        elif any(p == q for q, _ in to_cisco):
            roles[p] = ("Alternate", "Discarding")
        else:
            roles[p] = ("Designated", "Forwarding")
    return root, root_port, (2000 if root_port else 0), roles


def voss_asbuilt_raw(net, d: N.Device) -> str:
    """The Fabric Engine as-built batch the engine reads (show spanning-tree mstp status / port role,
    show interfaces gigabitEthernet error / statistics). Bridge identifiers are priority + the
    switch's synthetic (locally administered) MAC."""
    root, root_port, cost, roles = voss_stp(net, d)
    own, root_mac = N.synthetic_mac(d.hostname), N.synthetic_mac(root)
    rprio = "60:00" if root != d.hostname else "80:00"
    rule = "=" * 98
    status = (f"{rule}\n                              MSTP Status\n{rule}\n"
              f"Bridge Address                 : {own}\n"
              f"Cist Root                      : {rprio}:{root_mac}\n"
              f"Cist Regional Root             : 80:00:{own}\n"
              f"Cist Root Port                 : {root_port or 'cpp'}\n"
              f"Cist Root Cost                 : {cost}\n"
              f"Cist Regional Root Cost        : 0\n"
              f"Cist Bridge Priority           : 32768\n"
              f"Cist Max Age                   : 20 seconds\n"
              f"Cist Forward Delay             : 15 seconds\n"
              f"Cist Instance Ports            : {', '.join(sorted(roles)) or 'none'}\n")
    role_rows = "\n".join(f"{p:<10}{192 + i:<11}{r:<14}{st:<14}Enabled         Enabled"
                          for i, (p, (r, st)) in enumerate(sorted(roles.items())))
    port_roles = (f"{rule}\n                       MSTP Port Roles and States\n{rule}\n"
                  "Port-Num  Port-Index Port-Role     Port-State    PortSTPStatus   PortOperStatus\n"
                  + "-" * 98 + "\n" + role_rows)
    up = sorted(port_vlans(net, d.hostname))
    errors = (f"{rule}\n                              Port Ethernet Error\n{rule}\n"
              "PORT     ERROR   ERROR   FRAMES  TOO     LINK    CARRIER CARRIER SQETEST IN\n"
              "NUM      ALIGN   FCS     LONG    SHORT   FAILURE SENSE   ERRORS  ERRORS  DISCARD\n"
              + "-" * 107 + "\n"
              + "\n".join(f"{p:<9}{0:<8}{0:<8}{0:<8}{0:<8}{0:<8}{0:<8}{0:<8}{0:<8}{0}" for p in up))
    stats = ("PORT     IN                  OUT                  IN                   OUT\n"
             "NUM      OCTETS               OCTETS               PACKET               PACKET\n" + "-" * 114 + "\n"
             + "\n".join(f"{p:<9}{o_in:<21}{o_out:<21}{o_in // 700:<21}{o_out // 700}"
                         for p in up for o_in, o_out in [(int(COUNTER_FRACTION * (N.h("octets-in", d.hostname, p) % 9_000_000_000_000 + 10**9)),
                                                          int(COUNTER_FRACTION * (N.h("octets-out", d.hostname, p) % 9_000_000_000_000 + 10**9)))]))
    return (f"=== show spanning-tree mstp status ===\n{status}\n"
            f"=== show spanning-tree mstp port role ===\n{port_roles}\n\n"
            f"=== show interfaces gigabitEthernet error ===\n{errors}\n\n"
            f"=== show interfaces gigabitEthernet statistics ===\n{stats}\n")


def _cisco_type(platform: str, short: str, connected: bool, media: str) -> str:
    if short.startswith("Gi"):
        return "10/100/1000BaseTX"
    if short.startswith("Te") and platform == "c9300ux" and "/0/" in short:
        return "100/1000/2.5G/5G/10GBaseTX"
    if not connected:
        return "Not Present"                       # an empty SFP cage
    optic = {"Te": "SFP-10GBase", "Twe": "SFP-25GBase", "Hu": "QSFP-100G"}[
        next(k for k in ("Twe", "Te", "Hu") if short.startswith(k))]
    return f"{optic}-{'LR' if media == 'smf' else 'SR'}" if optic != "QSFP-100G" else \
        f"QSFP-100G-{'LR4' if media == 'smf' else 'SR4'}"


def port_status_rows(net, site):
    """The port status audit (show interfaces status / VOSS port state): every port of every
    collected switch. Connected ports are those with a link in the model; the rest are
    not connected (enabled: neither make's backup shuts them)."""
    rows = []
    for d in net.site_devices(site):
        if not (d.collected and d.kind == "switch"):
            continue
        pv = port_vlans(net, d.hostname)
        media = {p: l.media for p, _, _, l in N.neighbours(net, d.hostname)}
        groups = N.PLATFORMS[d.platform][4]
        for m in range(1, (d.members if d.vendor == "cisco" else 1) + 1):
            for short, _long, prefix, first, last in groups.values():
                pre = prefix.replace("1/", f"{m}/", 1) if d.vendor == "cisco" and prefix.startswith("1/") else prefix
                for n in range(first, last + 1):
                    port = f"{short}{pre}{n}"
                    up = port in pv
                    mode, vlans, desc, _ = pv.get(port, ("", [], "", ""))
                    vlan = ("trunk" if mode == "trunk" else str(vlans[0])) if up else "1"
                    if d.vendor == "cisco":
                        speed = {"Gi": "a-1000", "Te": "a-10G", "Twe": "a-25G", "Hu": "a-100G"}[short] if up else "auto"
                        rows.append({"Hostname": d.hostname, "Port": port, "Name": desc, "Status":
                                     "connected" if up else "notconnect", "Vlan": vlan,
                                     "Duplex": "a-full" if up else "auto", "Speed": speed,
                                     "Type": _cisco_type(d.platform, port, up, media.get(port, ""))})
                    else:
                        fibre = voss_fibre(d, port)
                        rows.append({"Hostname": d.hostname, "Port": port, "Name": desc, "Status":
                                     "upup" if up else "updown", "Vlan": vlan,
                                     "Duplex": "full" if up else "half",
                                     "Speed": ("10000" if fibre else "1000") if up else "0",
                                     "Type": ("10GbSR" if up else "GbicNone") if fibre else "1000BaseTX"})
    return rows


# ------------------------------------------------------------------ the customer's supplied files
WAN_EXPORT = "RTG_wan_services_export_20261019.csv"
SCHEDULE = "RTG_support_schedule_20261019.xlsx"
SCHEDULE_RECORD = "RTG_support_schedule_20261019.verified.json"     # <schedule without extension>.verified.json
SCHEDULE_VERIFIED = {"verified_by": "Riverside Technology Group IT asset management (synthetic)",
                     "verified_on": "2026-10-19",
                     "source": "the vendors' contract portals, checked against this schedule (synthetic record)"}


def wan_rows(net):
    """The carrier's service export (network.WAN_SERVICES), with the hand-off each service
    lands on as the model connects it."""
    rows = []
    for site, service, kind, circuit, bandwidth, ends in N.WAN_SERVICES:
        handoff = "-"
        if kind == "Internet":
            port, sw, sport, link = next((op, o, p, l) for p, o, op, l in N.neighbours(net, ends[0])
                                         if net.devices[o].kind == "switch")
            handoff = f"{ends[0]} (carrier CPE) to {sw} {port}, VLAN {link.vlans[0]}"
        elif ends:
            handoff = " to ".join(ends)
        rows.append({"Site Name": site, "Services": service, "Data Type": kind, "Status": "Active",
                     "Circuit ID": circuit, "Bandwidth": bandwidth, "Carrier": N.CARRIER, "Hand-off": handoff,
                     "Service Start": "2024-07-01"})
    return rows


def schedule_rows(net):
    """The customer's maintenance schedule: one record per collected switch unit and firewall,
    matched by serial. Core, distribution and firewalls on 24x7x4, access on 8x5xNBD."""
    brand = {"cisco": "Cisco", "extreme": "Extreme Networks", "palo": "Palo Alto Networks"}
    rows = []
    for d in sorted(net.devices.values(), key=lambda x: x.hostname):
        if not (d.collected and d.kind in ("switch", "firewall")):
            continue
        sla = "24x7x4" if d.kind == "firewall" or d.role in ("core", "distribution") else "8x5xNBD"
        if d.hostname in N.SUPPORT_EXCEPTIONS and N.SUPPORT_EXCEPTIONS[d.hostname] is None:
            continue                               # never added to the customer's schedule
        status, start, end = N.SUPPORT_EXCEPTIONS.get(d.hostname) or ("Active", "2025-07-01", "2027-06-30")
        for m in range(1, (d.members if d.kind == "switch" else 1) + 1):
            rows.append({"Serial No": N.synthetic_serial(d.hostname, m), "Brand": brand[d.vendor],
                         "Device Code": d.model, "Site Name": d.site, "Site": N.SITES[d.site]["address"],
                         "Start Date": start, "Actual End Date": end, "SLA": sla,
                         "Device Support Status": status,
                         "Customer Device Name": d.hostname + (f" (member {m})" if d.kind == "switch" and d.members > 1 else "")})
    return rows


def write_supplemental(net, folder: Path):
    """The customer's supplied files, in the customer's _supplemental folder (the engine reads
    them as supplied, never as discovered)."""
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(wan_rows(net)).to_csv(folder / WAN_EXPORT, index=False)
    pd.DataFrame(schedule_rows(net)).to_excel(folder / SCHEDULE, index=False)
    (folder / SCHEDULE_RECORD).write_text(json.dumps(SCHEDULE_VERIFIED, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ configuration backups
def cisco_backup(net, d: N.Device) -> str:
    svc = N.services(d)
    pv = port_vlans(net, d.hostname)
    lines = ["!", "version 17.9", "service timestamps log datetime msec localtime show-timezone",
             "service password-encryption", "!", f"hostname {d.hostname}", "!",
             "aaa new-model", "aaa group server tacacs+ RTG-TACACS", " server name RTG-TACACS-1",
             " server name RTG-TACACS-2", "aaa authentication login default group RTG-TACACS local",
             "aaa authorization exec default group RTG-TACACS local", "!",
             "ip routing" if d.hsrp else "no ip routing", "ip domain name corp.example.com"]
    lines += [f"ip name-server {' '.join(N.DNS)}", "ip ssh version 2", "!", "vtp mode transparent", "!",
              "spanning-tree mode rapid-pvst", "spanning-tree portfast bpduguard default", "!"]
    for v, name, _ in switch_vlans(net, d):
        if v != 1:
            lines += [f"vlan {v}", f" name {name}", "!"]
    lags = sorted({lag for _, _, _, lag in pv.values() if lag})
    for lag in lags:
        lines += [f"interface Port-channel{lag[2:]}", " switchport mode trunk", "!"]
    for p, (mode, vlans, desc, lag) in sorted(pv.items()):
        lines += [f"interface {long_name(p)}", f" description {desc}"]
        if mode == "access":
            lines += [" switchport mode access", f" switchport access vlan {vlans[0]}"]
            if vlans[0] == 20:
                lines += [" switchport voice vlan 30"]
            lines += [" spanning-tree portfast"]
        else:
            lines += [" switchport mode trunk", f" switchport trunk allowed vlan {','.join(map(str, vlans))}"]
        if lag:
            lines += [f" channel-group {lag[2:]} mode active"]
        lines += ["!"]
    for svi, ip in d.svis.items():
        net_ = ip.split("/")[0]
        lines += [f"interface {svi}", f" description {N.VLAN_NAMES.get(int(svi[4:]), svi)}",
                  f" ip address {net_} {'255.255.255.0' if ip.endswith('/24') else '255.255.255.248' if ip.endswith('/29') else '255.255.255.252'}"]
        if svi in d.hsrp:
            vip, prio = d.hsrp[svi]
            lines += [f" standby {int(svi[4:]) % 255} ip {vip}", f" standby {int(svi[4:]) % 255} priority {prio}",
                      f" standby {int(svi[4:]) % 255} preempt"]
            if svi[4:] in ("20", "50"):
                lines += [" ip helper-address 10.21.100.61"]
        lines += ["!"]
    if N.ospf_neighbours(net, d.hostname):
        lines += ["router ospf 1", f" router-id {d.mgmt_ip}", " passive-interface default"]
        lines += [f" no passive-interface {ifc}" for _, _, ifc in N.ospf_neighbours(net, d.hostname)]
        lines += [" network 10.0.0.0 0.255.255.255 area 0", "!"]
    if not d.hsrp:
        gw = ".".join(d.mgmt_ip.split(".")[:3] + ["1"])
        lines += [f"ip default-gateway {gw}", "!"]
    lines += [f"logging host {s}" for s in svc["syslog"]]
    lines += ["!", "snmp-server group RTG-NMS v3 priv", f"snmp-server location {location(d)}",
              "snmp-server contact Network Operations", "snmp-server trap-source Vlan10"]
    for ver, host in svc["traps"]:
        lines.append(f"snmp-server host {host} version 3 priv rtg-nms" if ver == "v3"
                     else f"snmp-server host {host} version 2c rtg-legacy-traps")
    lines += ["!", "tacacs server RTG-TACACS-1", f" address ipv4 {N.TACACS[0]}", "tacacs server RTG-TACACS-2",
              f" address ipv4 {N.TACACS[1]}", "!"]
    lines += [f"ntp server {n}" for n in svc["ntp"]]
    lines += ["!", "ip http server" if d.http_server else "no ip http server", "no ip http secure-server", "!",
              "banner motd ^C Authorised use only. Activity is monitored. ^C", "!",
              "line vty 0 15", " transport input ssh", " exec-timeout 10 0", "!", "end", "", f"{d.hostname}#"]
    return "\n".join(lines) + "\n"


def extreme_backup(net, d: N.Device) -> str:
    svc = N.services(d)
    pv = port_vlans(net, d.hostname)
    lines = ["#", f"# {d.model} configuration (synthetic)", "#", "config terminal",
             "boot config flags sshd", "no boot config flags telnetd", "no web-server enable", "#",
             f'prompt "{d.hostname}"', f'snmp-server name "{d.hostname}"',
             f'snmp-server location "{location(d)}"', 'snmp-server contact "Network Operations"', "#"]
    for v, name, ports in switch_vlans(net, d):
        if v == 1:
            continue
        lines += [f'vlan create {v} name "{name}" type port-mstprstp 0']
        members = [p for p, (mode, vlans, _, _) in pv.items() if v in vlans]
        if members:
            lines += [f"vlan members add {v} {','.join(sorted(members))}"]
    lines += ["#"]
    mlts = {}
    for p, (mode, vlans, desc, lag) in pv.items():
        if lag.startswith("mlt"):
            mlts.setdefault(int(lag.split()[1]), []).append(p)
    for n, members in sorted(mlts.items()):
        lines += [f"mlt {n} enable", f"mlt {n} member {','.join(sorted(members))}", f"mlt {n} encapsulation dot1q",
                  f"interface mlt {n}", f"lacp enable key {n}", "smlt" if n > 1 else "exit", "exit"]
    for p, (mode, vlans, desc, lag) in sorted(pv.items()):
        lines += [f"interface GigabitEthernet {p}", f'name "{desc}"',
                  "encapsulation dot1q" if mode == "trunk" else f"default-vlan-id {vlans[0]}",
                  "no shutdown", "exit"]
    for svi, ip in d.svis.items():
        lines += [f"interface Vlan {svi[4:]}", f"ip address {ip}", "exit"]
    lines += ["#", f"ip name-server primary {N.DNS[0]}", f"ip name-server secondary {N.DNS[1]}",
              *[f"ntp server address {n}" for n in svc["ntp"]], "ntp"]
    lines += [f"syslog host {i} address {s}" for i, s in enumerate(svc["syslog"], start=1)]
    lines += ['snmp-server group "rtg-nms" "" auth-priv read-view root notify-view root']
    for ver, host in svc["traps"]:
        lines.append(f"snmp-server host {host} v3 authPriv rtg-nms" if ver == "v3"
                     else f"snmp-server host {host} v2c rtg-legacy-traps")
    lines += [f"radius server host {N.TACACS[0]} key **** used-by cli", "#", "isis", "spbm 1",
              f"isis sys-name {d.hostname}", "exit", "#", "end", f"{d.hostname}:1#"]
    return "\n".join(lines) + "\n"


def palo_backup(net, fw: N.Device) -> str:
    zones = sorted({z for _, z, _, a in fw.fw_interfaces if z})
    lines = ["config {", "  devices {", "    localhost.localdomain {", "      deviceconfig {", "        system {",
             f"          hostname {fw.hostname};", f"          ip-address {fw.mgmt_ip};",
             "          ntp-servers {", f"            primary-ntp-server {{ ntp-server-address {N.NTP[0]}; }}",
             f"            secondary-ntp-server {{ ntp-server-address {N.NTP[1]}; }}", "          }",
             "          dns-setting {", "            servers {", f"              primary {N.DNS[0]};",
             f"              secondary {N.DNS[1]};", "            }", "          }",
             "          authentication-profile RTG-ADMIN-AUTH;",
             "          login-banner \"Authorised use only.\";", "          service { disable-telnet yes; disable-http yes; }",
             "        }", "      }", "      network {", "        interface {", "          ethernet {"]
    for name, zone, tag, address in fw.fw_interfaces:
        lines.append(f"            {name} {{ {'ha;' if address == 'ha' else f'layer3 {{ ip {{ {address}; }} }}'} }}")
    lines += ["          }", "        }", "      }", "      vsys {", "        vsys1 {", "          zone {"]
    lines += [f"            {z} {{ network {{ layer3 [ {' '.join(n for n, zz, _, _ in fw.fw_interfaces if zz == z)} ]; }} }}"
              for z in zones]
    lines += ["          }", "        }", "      }", "    }", "  }",
              # Administrators are remote (TACACS+) accounts: no local password hash in the configuration.
              "  mgt-config {", "    users {"]
    for user, role in (("netops-admin", "superuser yes;"), ("netops-readonly", "superreader yes;")):
        lines += [f"      {user} {{", "        permissions {", "          role-based {", f"            {role}",
                  "          }", "        }", "        authentication-profile RTG-ADMIN-AUTH;", "      }"]
    lines += ["    }", "  }", "  shared {", "    server-profile {", "      tacplus {", "        RTG-TACACS {",
              "          server {"]
    lines += [f"            tacacs-{i} {{ address {a}; port 49; }}" for i, a in enumerate(N.TACACS, start=1)]
    lines += ["          }", "          protocol CHAP;", "          timeout 3;", "        }", "      }", "    }",
              "    authentication-profile {", "      RTG-ADMIN-AUTH {",
              "        method { tacplus { server-profile RTG-TACACS; } }", "        allow-list [ all ];",
              "      }", "    }", "    log-settings {",
              f"      syslog {{ RTG-SIEM {{ server {{ siem {{ server {N.LOG_COLLECTOR}; transport UDP; port 514; }} }} }} }}",
              "    }", "  }", "}", f"admin@{fw.hostname}({fw.ha_state or 'active'})>"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ topology builder inputs
def topology_inputs(net, sites):
    """Inputs for network_mapping.build_network_topology, for the given sites."""
    hosts = [d for d in net.devices.values() if d.site in sites]
    collected = [d for d in hosts if d.collected and d.kind in ("switch", "firewall")]
    rows = [r for s in sites for r in mapping_rows(net, s)]
    l2, l3 = {}, {}
    for d in collected:
        if d.kind == "switch":
            # The map's VLAN membership includes trunk ports (what the collector reads from
            # 'show interfaces trunk' / VOSS vlan members), so links carrying a VLAN are highlighted.
            pv = port_vlans(net, d.hostname)
            l2[d.hostname] = {"vlans": [{"id": str(v), "name": n,
                                         "ports": ", ".join(sorted(q for q, (_, vl, _, _) in pv.items() if v in vl))}
                                        for v, n, p in switch_vlans(net, d) if v != 1],
                              "stp_mode": "rapid-pvst" if d.vendor == "cisco" else "spbm",
                              "stp_root": [], "vtp_mode": "transparent" if d.vendor == "cisco" else "",
                              "vtp_domain": "RTG" if d.vendor == "cisco" else "", "mvrp": False,
                              "vlan_ports_exhaustive": True}
            routing = ["OSPF"] if N.ospf_neighbours(net, d.hostname) else []
            l3[d.hostname] = {"routing_protocols": routing, "route_counts": {"connected": len(d.svis)},
                              "interfaces": dict(d.svis), "bgp": {}, "ospf": {}, "adjacencies": []}
        else:
            l3[d.hostname] = {"routing_protocols": ["static"], "route_counts": {"static": 1},
                              "interfaces": {n: a for n, z, t, a in d.fw_interfaces if a != "ha"},
                              "bgp": {}, "ospf": {}, "adjacencies": []}
    return {
        "rows": rows,
        "vendor_map": {d.hostname: {"palo": "palo"}.get(d.vendor, d.vendor) for d in hosts
                       if d.kind in ("switch", "firewall", "router")},
        "platform_map": {d.hostname: d.model for d in hosts},
        "ip_map": {d.hostname: d.mgmt_ip for d in hosts if d.mgmt_ip},
        "l2": l2, "l3": l3,
        "reporting": sorted(d.hostname for d in collected),
    }


# ------------------------------------------------------------------ writing a site
def write_site(net, site: str, base: Path):
    """Writes every evidence file for one site under its managed site folder."""
    (base / "audits").mkdir(parents=True, exist_ok=True)
    (base / "discovery").mkdir(parents=True, exist_ok=True)
    (base / "raw").mkdir(parents=True, exist_ok=True)
    for vendor in ("cisco", "extreme"):
        rows = audit_rows(net, site, vendor)
        if rows:
            pd.DataFrame(rows).to_excel(base / "audits" / f"{vendor}_switch_audit_output_{site}.xlsx", index=False)
    pd.DataFrame(mapping_rows(net, site)).to_excel(base / "discovery" / f"network_mapping_output_{site}.xlsx",
                                                   index=False)
    pd.DataFrame(port_status_rows(net, site)).to_excel(base / "audits" / f"port_status_audit_output_{site}.xlsx",
                                                       index=False)
    for d in net.site_devices(site):
        if not d.collected:
            continue
        if d.kind == "switch" and d.vendor == "cisco":
            (base / "raw" / f"cisco_raw_{d.hostname}.txt").write_text(cisco_raw(net, d), encoding="utf-8")
            p = base / "backups" / "cisco" / RUN
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{d.hostname}_backup_{RUN}.txt").write_text(cisco_backup(net, d), encoding="utf-8")
        elif d.kind == "switch" and d.vendor == "extreme":
            (base / "raw" / f"extreme_l3_raw_{d.hostname}.txt").write_text(extreme_l3_raw(net, d), encoding="utf-8")
            # The as-built batch: on Fabric Engine with SPBM the engine records spanning tree as
            # not applicable (IS-IS/SPBM prevents loops), which needs this file to exist.
            (base / "raw" / f"extreme_asbuilt_raw_{d.hostname}.txt").write_text(voss_asbuilt_raw(net, d),
                                                                                 encoding="utf-8")
            p = base / "backups" / "extreme" / RUN
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{d.hostname}_extreme_backup_{RUN}.txt").write_text(extreme_backup(net, d), encoding="utf-8")
        elif d.kind == "firewall" and d.vendor == "palo":
            (base / "raw" / f"palo_raw_{d.hostname}.txt").write_text(palo_raw(net, d), encoding="utf-8")
            p = base / "backups" / "palo" / RUN
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{d.hostname}_paloalto_backup_{RUN}.txt").write_text(palo_backup(net, d), encoding="utf-8")
    (base / "discovery" / "topology_inputs.json").write_text(json.dumps(topology_inputs(net, [site]), indent=1),
                                                            encoding="utf-8")
