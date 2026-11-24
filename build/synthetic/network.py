"""Riverside Technology Group: a fictional multi-site enterprise network, designed from scratch.

Everything here is invented for the Sysopty website demonstration: sites, hostnames,
addresses, serial numbers, MAC addresses and topology. Nothing is derived from any
customer network. The design is deterministic: build() always returns the same network,
and the only pseudo-random values (serials, MACs) come from a hash of a fixed seed and
the device name.

See SYNTHETIC_NETWORK_DESIGN.md for the design rationale.
"""
from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass, field

SEED = "riverside-technology-group-demo-2026"
ORG = "Riverside Technology Group"
COLLECTION_DATE = "2026-10-20"

# ------------------------------------------------------------------ sites and VLANs
SITES = {
    "RTG-HQ":     {"code": "hq",  "octet": 10, "mgmt_octet": 210, "role": "Corporate headquarters",
                   "address": "1 Riverside Way, Riverton", "rooms": ["Building A Level 1 Comms Room",
                                                                    "Building A Level 2 Comms Room",
                                                                    "Building A Level 3 Comms Room",
                                                                    "Building B Ground Floor Comms Room"]},
    "RTG-DC1":    {"code": "dc1", "octet": 21, "role": "Primary data centre",
                   "address": "Data Hall 2, 40 Example Parade, Riverton", "rooms": ["Data Hall 2 Row C"]},
    "RTG-NORTH":  {"code": "nth", "octet": 30, "role": "Regional office (north)",
                   "address": "12 North Street, Northbay", "rooms": ["Level 1 Comms Room", "Level 2 Comms Room"]},
    "RTG-SOUTH":  {"code": "sth", "octet": 41, "role": "Regional office (south)",
                   "address": "8 Harbour Road, Southport", "rooms": ["Ground Floor Comms Room", "Level 1 Comms Room"]},
    "RTG-BRANCH": {"code": "brn", "octet": 50, "mgmt_octet": 210, "role": "Branch office",
                   "address": "Shop 4, 2 Market Lane, Eastvale", "rooms": ["Back Office Rack"]},
}

VLAN_NAMES = {
    10: "NETWORK-MGMT", 20: "CORP-USERS", 30: "VOICE", 40: "SERVERS-WEB", 41: "SERVERS-APP",
    42: "SERVERS-DB", 50: "WLAN-CORP", 60: "WLAN-GUEST", 70: "PRINTERS", 80: "SECURITY-SYSTEMS",
    90: "BACKUP", 100: "INFRA-SERVICES", 110: "DMZ",
    900: "FW-TRANSIT", 901: "EPL-NORTH", 902: "EPL-SOUTH", 903: "DCI-TRANSIT",
    997: "WAN-EDGE", 998: "WAN-EDGE", 999: "WAN-EDGE",
}
# VLANs present at each site's switches (not every VLAN exists everywhere).
SITE_VLANS = {
    "RTG-HQ":     [10, 20, 30, 50, 60, 70, 80, 110, 900, 901, 902, 903, 999],
    "RTG-DC1":    [10, 40, 41, 42, 90, 100, 110, 903, 998],
    "RTG-NORTH":  [10, 20, 30, 50, 60, 70, 901, 997],
    "RTG-SOUTH":  [10, 20, 30, 50, 60, 80, 902, 997],
    "RTG-BRANCH": [10, 20, 50, 60, 997],
}
ACCESS_VLANS = {"RTG-HQ": [20, 30, 50, 70, 80], "RTG-NORTH": [20, 30, 50, 70], "RTG-SOUTH": [20, 30, 50, 80],
                "RTG-BRANCH": [20, 50], "RTG-DC1": [40, 41, 42, 90, 100]}

# Shared services (all in the data centre's infrastructure-services VLAN 100).
NTP = ["10.21.100.11", "10.21.100.12"]
DNS = ["10.21.100.53", "10.21.100.54"]
SYSLOG_PRIMARY, SYSLOG_SECONDARY = "10.21.100.21", "10.21.100.22"
LOG_COLLECTOR = "10.21.100.25"               # firewall log forwarding
TRAP_V3, TRAP_LEGACY = "10.21.100.31", "10.21.100.32"
TACACS = ["10.21.100.41", "10.21.100.42"]
SYSLOG_OLD = "10.21.100.20"                  # decommissioned collector still configured on two switches

# Per-site service choices (variation shows up in the service maps and findings).
SITE_SERVICES = {
    "RTG-HQ":     {"syslog": [SYSLOG_PRIMARY, SYSLOG_SECONDARY], "traps": [("v3", TRAP_V3)]},
    "RTG-DC1":    {"syslog": [SYSLOG_PRIMARY, SYSLOG_SECONDARY], "traps": [("v3", TRAP_V3)]},
    "RTG-NORTH":  {"syslog": [SYSLOG_PRIMARY], "traps": [("v3", TRAP_V3)]},
    "RTG-SOUTH":  {"syslog": [SYSLOG_SECONDARY], "traps": [("v3", TRAP_V3), ("v2c", TRAP_LEGACY)]},
    "RTG-BRANCH": {"syslog": [SYSLOG_PRIMARY], "traps": [("v2c", TRAP_LEGACY)]},
}



def services(d) -> dict:
    """Syslog, trap and NTP targets for one device: the site standard, plus the configuration
    drift a real estate accumulates (and Sysopty reports): HQ's distribution pair also sends
    traps to the legacy receiver, two older access switches still log to a decommissioned
    collector, and the Building B Extreme switches were built from a different template."""
    out = {"syslog": list(SITE_SERVICES[d.site]["syslog"]), "traps": list(SITE_SERVICES[d.site]["traps"]),
           "ntp": list(NTP)}
    if d.site == "RTG-HQ":
        if d.role == "distribution":
            out["traps"] = [("v3", TRAP_V3), ("v2c", TRAP_LEGACY)]
        elif d.hostname in ("c9300-hq-a07", "c9300-hq-a08"):
            out["syslog"] = [SYSLOG_OLD]
        elif d.platform == "vsp5420":
            out["syslog"], out["ntp"] = [SYSLOG_SECONDARY], [NTP[1]]
    return out


# ------------------------------------------------------------------ platforms
# vendor, kind, model string, software, port layout
PLATFORMS = {
    "c9500":   ("cisco", "switch", "C9500-24Y4C", "17.9.5", {"access": ("Twe", "TwentyFiveGigE", "1/0/", 1, 24),
                                                            "uplink": ("Hu", "HundredGigE", "1/0/", 25, 28)}),
    "c9300ux": ("cisco", "switch", "C9300-24UX", "17.9.5", {"access": ("Te", "TenGigabitEthernet", "1/0/", 1, 24),
                                                           "uplink": ("Te", "TenGigabitEthernet", "1/1/", 1, 8)}),
    "c9300":   ("cisco", "switch", "C9300-48P", "17.9.5", {"access": ("Gi", "GigabitEthernet", "1/0/", 1, 48),
                                                          "uplink": ("Te", "TenGigabitEthernet", "1/1/", 1, 8)}),
    "c9200":   ("cisco", "switch", "C9200L-48P-4X", "17.6.6a", {"access": ("Gi", "GigabitEthernet", "1/0/", 1, 48),
                                                              "uplink": ("Te", "TenGigabitEthernet", "1/1/", 1, 4)}),
    "c9200s":  ("cisco", "switch", "C9200L-24P-4X", "16.12.10", {"access": ("Gi", "GigabitEthernet", "1/0/", 1, 24),
                                                               "uplink": ("Te", "TenGigabitEthernet", "1/1/", 1, 4)}),
    "vsp7520": ("extreme", "switch", "7520-48Y-8C-FabricEngine", "9.3.3.0", {"access": ("", "", "1/", 1, 48),
                                                                            "uplink": ("", "", "1/", 49, 56)}),
    "vsp5520": ("extreme", "switch", "5520-48T-FabricEngine", "9.3.3.0", {"access": ("", "", "1/", 1, 48),
                                                                         "uplink": ("", "", "2/", 1, 4)}),
    "vsp5420": ("extreme", "switch", "5420M-48W-4YE-FabricEngine", "9.0.6.0", {"access": ("", "", "1/", 1, 48),
                                                                              "uplink": ("", "", "1/", 49, 52)}),
    "pa3410":  ("palo", "firewall", "PA-3410", "11.1.4-h7", {}),
    "pa5410":  ("palo", "firewall", "PA-5410", "11.1.4-h7", {}),
    "pa445":   ("palo", "firewall", "PA-445", "10.2.11", {}),
    "fg100f":  ("fortinet", "firewall", "FortiGate-100F", "7.4.4", {}),
    "fg40f":   ("fortinet", "firewall", "FortiGate-40F", "7.2.9", {}),
    "c4451":   ("cisco", "router", "ISR4451-X/K9", "17.9.4a", {}),
    "c1111":   ("cisco", "router", "C1111-8P", "17.9.4a", {}),
    "ap-cisco":   ("cisco", "ap", "C9120AXI-Z", "17.9.5", {}),
    "ap-extreme": ("extreme", "ap", "AP5050U", "10.71.3", {}),
    "endpoint":   ("other", "endpoint", "", "", {}),
}
PLATFORM_STRING = {   # how each platform describes itself over CDP/LLDP
    "c9500": "cisco C9500-24Y4C", "c9300ux": "cisco C9300-24UX", "c9300": "cisco C9300-48P",
    "c9200": "cisco C9200L-48P-4X", "c9200s": "cisco C9200L-24P-4X",
    "vsp7520": "7520-48Y-8C-FabricEngine (9.3.3.0)", "vsp5520": "5520-48T-FabricEngine (9.3.3.0)",
    "vsp5420": "5420M-48W-4YE-FabricEngine (9.0.6.0)",
    "pa3410": "PA-3410", "pa5410": "PA-5410", "pa445": "PA-445",
    "fg100f": "FortiGate-100F v7.4.4,build2662", "fg40f": "FortiGate-40F v7.2.9,build1688",
    "c4451": "cisco ISR4451-X/K9", "c1111": "cisco C1111-8P",
    "ap-cisco": "cisco C9120AXI-Z", "ap-extreme": "ExtremeWireless AP5050U",
}


HOST_PREFIX = {"c9500": "c9500", "c9300ux": "c9300", "c9300": "c9300", "c9200": "c9200", "c9200s": "c9200",
               "vsp7520": "vsp7520", "vsp5520": "vsp5520", "vsp5420": "vsp5420"}


def h(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join((SEED,) + tuple(map(str, parts))).encode()).digest()[:8], "big")


def synthetic_mac(name: str, index: int = 0) -> str:
    """Locally administered unicast MAC (02:72:74 = 'rt'): never a real vendor address."""
    n = h("mac", name, index)
    return "02:72:74:" + ":".join(f"{(n >> (8 * i)) & 0xff:02x}" for i in range(3))


def device_mac(d) -> str:
    """The MAC a device shows on the network: an endpoint's allocated MAC, else the synthetic one."""
    return d.mac or synthetic_mac(d.hostname)


def synthetic_serial(name: str, member: int = 1) -> str:
    """Clearly synthetic: SYN + 8 hex digits, unique per device and stack member."""
    return f"SYN{h('serial', name, member) & 0xffffffff:08X}"


# ------------------------------------------------------------------ objects
@dataclass
class Device:
    hostname: str
    site: str
    platform: str
    role: str                          # core | distribution | access | firewall | router | ap | endpoint
    mgmt_ip: str = ""
    members: int = 1
    room: str = ""
    collected: bool = True
    svis: dict = field(default_factory=dict)        # {"Vlan10": "10.10.210.2/24"}
    hsrp: dict = field(default_factory=dict)        # {"Vlan20": ("10.10.20.1", 110)}
    fw_interfaces: list = field(default_factory=list)  # [(name, zone, tag, address)]
    ha_peer: str = ""
    ha_state: str = ""
    endpoint_kind: str = ""
    software_override: str = ""        # a device not (yet) on its platform's standard release
    http_server: bool = False          # HTTP management left enabled (an earlier collection only)
    port_description: str = ""         # an endpoint's switch-port description, where not the default
    psu_fault: str = ""                # the power supply bay reporting a fault ("1B"), if any
    mac: str = ""                      # an endpoint's own MAC (else synthetic_mac(hostname))
    lldp_name: str = ""                # the name an endpoint announces over CDP/LLDP, where not its hostname
    announces: bool = True             # sends CDP/LLDP (workstations do not)
    _next: dict = field(default_factory=dict)

    @property
    def vendor(self):
        return PLATFORMS[self.platform][0]

    @property
    def kind(self):
        return PLATFORMS[self.platform][1]

    @property
    def model(self):
        return PLATFORMS[self.platform][2]

    @property
    def software(self):
        return self.software_override or PLATFORMS[self.platform][3]

    @property
    def platform_string(self):
        return PLATFORM_STRING.get(self.platform, self.model)

    def port(self, group: str, number: int | None = None, member: int = 1) -> tuple[str, str]:
        """(short, long) name of the next free (or the given) port in a group."""
        short, long, prefix, first, last = PLATFORMS[self.platform][4][group]
        key = (group, member)
        used = self._next.setdefault("used", set())
        if number is None:                       # next free port; never one already assigned
            number = self._next.get(key, first)
            while (group, member, number) in used:
                number += 1
            self._next[key] = number + 1
        if not first <= number <= last:
            raise ValueError(f"{self.hostname}: {group} port {number} out of range {first}-{last}")
        if (group, member, number) in used:
            raise ValueError(f"{self.hostname}: {group} port {number} (member {member}) assigned twice")
        used.add((group, member, number))
        if self.vendor == "extreme":
            name = f"{prefix}{number}"
            return name, name
        pre = prefix.replace("1/", f"{member}/", 1) if prefix.startswith("1/") else prefix
        return f"{short}{pre}{number}", f"{long}{pre}{number}"


@dataclass
class Link:
    a: str
    a_port: str          # short form on a
    b: str
    b_port: str          # short form on b
    media: str = "smf"   # copper | mmf | smf
    lag: str = ""        # bundle name on a ("Po11", "ae1", "mlt 2") when the port is a member
    purpose: str = ""
    kind: str = "lldp"   # lldp | ha (inferred HA peer, firewall to firewall)
    vlans: list = field(default_factory=list)   # trunk VLANs; [vid] for an access port
    mode: str = "trunk"  # trunk | access | routed


@dataclass
class Network:
    devices: dict = field(default_factory=dict)
    links: list = field(default_factory=list)

    def add(self, d: Device) -> Device:
        if d.hostname in self.devices:
            raise ValueError(f"duplicate hostname {d.hostname}")
        self.devices[d.hostname] = d
        return d

    def connect(self, a: Device, a_port, b: Device, b_port, **kw) -> Link:
        link = Link(a.hostname, a_port, b.hostname, b_port, **kw)
        self.links.append(link)
        return link

    def site_devices(self, site: str):
        return [d for d in self.devices.values() if d.site == site]


def _third(site: str, vlan: int) -> int:
    """An address's third octet: the VLAN, except a management VLAN a site numbers separately."""
    return SITES[site].get("mgmt_octet", vlan) if vlan == 10 else vlan


def subnet(site: str, vlan: int) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"10.{SITES[site]['octet']}.{_third(site, vlan if vlan < 256 else vlan % 256)}.0/24")


def addr(site: str, vlan: int, host: int, prefix: int = 24) -> str:
    return f"10.{SITES[site]['octet']}.{_third(site, vlan)}.{host}/{prefix}"


# ------------------------------------------------------------------ builders
def _mgmt(site, n):
    return f"10.{SITES[site]['octet']}.{_third(site, 10)}.{n}"


def _switch(net, site, platform, role, number, mgmt_host, room, members=1):
    code = SITES[site]["code"]
    # Sysopty tiers switches by name: "-cNN" is the core/distribution layer (it has no separate
    # distribution role), so the HQ distribution pair is numbered c03/c04 after the cores.
    letter = {"core": "c", "distribution": "c", "access": "a"}[role]
    name = f"{HOST_PREFIX[platform]}-{code}-{letter}{number:02d}"
    return net.add(Device(name, site, platform, role, _mgmt(site, mgmt_host), members=members, room=room))


def _ap(net, site, platform, sw: Device, index: int, area: str):
    code = SITES[site]["code"]
    name = f"{code}-{area}-ap{index:02d}"
    return net.add(Device(name, site, platform, "ap", collected=False, room=sw.room))


def _attach_ap(net, sw: Device, ap: Device, port_number=None):
    port, _ = sw.port("access", port_number)
    ap_port = "Gi0" if ap.vendor == "cisco" else "eth0"
    net.connect(sw, port, ap, ap_port, media="copper", mode="access", vlans=[10], purpose="access point")


def _uplink(net, child: Device, parent: Device, child_group="uplink", parent_group="access", media="mmf",
            vlans=None, child_port=None, parent_port=None):
    cp, _ = child.port(child_group, child_port)
    pp, _ = parent.port(parent_group, parent_port)
    return net.connect(child, cp, parent, pp, media=media, vlans=list(vlans or []), purpose="uplink")


# ------------------------------------------------------------------ the earlier (July 2026) state of HQ
# What changed at HQ between the July and October collections, as change records would show it.
# as_of_july() turns the current design back into the July state; the July collection is written
# from it and recorded by the engine's own document step (engine.record_history).
JULY_CHANGES = [
    ("software", "c9500-hq-c01", "core switch upgraded from IOS-XE 17.9.4a to 17.9.5 (15 Aug 2026)"),
    ("software", "c9500-hq-c02", "core switch upgraded from IOS-XE 17.9.4a to 17.9.5 (15 Aug 2026)"),
    ("access VLAN", "hq-door-ctl01", "door controller port moved from VLAN 20 (users) to VLAN 80 (security systems)"),
    ("configuration", "c9300-hq-c03", "HTTP management disabled (ip http server removed)"),
    ("configuration", "c9300-hq-c04", "HTTP management disabled (ip http server removed)"),
    ("description", "hq-prn-01", "printer port description updated after the device was replaced"),
    ("added", "hq-blb-ap24", "access point installed in Building B"),
    ("hardware", "c9300-hq-a03", "power supply 1B failed (Bad); the switch runs on power supply 1A"),
]

# Support coverage the customer's schedule records, where it is not the standard contract
# (evidence.schedule_rows): (status, start, end), or None for a device with no record at all.
# c9300-hq-a05's contract ended on 21 Aug 2026, 60 days before the October collection; c9300-hq-a06
# was never added to the schedule. Every other collected asset has an active contract.
SUPPORT_EXCEPTIONS = {
    "c9300-hq-a05": ("Expired", "2023-08-22", "2026-08-21"),
    "c9300-hq-a06": None,
}
# Power supply faults in the October collection: {host: bay}. A C9300-48P has two bays per
# member (A and B, PWR-C1-715WAC); with 1B failed the switch runs on 1A alone.
PSU_FAULTS = {"c9300-hq-a03": "1B"}


def as_of_july(net: Network) -> Network:
    """The July 2026 state of HQ (JULY_CHANGES undone), in place; other sites are unchanged."""
    d = net.devices
    for h in ("c9500-hq-c01", "c9500-hq-c02"):
        d[h].software_override = "17.9.4a"
    for h in ("c9300-hq-c03", "c9300-hq-c04"):
        d[h].http_server = True
    d["hq-prn-01"].port_description = "MFP Level 2 copy room hq-prn-01"
    for l in net.links:
        if "hq-door-ctl01" in (l.a, l.b):
            l.vlans = [20]
    d["hq-door-ctl01"].mgmt_ip = addr("RTG-HQ", 20, DHCP_LAST).split("/")[0]   # re-addressed when moved
    ap = "hq-blb-ap24"
    net.links = [l for l in net.links if ap not in (l.a, l.b)]
    del d[ap]
    for h in PSU_FAULTS:                    # both supplies were healthy in July
        d[h].psu_fault = ""
    return net


# ------------------------------------------------------------------ the access-layer endpoint population
# Who is patched into the access switches, within the address plan: each site has one /24 user VLAN
# (VLAN 20), so wired workstations are limited to its DHCP scope (.21-.250); wireless users are on
# VLAN 50. Building A and the Cisco offices have a desk phone per desk with the PC behind it (VLAN 20
# data, VLAN 30 voice); Building B and the Fabric Engine south office use softphones (PC only).
# Printers sit in VLAN 70 where the site has it, else in VLAN 20; cameras, door and building
# controllers in VLAN 80 where the site has it. Workstations do not announce CDP/LLDP; phones,
# printers, cameras and controllers do. DC1 (servers on the top-of-rack switches) is not populated.
# site: {access switch: (desks, phones at the desks, printers, cameras, door controllers, BMS controllers)}
ENDPOINT_PLAN = {
    "RTG-HQ": {
        **{f"c9300-hq-a0{i}": (26 if i in (1, 2) else 15, True, 0 if i == 3 else 1, 2,
                               1 if i in (1, 7) else 0, 1 if i in (2, 8) else 0) for i in range(1, 9)},
        **{f"vsp5420-hq-a{i:02d}": (10, False, 0 if i == 10 else 1, 1,
                                    1 if i in (9, 12, 15) else 0, 1 if i in (11, 16) else 0) for i in range(9, 17)},
    },
    "RTG-NORTH": {f"c9200-nth-a0{i}": (12, True, 1 if i in (1, 3, 5) else 0, 0, 0, 0) for i in range(1, 7)},
    "RTG-SOUTH": {f"vsp5420-sth-a0{i}": (10, False, 1 if i in (1, 3, 5) else 0, 1, 1 if i == 1 else 0, 0)
                  for i in range(1, 7)},
    "RTG-BRANCH": {f"c9200-brn-a0{i}": (7, True, 1 if i == 1 else 0, 0, 0, 0) for i in (1, 2)},
}
ENDPOINT_VLAN = {"workstation": 20, "IP phone": 30, "printer": 70, "camera": 80, "door controller": 80,
                 "BMS controller": 80, "video recorder": 80}
DHCP_FIRST, DHCP_LAST = 21, 250                      # each VLAN's address pool for endpoints


def _floor(site, sw: Device) -> str:
    """The desk-numbering area of a switch's comms room: A1/A2/A3 (Building A levels), B0, L1, G, BO."""
    room = sw.room
    if "Building A Level" in room:
        return "A" + room.split("Level ")[1][0]
    if "Building B" in room:
        return "B0"
    if room.startswith("Level"):
        return "L" + room.split(" ")[1]
    return "G" if room.startswith("Ground") else "BO"


def endpoint_vlan(site, kind) -> int:
    v = ENDPOINT_VLAN[kind]
    return v if v in SITE_VLANS[site] else 20


def populate_endpoints(net: Network):
    """The endpoints of ENDPOINT_PLAN, patched to free access ports in order (never an uplink),
    a stack's desks split across its members. Unique locally administered MACs (02:72:75:..)
    and addresses from each VLAN's pool, after those the earlier design already holds."""
    used_macs = {synthetic_mac(h) for h in net.devices}
    def mac(name):
        i = 0
        while True:
            n = h("endpoint-mac", name, i)
            m = "02:72:75:" + ":".join(f"{(n >> (8 * k)) & 0xff:02x}" for k in range(3))
            if m not in used_macs:
                used_macs.add(m)
                return m
            i += 1
    pools = {}
    def ip(site, kind):
        v = endpoint_vlan(site, kind)
        n = pools.setdefault((site, v), DHCP_FIRST)
        if n > DHCP_LAST:
            raise ValueError(f"{site} VLAN {v}: address pool exhausted")
        pools[(site, v)] = n + 1
        return addr(site, v, n).split("/")[0]
    # the earlier design's endpoints keep their names; they get addresses from the same pools
    for d in sorted(net.devices.values(), key=lambda x: x.hostname):
        if d.role == "endpoint" and d.endpoint_kind in ENDPOINT_VLAN and not d.mgmt_ip:
            vlan = next(l.vlans[0] for _, _, _, l in neighbours(net, d.hostname))
            pools.setdefault((d.site, vlan), DHCP_FIRST)
            d.mgmt_ip = addr(d.site, vlan, pools[(d.site, vlan)]).split("/")[0]
            pools[(d.site, vlan)] += 1
    counters = {}
    def name(site, prefix, width=2):
        code = SITES[site]["code"]
        existing = sum(1 for x in net.devices if x.startswith(f"{code}-{prefix}"))
        counters[(site, prefix)] = counters.get((site, prefix), existing) + 1
        return f"{code}-{prefix}{counters[(site, prefix)]:0{width}d}"
    desks = {}
    def attach(sw, member, dev, kind, desc):
        port, _ = sw.port("access", member=member)
        dev.port_description = desc
        net.connect(sw, port, dev, "Port 1" if kind == "IP phone" else "eth0", media="copper", mode="access",
                    vlans=[endpoint_vlan(sw.site, "workstation" if kind == "IP phone" else kind)],
                    purpose=kind)
    for site, plan in ENDPOINT_PLAN.items():
        for swname, (n_desks, phones, printers, cameras, doors, bms) in plan.items():
            sw = net.devices[swname]
            floor = _floor(site, sw)
            for k in range(n_desks):
                member = 1 + k % sw.members
                desks[floor] = desks.get(floor, 0) + 1
                desk = f"Desk {floor}-{desks[floor]:03d}"
                ws = net.add(Device(name(site, "ws-", 4), site, "endpoint", "endpoint", ip(site, "workstation"),
                                    collected=False, room=sw.room, endpoint_kind="workstation", announces=False))
                ws.mac = mac(ws.hostname)
                if phones:
                    ph = net.add(Device(name(site, "ph-", 4), site, "endpoint", "endpoint", ip(site, "IP phone"),
                                        collected=False, room=sw.room, endpoint_kind="IP phone"))
                    ph.mac = mac(ph.hostname)
                    ph.lldp_name = "SEP" + ph.mac.replace(":", "").upper()
                    attach(sw, member, ph, "IP phone", desk)
                    net.connect(ph, "PC Port", ws, "eth0", media="copper", mode="access",
                                vlans=[endpoint_vlan(site, "workstation")], purpose="desk PC")
                else:
                    attach(sw, member, ws, "workstation", desk)
            for kind, count, prefix in (("printer", printers, "prn-"), ("camera", cameras, "cam-"),
                                        ("door controller", doors, "door-ctl"), ("BMS controller", bms, "bms-")):
                if count and endpoint_vlan(site, kind) != ENDPOINT_VLAN[kind] and kind != "printer":
                    continue                      # no security VLAN at this site
                for _ in range(count):
                    dev = net.add(Device(name(site, prefix), site, "endpoint", "endpoint", ip(site, kind),
                                         collected=False, room=sw.room, endpoint_kind=kind))
                    dev.mac = mac(dev.hostname)
                    attach(sw, 1, dev, kind, f"{kind} {dev.hostname}")


def build() -> Network:
    net = Network()
    build_hq(net)
    build_dc1(net)
    build_north(net)
    build_south(net)
    build_branch(net)
    interconnect(net)
    populate_endpoints(net)
    for h, bay in PSU_FAULTS.items():
        net.devices[h].psu_fault = bay
    return net


def _svis(dev: Device, site: str, vlans, host: int, vip_host=1, priority=None):
    for v in vlans:
        dev.svis[f"Vlan{v}"] = addr(site, v, host)
        if priority is not None:
            dev.hsrp[f"Vlan{v}"] = (addr(site, v, vip_host).split("/")[0], priority)


def build_hq(net: Network):
    s = "RTG-HQ"
    rooms = SITES[s]["rooms"]
    c = [_switch(net, s, "c9500", "core", i, 1 + i, rooms[0]) for i in (1, 2)]
    d = [_switch(net, s, "c9300ux", "distribution", i + 2, 3 + i, rooms[0]) for i in (1, 2)]
    cisco_access = []
    for i in range(1, 9):
        members = 2 if i in (1, 2) else 1
        cisco_access.append(_switch(net, s, "c9300", "access", i, 10 + i, rooms[(i - 1) // 3 % 3], members))
    ext_access = [_switch(net, s, "vsp5420", "access", i, 10 + i, rooms[3]) for i in range(9, 17)]

    # Core pair: routed user VLANs with HSRP; core 1 active.
    user_vlans = [10, 20, 30, 50, 70, 80]
    _svis(c[0], s, user_vlans, 2, priority=110)
    _svis(c[1], s, user_vlans, 3, priority=100)
    c[0].svis["Vlan900"], c[1].svis["Vlan900"] = "10.10.250.2/29", "10.10.250.3/29"
    c[0].hsrp["Vlan900"], c[1].hsrp["Vlan900"] = ("10.10.250.1", 110), ("10.10.250.1", 100)
    c[0].svis["Vlan901"] = "10.255.1.1/30"           # carrier EPL to the north office
    c[1].svis["Vlan902"] = "10.255.2.1/30"           # carrier EPL to the south office
    c[0].svis["Vlan903"], c[1].svis["Vlan903"] = "10.255.3.2/29", "10.255.3.3/29"   # DC interconnect
    for sw in d + cisco_access + ext_access:
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    hq_trunk = [10, 20, 30, 50, 60, 70, 80]

    # core-core: two 100G links in Port-channel1
    for n in (27, 28):
        a, _ = c[0].port("uplink", n)
        b, _ = c[1].port("uplink", n)
        net.connect(c[0], a, c[1], b, lag="Po1", media="mmf", vlans=SITE_VLANS[s], purpose="core interconnect")
    # distribution to both cores
    for sw in d:
        for core in c:
            _uplink(net, sw, core, vlans=hq_trunk + [999])
    # Cisco access to both distribution switches (stacks: one uplink from each member)
    for sw in cisco_access:
        for m, dist in enumerate(d, start=1):
            member = m if sw.members > 1 else 1
            cp, _ = sw.port("uplink", None if member == 1 else 1, member=member)
            pp, _ = dist.port("access")
            net.connect(sw, cp, dist, pp, media="mmf", vlans=hq_trunk, purpose="uplink")
    # Extreme access straight to the cores (25G)
    for sw in ext_access:
        for core in c:
            _uplink(net, sw, core, vlans=hq_trunk)

    # Firewalls: PA-3410 HA pair. ae1 to its core; untrust to the WAN-edge VLAN on the distribution pair.
    fws = []
    for i, core in enumerate(c, start=1):
        fw = net.add(Device(f"pa3410-hq-f0{i}", s, "pa3410", "firewall", _mgmt(s, 250 + i), room=rooms[0]))
        fw.ha_state = "active" if i == 1 else "passive"
        for n, eth in ((21, "ethernet1/5"), (22, "ethernet1/6")):
            cp, _ = core.port("access", n)
            net.connect(core, cp, fw, eth, lag="Po21", media="mmf", vlans=[60, 110, 900], purpose="firewall")
        dp, _ = d[i - 1].port("access", 24)
        net.connect(d[i - 1], dp, fw, "ethernet1/1", media="copper", mode="access", vlans=[999], purpose="untrust")
        fws.append(fw)
    fws[0].ha_peer, fws[1].ha_peer = fws[1].hostname, fws[0].hostname
    for fw in fws:
        fw.fw_interfaces = [
            ("ethernet1/1", "untrust", 0, "198.51.100.2/29" if fw is fws[0] else "198.51.100.2/29"),
            ("ae1.60", "guest", 60, "10.10.60.1/24"),
            ("ae1.110", "dmz", 110, "10.10.110.1/24"),
            ("ae1.900", "trust", 900, "10.10.250.4/29"),
            ("ethernet1/7", "", 0, "ha"), ("ethernet1/8", "", 0, "ha"),
        ]
    net.connect(fws[0], "ethernet1/7", fws[1], "ethernet1/7", kind="ha", media="copper", purpose="HA1 link")
    net.connect(fws[0], "ethernet1/8", fws[1], "ethernet1/8", kind="ha", media="copper", purpose="HA2 link")

    # Carrier-managed WAN routers (not collected) on the WAN-edge VLAN
    for i, dist in enumerate(d, start=1):
        r = net.add(Device(f"c4451-hq-r0{i}", s, "c4451", "router", collected=False, room=rooms[0]))
        dp, _ = dist.port("access", 23)
        net.connect(dist, dp, r, "Gi0/0/1", media="copper", mode="access", vlans=[999], purpose="carrier CPE")

    # Wireless: 2 Cisco APs per Cisco access switch, 1 Extreme AP per Extreme access switch (24)
    n = 1
    for sw in cisco_access:
        for _ in range(2):
            _attach_ap(net, sw, _ap(net, s, "ap-cisco", sw, n, "bla"), None)
            n += 1
    for sw in ext_access:
        _attach_ap(net, sw, _ap(net, s, "ap-extreme", sw, n, "blb"), 40)
        n += 1
    # Other devices: two printers, a door-access controller and a video recorder
    for name, sw, port, vlan, kind in (("hq-prn-01", cisco_access[2], 40, 70, "printer"),
                                       ("hq-prn-02", ext_access[1], 41, 70, "printer"),
                                       ("hq-door-ctl01", cisco_access[3], 45, 80, "door controller"),
                                       ("hq-nvr-01", d[0], 20, 80, "video recorder")):
        e = net.add(Device(name, s, "endpoint", "endpoint", collected=False, room=sw.room, endpoint_kind=kind))
        sp, _ = sw.port("access", port)
        net.connect(sw, sp, e, "eth0", media="copper", mode="access", vlans=[vlan], purpose=kind)


def build_dc1(net: Network):
    s = "RTG-DC1"
    room = SITES[s]["rooms"][0]
    c = [_switch(net, s, "vsp7520", "core", i, 1 + i, room) for i in (1, 2)]
    tor = [_switch(net, s, "vsp5520", "access", i, 10 + i, room) for i in range(1, 5)]
    for i, sw in enumerate(c):
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    for sw in tor:
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    dc_vlans = [10, 40, 41, 42, 90, 100, 110]
    # vIST between the cores (MLT 1)
    for n in (55, 56):
        a, _ = c[0].port("uplink", n)
        b, _ = c[1].port("uplink", n)
        net.connect(c[0], a, c[1], b, lag="mlt 1", media="mmf", vlans=SITE_VLANS[s], purpose="vIST")
    for sw in tor:
        for core in c:
            _uplink(net, sw, core, vlans=dc_vlans)
    # PA-5410 pair: ae1 split across both cores (SMLT), untrust on the DC WAN-edge VLAN
    fws = []
    for i in (1, 2):
        fw = net.add(Device(f"pa5410-dc1-f0{i}", s, "pa5410", "firewall", f"10.21.10.{250 + i}", room=room))
        fw.ha_state = "active" if i == 1 else "passive"
        for core, eth in zip(c, ("ethernet1/17", "ethernet1/18")):
            cp, _ = core.port("access", 40 + i)
            net.connect(core, cp, fw, eth, lag="mlt 2" if i == 1 else "mlt 3", media="mmf",
                        vlans=[40, 41, 42, 90, 100, 110, 903], purpose="firewall")
        cp, _ = c[i - 1].port("access", 45)
        net.connect(c[i - 1], cp, fw, "ethernet1/1", media="copper", mode="access", vlans=[998], purpose="untrust")
        fws.append(fw)
    fws[0].ha_peer, fws[1].ha_peer = fws[1].hostname, fws[0].hostname
    for fw in fws:
        fw.fw_interfaces = [
            ("ethernet1/1", "untrust", 0, "198.51.100.18/29"),
            ("ae1.40", "servers-web", 40, "10.21.40.1/24"),
            ("ae1.41", "servers-app", 41, "10.21.41.1/24"),
            ("ae1.42", "servers-db", 42, "10.21.42.1/24"),
            ("ae1.90", "backup", 90, "10.21.90.1/24"),
            ("ae1.100", "infra-services", 100, "10.21.100.1/24"),
            ("ae1.110", "dmz", 110, "10.21.110.1/24"),
            ("ae1.903", "trust-wan", 903, "10.255.3.4/29"),
            ("ethernet1/19", "", 0, "ha"), ("ethernet1/20", "", 0, "ha"),
        ]
    net.connect(fws[0], "ethernet1/19", fws[1], "ethernet1/19", kind="ha", media="copper", purpose="HA1 link")
    net.connect(fws[0], "ethernet1/20", fws[1], "ethernet1/20", kind="ha", media="copper", purpose="HA2 link")
    for i, core in enumerate(c, start=1):
        r = net.add(Device(f"c4451-dc1-r0{i}", s, "c4451", "router", collected=False, room=room))
        cp, _ = core.port("access", 46)
        net.connect(core, cp, r, "Gi0/0/1", media="copper", mode="access", vlans=[998], purpose="carrier CPE")
    for n, sw in enumerate(tor[:2], start=1):
        _attach_ap(net, sw, _ap(net, s, "ap-extreme", sw, n, "hall"), 48)
    ups = net.add(Device("dc1-ups-01", s, "endpoint", "endpoint", collected=False, room=room, endpoint_kind="UPS"))
    sp, _ = tor[2].port("access", 47)
    net.connect(tor[2], sp, ups, "eth0", media="copper", mode="access", vlans=[10], purpose="UPS")


def build_north(net: Network):
    s = "RTG-NORTH"
    rooms = SITES[s]["rooms"]
    c = [_switch(net, s, "c9300ux", "core", i, 1 + i, rooms[0]) for i in (1, 2)]
    acc = [_switch(net, s, "c9200", "access", i, 10 + i, rooms[(i - 1) // 3]) for i in range(1, 7)]
    north_vlans = [10, 20, 30, 50, 70]
    _svis(c[0], s, north_vlans, 2, priority=110)
    _svis(c[1], s, north_vlans, 3, priority=100)
    c[0].svis["Vlan901"] = "10.255.1.2/30"
    for sw in acc:
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    for n in (1, 2):
        a, _ = c[0].port("uplink", n)
        b, _ = c[1].port("uplink", n)
        net.connect(c[0], a, c[1], b, lag="Po1", media="copper", vlans=SITE_VLANS[s], purpose="core interconnect")
    for sw in acc:
        for core in c:
            _uplink(net, sw, core, vlans=north_vlans + [60])
    # FortiGate 100F HA pair (not collected: Sysopty has no FortiGate collector) and the carrier CPE
    for i, core in enumerate(c, start=1):
        fw = net.add(Device(f"fg100f-nth-f0{i}", s, "fg100f", "firewall", f"10.30.10.{250 + i}",
                            collected=False, room=rooms[0]))
        cp, _ = core.port("access", 20)
        net.connect(core, cp, fw, "x1", media="mmf", vlans=[60, 997], purpose="firewall")
        cp, _ = core.port("access", 21)
        net.connect(core, cp, fw, "wan1", media="copper", mode="access", vlans=[997], purpose="untrust")
    r = net.add(Device("c1111-nth-r01", s, "c1111", "router", collected=False, room=rooms[0]))
    cp, _ = c[0].port("access", 22)
    net.connect(c[0], cp, r, "Gi0/0/1", media="copper", mode="access", vlans=[997], purpose="carrier CPE")
    n = 1
    for i, sw in enumerate(acc):
        for _ in range(3 if i < 2 else 2):
            _attach_ap(net, sw, _ap(net, s, "ap-cisco", sw, n, "l1" if i < 3 else "l2"), None)
            n += 1


def build_south(net: Network):
    s = "RTG-SOUTH"
    rooms = SITES[s]["rooms"]
    c = [_switch(net, s, "vsp5520", "core", i, 1 + i, rooms[0]) for i in (1, 2)]
    acc = [_switch(net, s, "vsp5420", "access", i, 10 + i, rooms[(i - 1) // 3]) for i in range(1, 7)]
    for sw in c + acc:
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    c[0].svis["Vlan902"] = "10.255.2.2/30"
    for n in (3, 4):
        a, _ = c[0].port("uplink", n)
        b, _ = c[1].port("uplink", n)
        net.connect(c[0], a, c[1], b, lag="mlt 1", media="mmf", vlans=SITE_VLANS[s], purpose="vIST")
    south_vlans = [10, 20, 30, 50, 60, 80]
    for sw in acc:
        for core in c:
            _uplink(net, sw, core, vlans=south_vlans)
    fw = net.add(Device("pa445-sth-f01", s, "pa445", "firewall", "10.41.10.251", room=rooms[0]))
    for core, eth in zip(c, ("ethernet1/3", "ethernet1/4")):
        cp, _ = core.port("access", 41)
        net.connect(core, cp, fw, eth, lag="mlt 2", media="copper", vlans=[20, 30, 50, 60, 80], purpose="firewall")
    cp, _ = c[0].port("access", 45)
    net.connect(c[0], cp, fw, "ethernet1/1", media="copper", mode="access", vlans=[997], purpose="untrust")
    # The south office firewall is the gateway for the user VLANs.
    fw.fw_interfaces = [
        ("ethernet1/1", "untrust", 0, "203.0.113.10/29"),
        ("ae1.20", "users", 20, "10.41.20.1/24"),
        ("ae1.30", "voice", 30, "10.41.30.1/24"),
        ("ae1.50", "wlan-corp", 50, "10.41.50.1/24"),
        ("ae1.60", "guest", 60, "10.41.60.1/24"),
        ("ae1.80", "security", 80, "10.41.80.1/24"),
    ]
    r = net.add(Device("c1111-sth-r01", s, "c1111", "router", collected=False, room=rooms[0]))
    cp, _ = c[1].port("access", 45)
    net.connect(c[1], cp, r, "Gi0/0/1", media="copper", mode="access", vlans=[997], purpose="carrier CPE")
    n = 1
    for i, sw in enumerate(acc):
        for _ in range(3 if i < 2 else 2):
            _attach_ap(net, sw, _ap(net, s, "ap-extreme", sw, n, "gf" if i < 3 else "l1"), None)
            n += 1


def build_branch(net: Network):
    s = "RTG-BRANCH"
    room = SITES[s]["rooms"][0]
    acc = [_switch(net, s, "c9200s", "access", i, 10 + i, room) for i in (1, 2)]
    for sw in acc:
        sw.svis["Vlan10"] = f"{sw.mgmt_ip}/24"
    a, _ = acc[0].port("uplink", 1)
    b, _ = acc[1].port("uplink", 1)
    net.connect(acc[0], a, acc[1], b, media="copper", vlans=SITE_VLANS[s], purpose="stack interconnect")
    fw = net.add(Device("fg40f-brn-f01", s, "fg40f", "firewall", _mgmt(s, 250), collected=False, room=room))
    p, _ = acc[0].port("access", 24)
    net.connect(acc[0], p, fw, "lan1", media="copper", vlans=[10, 20, 50, 60], purpose="firewall")
    p, _ = acc[0].port("access", 23)
    net.connect(acc[0], p, fw, "wan", media="copper", mode="access", vlans=[997], purpose="untrust")
    r = net.add(Device("c1111-brn-r01", s, "c1111", "router", collected=False, room=room))
    p, _ = acc[0].port("access", 22)
    net.connect(acc[0], p, r, "Gi0/0/1", media="copper", mode="access", vlans=[997], purpose="carrier CPE")
    n = 1
    for sw in acc:
        for _ in range(3):
            _attach_ap(net, sw, _ap(net, s, "ap-cisco", sw, n, "shop"), None)
            n += 1


def interconnect(net: Network):
    """Links between sites: DC interconnect (dark fibre) and carrier Ethernet private lines
    (LLDP-transparent) to the regional offices. The branch uses an IPsec VPN (no L2 link)."""
    d = net.devices
    hq1, hq2 = d["c9500-hq-c01"], d["c9500-hq-c02"]
    for hq, dc in ((hq1, d["vsp7520-dc1-c01"]), (hq2, d["vsp7520-dc1-c02"])):
        a, _ = hq.port("uplink", 25)
        b, _ = dc.port("uplink", 49)
        net.connect(hq, a, dc, b, media="smf", vlans=[10, 903], purpose="DC interconnect")
    a, _ = hq1.port("access", 13)
    b, _ = d["c9300-nth-c01"].port("uplink", 4)
    net.connect(hq1, a, d["c9300-nth-c01"], b, media="smf", vlans=[901], purpose="carrier EPL")
    a, _ = hq2.port("access", 13)
    b, _ = d["vsp5520-sth-c01"].port("uplink", 1)
    net.connect(hq2, a, d["vsp5520-sth-c01"], b, media="smf", vlans=[902], purpose="carrier EPL")


# ------------------------------------------------------------------ carrier services
# The carrier's service export (what the customer supplies; not discovered). Fictional carrier
# and circuit identifiers. "ends" are the devices the service is handed off to: the carrier CPE
# for internet services, the two switches a private line or dark fibre joins. Each must be a
# link of the matching purpose in the model (validate.validate_network checks it).
CARRIER = "Example Carrier Networks (fictional)"
WAN_SERVICES = [
    # site, service, type, circuit, bandwidth, ends
    ("RTG-HQ", "Business Internet 1000 Mbps (primary)", "Internet", "SYN-INT-HQ-0001", "1000 Mbps", ("c4451-hq-r01",)),
    ("RTG-HQ", "Business Internet 1000 Mbps (secondary)", "Internet", "SYN-INT-HQ-0002", "1000 Mbps", ("c4451-hq-r02",)),
    ("RTG-HQ", "IP address block 198.51.100.0/29", "Addressing", "SYN-IPB-HQ-0001", "-", ()),
    ("RTG-HQ", "Ethernet Private Line HQ - North (VLAN 901)", "EPL", "SYN-EPL-0901", "1000 Mbps",
     ("c9500-hq-c01", "c9300-nth-c01")),
    ("RTG-HQ", "Ethernet Private Line HQ - South (VLAN 902)", "EPL", "SYN-EPL-0902", "1000 Mbps",
     ("c9500-hq-c02", "vsp5520-sth-c01")),
    ("RTG-HQ", "Dark fibre HQ - DC1 (path A)", "Dark fibre", "SYN-DF-0001", "100 Gbps", ("c9500-hq-c01", "vsp7520-dc1-c01")),
    ("RTG-HQ", "Dark fibre HQ - DC1 (path B)", "Dark fibre", "SYN-DF-0002", "100 Gbps", ("c9500-hq-c02", "vsp7520-dc1-c02")),
    ("RTG-DC1", "Business Internet 1000 Mbps (primary)", "Internet", "SYN-INT-DC1-0001", "1000 Mbps", ("c4451-dc1-r01",)),
    ("RTG-DC1", "Business Internet 1000 Mbps (secondary)", "Internet", "SYN-INT-DC1-0002", "1000 Mbps", ("c4451-dc1-r02",)),
    ("RTG-DC1", "IP address block 198.51.100.16/29", "Addressing", "SYN-IPB-DC1-0001", "-", ()),
    ("RTG-DC1", "Dark fibre HQ - DC1 (path A)", "Dark fibre", "SYN-DF-0001", "100 Gbps", ("c9500-hq-c01", "vsp7520-dc1-c01")),
    ("RTG-DC1", "Dark fibre HQ - DC1 (path B)", "Dark fibre", "SYN-DF-0002", "100 Gbps", ("c9500-hq-c02", "vsp7520-dc1-c02")),
    ("RTG-NORTH", "Business Internet 200 Mbps", "Internet", "SYN-INT-NTH-0001", "200 Mbps", ("c1111-nth-r01",)),
    ("RTG-NORTH", "Ethernet Private Line HQ - North (VLAN 901)", "EPL", "SYN-EPL-0901", "1000 Mbps",
     ("c9500-hq-c01", "c9300-nth-c01")),
    ("RTG-SOUTH", "Business Internet 200 Mbps", "Internet", "SYN-INT-STH-0001", "200 Mbps", ("c1111-sth-r01",)),
    ("RTG-SOUTH", "IP address block 203.0.113.8/29", "Addressing", "SYN-IPB-STH-0001", "-", ()),
    ("RTG-SOUTH", "Ethernet Private Line HQ - South (VLAN 902)", "EPL", "SYN-EPL-0902", "1000 Mbps",
     ("c9500-hq-c02", "vsp5520-sth-c01")),
    ("RTG-BRANCH", "Business Internet 100 Mbps", "Internet", "SYN-INT-BRN-0001", "100 Mbps", ("c1111-brn-r01",)),
]
WAN_PURPOSE = {"Internet": "carrier CPE", "EPL": "carrier EPL", "Dark fibre": "DC interconnect"}


# ------------------------------------------------------------------ queries used by the writers
def neighbours(net: Network, host: str):
    """[(local_port, neighbour, neighbour_port, link)] for host."""
    out = []
    for l in net.links:
        if l.a == host:
            out.append((l.a_port, l.b, l.b_port, l))
        elif l.b == host:
            out.append((l.b_port, l.a, l.a_port, l))
    return out


def ospf_neighbours(net: Network, host: str):
    """OSPF adjacencies on the routed transit VLANs: [(neighbour host, neighbour ip, local interface)]."""
    pairs = {"Vlan901": ("c9500-hq-c01", "c9300-nth-c01"), "Vlan902": ("c9500-hq-c02", "vsp5520-sth-c01")}
    out = []
    for ifc, (x, y) in pairs.items():
        if host in (x, y):
            other = y if host == x else x
            out.append((other, net.devices[other].svis[ifc].split("/")[0], ifc))
    if host in ("c9500-hq-c01", "c9500-hq-c02"):
        other = "c9500-hq-c02" if host == "c9500-hq-c01" else "c9500-hq-c01"
        out.append((other, net.devices[other].svis["Vlan900"].split("/")[0], "Vlan900"))
    return out


def router_id(net: Network, host: str) -> str:
    return net.devices[host].mgmt_ip
