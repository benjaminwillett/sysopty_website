# Riverside Technology Group: synthetic network design

Riverside Technology Group (RTG) is a **fictional** medium-sized enterprise. Its network was designed from first principles for the Sysopty website demonstration. No customer network, configuration, topology, address plan or inventory was used as input. The design is code, in `build/synthetic/network.py`, and is deterministic: every build produces the identical network.

## 1. Sites

| Site | Role | Address space | Summary |
|---|---|---|---|
| RTG-HQ | Corporate headquarters | 10.10.0.0/16 | Cisco C9500 core pair, C9300 distribution pair, 8 Cisco and 8 Extreme access switches, PA-3410 HA pair, 2 carrier WAN routers, 24 APs |
| RTG-DC1 | Primary data centre | 10.21.0.0/16 | Extreme Fabric Engine core pair (vIST), 4 top-of-rack switches, PA-5410 HA pair segmenting the server, backup and DMZ networks, 2 carrier WAN routers |
| RTG-NORTH | Regional office | 10.30.0.0/16 | Cisco collapsed core pair, 6 Cisco access switches, FortiGate 100F HA pair, carrier WAN router, 14 APs |
| RTG-SOUTH | Regional office | 10.41.0.0/16 | Extreme Fabric Engine collapsed core pair, 6 Extreme access switches, PA-445 (gateway for the user VLANs), carrier WAN router, 14 APs |
| RTG-BRANCH | Small branch | 10.50.0.0/16 | 2 Cisco C9200L switches, FortiGate 40F, carrier WAN router, 6 APs |

All addresses and room names are fictional (for example "1 Riverside Way, Riverton").

## 2. Inventory (124 devices)

| Category | Count | Notes |
|---|---:|---|
| Core and distribution switches | 10 | 8 core, 2 distribution |
| Access and top-of-rack switches | 34 | Two HQ access switches are two-member stacks |
| Firewalls | 8 | 5 Palo Alto (collected); 3 Fortinet (seen as neighbours: Sysopty has no FortiGate collector) |
| WAN routers | 7 | Carrier-managed CPE, seen as neighbours on each site's WAN-edge VLAN (Sysopty has no router device kind) |
| Wireless access points | 60 | Cisco C9120AXI on Cisco switches, Extreme AP5050U on Extreme switches |
| Other devices | 5 | 2 printers, a door-access controller, a video recorder, a UPS card |

| Site | Hostname | Role | Vendor | Model | Software | Management | Collected |
|---|---|---|---|---|---|---|---|
| RTG-HQ | `c9500-hq-c01` | core | Cisco | C9500-24Y4C | 17.9.5 | 10.10.210.2 | yes |
| RTG-HQ | `c9500-hq-c02` | core | Cisco | C9500-24Y4C | 17.9.5 | 10.10.210.3 | yes |
| RTG-HQ | `c9300-hq-c03` | distribution | Cisco | C9300-24UX | 17.9.5 | 10.10.210.4 | yes |
| RTG-HQ | `c9300-hq-c04` | distribution | Cisco | C9300-24UX | 17.9.5 | 10.10.210.5 | yes |
| RTG-HQ | `c9300-hq-a01` | access (stack of 2) | Cisco | C9300-48P | 17.9.5 | 10.10.210.11 | yes |
| RTG-HQ | `c9300-hq-a02` | access (stack of 2) | Cisco | C9300-48P | 17.9.5 | 10.10.210.12 | yes |
| RTG-HQ | `c9300-hq-a03` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.13 | yes |
| RTG-HQ | `c9300-hq-a04` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.14 | yes |
| RTG-HQ | `c9300-hq-a05` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.15 | yes |
| RTG-HQ | `c9300-hq-a06` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.16 | yes |
| RTG-HQ | `c9300-hq-a07` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.17 | yes |
| RTG-HQ | `c9300-hq-a08` | access | Cisco | C9300-48P | 17.9.5 | 10.10.210.18 | yes |
| RTG-HQ | `vsp5420-hq-a09` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.19 | yes |
| RTG-HQ | `vsp5420-hq-a10` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.20 | yes |
| RTG-HQ | `vsp5420-hq-a11` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.21 | yes |
| RTG-HQ | `vsp5420-hq-a12` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.22 | yes |
| RTG-HQ | `vsp5420-hq-a13` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.23 | yes |
| RTG-HQ | `vsp5420-hq-a14` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.24 | yes |
| RTG-HQ | `vsp5420-hq-a15` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.25 | yes |
| RTG-HQ | `vsp5420-hq-a16` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.10.210.26 | yes |
| RTG-HQ | `pa3410-hq-f01` | firewall | Palo Alto Networks | PA-3410 | 11.1.4-h7 | 10.10.210.251 | yes |
| RTG-HQ | `pa3410-hq-f02` | firewall | Palo Alto Networks | PA-3410 | 11.1.4-h7 | 10.10.210.252 | yes |
| RTG-HQ | `c4451-hq-r01` | router | Cisco | ISR4451-X/K9 | 17.9.4a | — | no (seen as neighbour) |
| RTG-HQ | `c4451-hq-r02` | router | Cisco | ISR4451-X/K9 | 17.9.4a | — | no (seen as neighbour) |
| RTG-DC1 | `vsp7520-dc1-c01` | core | Extreme Networks | 7520-48Y-8C-FabricEngine | 9.3.3.0 | 10.21.10.2 | yes |
| RTG-DC1 | `vsp7520-dc1-c02` | core | Extreme Networks | 7520-48Y-8C-FabricEngine | 9.3.3.0 | 10.21.10.3 | yes |
| RTG-DC1 | `vsp5520-dc1-a01` | access | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.21.10.11 | yes |
| RTG-DC1 | `vsp5520-dc1-a02` | access | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.21.10.12 | yes |
| RTG-DC1 | `vsp5520-dc1-a03` | access | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.21.10.13 | yes |
| RTG-DC1 | `vsp5520-dc1-a04` | access | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.21.10.14 | yes |
| RTG-DC1 | `pa5410-dc1-f01` | firewall | Palo Alto Networks | PA-5410 | 11.1.4-h7 | 10.21.10.251 | yes |
| RTG-DC1 | `pa5410-dc1-f02` | firewall | Palo Alto Networks | PA-5410 | 11.1.4-h7 | 10.21.10.252 | yes |
| RTG-DC1 | `c4451-dc1-r01` | router | Cisco | ISR4451-X/K9 | 17.9.4a | — | no (seen as neighbour) |
| RTG-DC1 | `c4451-dc1-r02` | router | Cisco | ISR4451-X/K9 | 17.9.4a | — | no (seen as neighbour) |
| RTG-NORTH | `c9300-nth-c01` | core | Cisco | C9300-24UX | 17.9.5 | 10.30.10.2 | yes |
| RTG-NORTH | `c9300-nth-c02` | core | Cisco | C9300-24UX | 17.9.5 | 10.30.10.3 | yes |
| RTG-NORTH | `c9200-nth-a01` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.11 | yes |
| RTG-NORTH | `c9200-nth-a02` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.12 | yes |
| RTG-NORTH | `c9200-nth-a03` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.13 | yes |
| RTG-NORTH | `c9200-nth-a04` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.14 | yes |
| RTG-NORTH | `c9200-nth-a05` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.15 | yes |
| RTG-NORTH | `c9200-nth-a06` | access | Cisco | C9200L-48P-4X | 17.6.6a | 10.30.10.16 | yes |
| RTG-NORTH | `fg100f-nth-f01` | firewall | Fortinet | FortiGate-100F | 7.4.4 | 10.30.10.251 | no (seen as neighbour) |
| RTG-NORTH | `fg100f-nth-f02` | firewall | Fortinet | FortiGate-100F | 7.4.4 | 10.30.10.252 | no (seen as neighbour) |
| RTG-NORTH | `c1111-nth-r01` | router | Cisco | C1111-8P | 17.9.4a | — | no (seen as neighbour) |
| RTG-SOUTH | `vsp5520-sth-c01` | core | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.41.10.2 | yes |
| RTG-SOUTH | `vsp5520-sth-c02` | core | Extreme Networks | 5520-48T-FabricEngine | 9.3.3.0 | 10.41.10.3 | yes |
| RTG-SOUTH | `vsp5420-sth-a01` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.11 | yes |
| RTG-SOUTH | `vsp5420-sth-a02` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.12 | yes |
| RTG-SOUTH | `vsp5420-sth-a03` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.13 | yes |
| RTG-SOUTH | `vsp5420-sth-a04` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.14 | yes |
| RTG-SOUTH | `vsp5420-sth-a05` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.15 | yes |
| RTG-SOUTH | `vsp5420-sth-a06` | access | Extreme Networks | 5420M-48W-4YE-FabricEngine | 9.0.6.0 | 10.41.10.16 | yes |
| RTG-SOUTH | `pa445-sth-f01` | firewall | Palo Alto Networks | PA-445 | 10.2.11 | 10.41.10.251 | yes |
| RTG-SOUTH | `c1111-sth-r01` | router | Cisco | C1111-8P | 17.9.4a | — | no (seen as neighbour) |
| RTG-BRANCH | `c9200-brn-a01` | access | Cisco | C9200L-24P-4X | 16.12.10 | 10.50.210.11 | yes |
| RTG-BRANCH | `c9200-brn-a02` | access | Cisco | C9200L-24P-4X | 16.12.10 | 10.50.210.12 | yes |
| RTG-BRANCH | `fg40f-brn-f01` | firewall | Fortinet | FortiGate-40F | 7.2.9 | 10.50.210.250 | no (seen as neighbour) |
| RTG-BRANCH | `c1111-brn-r01` | router | Cisco | C1111-8P | 17.9.4a | — | no (seen as neighbour) |

| Site | Access points | Other devices |
|---|---|---|
| RTG-HQ | 24 (16× C9120AXI-Z, 8× AP5050U) | `hq-prn-01` (printer), `hq-prn-02` (printer), `hq-door-ctl01` (door controller), `hq-nvr-01` (video recorder) |
| RTG-DC1 | 2 (2× AP5050U) | `dc1-ups-01` (UPS) |
| RTG-NORTH | 14 (14× C9120AXI-Z) | — |
| RTG-SOUTH | 14 (14× AP5050U) | — |
| RTG-BRANCH | 6 (6× C9120AXI-Z) | — |

**Serial numbers** are `SYN` followed by eight hex digits, unique per device and stack member. **MAC addresses** are locally administered unicast `02:72:74:xx:xx:xx`, so none can collide with a vendor-assigned address. Both are derived from a hash of a fixed seed and the hostname.

**Software** is mostly current, with deliberate exceptions so the engine's lifecycle checks have something to report:
- IOS-XE 17.6.6a on the North access switches, and 16.12.10 at the branch;
- Fabric Engine 9.0.6.0 on the 5420 access switches;
- PAN-OS 10.2.11 at South.

**Hostnames** follow `<platform>-<site>-<role><nn>`:
- `c` is core/distribution, `a` is access, `f` is firewall and `r` is router;
- APs are named `<site>-<area>-apNN`.

This matches the engine's tiering (`-cNN` is the core layer). For that reason the HQ distribution pair is `c9300-hq-c03`/`c04`: the engine has no separate distribution role.

## 3. Topology

**HQ.**
- **Core.** Two C9500-24Y4C cores, joined by Port-channel1 (2 × 100G). They route the user VLANs with HSRP (core 1 active).
- **Building A.**
  - The C9300-24UX distribution pair is dual-homed to both cores.
  - Eight C9300-48P access switches are dual-homed to both distribution switches (the two stacks take one uplink from each member).
- **Building B.** Eight Extreme 5420M access switches are dual-homed directly to the cores at 25G.
- **Firewalls.** The PA-3410 HA pair (active/passive; HA1 and HA2 on ethernet1/7 and ethernet1/8) connects to the cores over `ae1` (Po21) and to the WAN-edge VLAN 999 on ethernet1/1.
- **WAN.** The carrier routers plug into the distribution pair's WAN-edge VLAN.

**DC1.**
- **Fabric.** Two Extreme 7520 cores form a vIST pair (MLT 1). Four 5520 top-of-rack switches are SMLT dual-homed to them.
- **Firewalls.** The PA-5410 HA pair's `ae1` is split across both cores (SMLT LACP). The firewalls are the gateway for every server network:
  - web, app and DB servers (VLANs 40–42);
  - backup (90) and infrastructure services (100);
  - DMZ (110) and the HQ interconnect (903).
- **WAN.** Untrust and the carrier routers are on WAN-edge VLAN 998.

**North.**
- The Cisco C9300 collapsed core pair routes the user VLANs with HSRP, and its six C9200L access switches are dual-homed to it.
- The FortiGate 100F HA pair provides guest and internet breakout.

**South.** The Extreme 5520 collapsed core pair (vIST) dual-homes its six 5420M access switches. The PA-445 is the gateway for the user, voice, wireless, guest and security VLANs, over `ae1` (SMLT).

**Branch.** Two C9200L-24P switches. The FortiGate 40F is the gateway; the carrier router is on the WAN-edge VLAN.

**Between sites:**

| Link | Type | Addressing |
|---|---|---|
| HQ core 1 ↔ DC1 core 1; HQ core 2 ↔ DC1 core 2 | Dark fibre, 100G | VLAN 903 (10.255.3.0/29) to the DC1 firewalls |
| HQ core 1 ↔ North core 1 | Carrier Ethernet private line (LLDP-transparent) | VLAN 901, 10.255.1.0/30, OSPF area 0 |
| HQ core 2 ↔ South core 1 | Carrier Ethernet private line (LLDP-transparent) | VLAN 902, 10.255.2.0/30, OSPF area 0 |
| Branch | IPsec VPN over the internet (FortiGate) | No layer-2 adjacency; the branch is its own island in the map |

Each site's report shows the far end of an inter-site link as an uncollected neighbour, as Sysopty would for a real site.

## 4. Addressing

- **Internal.** Every site uses `10.<site>.<vlan>.0/24` (HQ 10, DC1 20, North 30, South 40, Branch 50). The exception is the management VLAN 10 at HQ and Branch, numbered `10.10.210.0/24` and `10.50.210.0/24`.
- **Gateways.** On HSRP sites the gateway is `.1`, with the switches on `.2` and `.3`. On firewall-routed VLANs the gateway is `.1` on the firewall.
- **Management.** VLAN 10, `.2`–`.26`; firewalls use `.250`–`.252`.
- **Transit.** HQ core ↔ firewall: 10.10.250.0/29. Inter-site: 10.255.x.0/30 and /29.
- **Public addresses** use the documentation ranges only: 198.51.100.0/24 (HQ and DC1 untrust) and 203.0.113.0/24 (South).

## 5. VLANs

| VLAN | Name | HQ | DC1 | North | South | Branch |
|---|---|:-:|:-:|:-:|:-:|:-:|
| 10 | NETWORK-MGMT | ✓ | ✓ | ✓ | ✓ | ✓ |
| 20 | CORP-USERS | ✓ | | ✓ | ✓ | ✓ |
| 30 | VOICE | ✓ | | ✓ | ✓ | |
| 40 / 41 / 42 | SERVERS-WEB / APP / DB | | ✓ | | | |
| 50 | WLAN-CORP | ✓ | | ✓ | ✓ | ✓ |
| 60 | WLAN-GUEST | ✓ | | ✓ | ✓ | ✓ |
| 70 | PRINTERS | ✓ | | ✓ | | |
| 80 | SECURITY-SYSTEMS | ✓ | | | ✓ | |
| 90 | BACKUP | | ✓ | | | |
| 100 | INFRA-SERVICES | | ✓ | | | |
| 110 | DMZ | ✓ | ✓ | | | |
| 900–903 | Transit (firewall, North EPL, South EPL, DC interconnect) | ✓ | 903 | 901 | 902 | |
| 997–999 | WAN-EDGE | 999 | 998 | 997 | 997 | 997 |

## 6. Firewall architecture

| Firewall | Zones (interface) |
|---|---|
| PA-3410 HQ pair | untrust (ethernet1/1), guest (ae1.60), dmz (ae1.110), trust (ae1.900) |
| PA-5410 DC1 pair | untrust, servers-web (ae1.40), servers-app (ae1.41), servers-db (ae1.42), backup (ae1.90), infra-services (ae1.100), dmz (ae1.110), trust-wan (ae1.903) |
| PA-445 South | untrust, users (ae1.20), voice (ae1.30), wlan-corp (ae1.50), guest (ae1.60), security (ae1.80) |
| FortiGate 100F North pair; FortiGate 40F Branch | Not collected (no FortiGate collector); they appear as security devices seen by the switches |

The firewalls forward logs to 10.21.100.25. Security policies are a single rule per zone to untrust, which exists only so that the engine counts rules.

## 7. Network services

Everything lives in DC1's infrastructure-services VLAN (10.21.100.0/24):

| Service | Address(es) |
|---|---|
| NTP | .11, .12 |
| DNS | .53, .54 |
| Syslog | .21 (primary), .22 (secondary) |
| Log forwarding | .25 |
| SNMP traps | .31 (SNMPv3 authPriv); .32 (legacy v2c) |
| TACACS+ | .41, .42 |

**Per site:**
- HQ and DC1 use both syslog servers and v3 traps.
- North uses the primary syslog server.
- South uses the secondary, and sends traps to both receivers.
- The branch uses the primary and legacy v2c traps.

**Deliberate configuration drift at HQ.** Sysopty exists to find drift, so HQ has some:
- the distribution pair also sends traps to the legacy v2c receiver;
- two older access switches (`c9300-hq-a07`/`a08`) still log to a decommissioned collector (10.21.100.20);
- the Building B Extreme switches came from a different template, with the secondary syslog server and one NTP server.

The engine reports these as findings and draws each service as its own map.

**No secrets are generated.** SNMP and AAA configuration names groups and servers only. The one key field required by the Extreme RADIUS syntax is `****`.

## 8. Wireless and other devices

APs connect to access ports in VLAN 10 and carry PoE draws. Cisco APs announce `cisco C9120AXI-Z` over CDP/LLDP. Extreme APs appear in LLDP detail with the WLAN Access Point capability and Fabric Attach type 6. The five other devices are endpoints on their functional VLANs.
