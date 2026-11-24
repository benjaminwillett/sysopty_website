# Synthetic evidence generator

The website's demonstration assets are produced by the real Sysopty engine from **synthetic evidence**: files in exactly the formats Sysopty's collectors write, generated from the fictional Riverside Technology Group design (SYNTHETIC_NETWORK_DESIGN.md). The engine is not modified. It reads the files as it would read any saved collection.

## Components

| File | Purpose |
|---|---|
| `build/synthetic/network.py` | The network design as code. `build()` returns sites, devices, links, VLANs, addresses and services. |
| `build/synthetic/evidence.py` | Writes the design as Sysopty evidence: audit workbooks, mapping workbook, raw command output, backups and topology-builder inputs. |
| `build/synthetic/engine.py` | Copies the product's code into an isolated engine folder (allowlist), registers the synthetic customer and sites, builds maps and runs reports. |
| `build/synthetic/validate.py` | Consistency checks of the design and the written evidence. |
| `build/make_synthetic_assets.py` | The pipeline: engine → evidence → reports → VLAN maps → demo → images → validate → leak check. |
| `build/site_images.py` | Extracts figures from the reports and writes the WebP images and gallery markup. |
| `tests/test_synthetic.py` | 20 tests: determinism, inventory, consistency, injected faults (each validator check must fire), formats, no credentials, documentation-range addresses, no customer words. |

## Determinism and the seed

- **No random number generator is used.** All variation is explicit in the design.
- **The few values that need uniqueness** (serial numbers and MAC addresses) are `SHA-256(SEED | kind | hostname | index)`, with `SEED = "riverside-technology-group-demo-2026"` (in `network.py`).
- **Same input, same output.** The same code and seed always produce identical evidence (`test_build_is_deterministic`).
- **Engine output is not byte-identical.** The engine stamps report dates and run identifiers, so the rendered reports differ between runs.
- **Changing the network** means changing `network.py`: add a device, link or VLAN in the site builders, then re-run validation.

## Evidence format (per site)

This is the managed layout `<artifact root>/Riverside Technology Group/<site>/`, created by the engine itself so it carries the engine's identity marker.

| Path | Content | Read by |
|---|---|---|
| `audits/cisco_switch_audit_output_<site>.xlsx`, `extreme_…` | One row per switch or stack member: model, serial, software, NTP/DNS/syslog, VLANs, SVI addresses, STP/VTP, location, clock | hardware, VLAN and services sections |
| `discovery/network_mapping_output_<site>.xlsx` | One row per CDP/LLDP adjacency seen by a collected device. Both ends of switch-to-switch links (so the engine marks them Confirmed); firewall HA links as `inferred_ha_peer` | topology, architecture, AP and endpoint sections |
| `discovery/network_topology_<site>.html` | The interactive map, **built by the engine's own** `build_network_topology` / `generate_topology_outputs` from the design's L2/L3 maps | offline L3 (subnets, routing), VLAN map snapshots |
| `audits/port_status_audit_output_<site>.xlsx` | Every port of every collected switch (each stack member): `connected`/`notconnect` (Cisco), `upup`/`updown` (VOSS), VLAN, speed, media type. Up exactly where the design has a link; empty SFP cages are `Not Present`/`GbicNone` | port capacity, optics, unused ports left enabled |
| `raw/cisco_raw_<host>.txt` | `show version \| include uptime`, `show environment all` (fans and `Switch N: SYSTEM TEMPERATURE` for every stack member), `show power inline`, `show spanning-tree root` (the site's `-c01` core is root for every VLAN it carries at priority 24576, the CIST root the Fabric Engine switches report; not written at the branch, which has no designed root), `show ip default-gateway`, `show ip ospf neighbor`, `show ip protocols`, `show interfaces` (ending at the prompt) | environment, PoE, routing, interfaces |
| `raw/extreme_l3_raw_<host>.txt` | `lldp_detail_out` (VOSS 9 format), `port_state_out`/`port_name_out` (copper ports `1000BaseTX`, SFP cages `10GbSR`/`GbicNone`), `sysinfo_out`, `isis_adj_out`, `poe_out` | LLDP enrichment, ports, power and temperature, fabric |
| `raw/extreme_asbuilt_raw_<host>.txt` | `show spanning-tree mstp status` / `port role` (MSTP on the access side; the root is the Cisco core where a switch is dual-homed to it, its own CIST root otherwise; bridge IDs are priority + the synthetic MAC), `show interfaces gigabitEthernet error` / `statistics` | spanning tree (4.3 and the switching figure), interface health |
| `raw/palo_raw_<fw>.txt` | `show system info`, `show interface all` (padded columns), `show high-availability all` (with both units' software and content versions and the peer compatibility lines), `show logging-status`, static and default routes, routing summary, environmentals, licences, `show running security-policy`, `show running nat-policy` (outbound source NAT), `show vpn tunnel` (no tunnels) | firewall interfaces, zones, HA, policy, log forwarding |
| `backups/cisco|extreme|palo/<run>/…` | Full configurations: VLANs, interfaces, LAGs/MLTs, SVIs with HSRP, OSPF, NTP, DNS, syslog, SNMP groups and trap hosts, TACACS/RADIUS servers, SSH-only VTY, banner. PAN-OS backups also hold DNS servers, administrators (`mgt-config`, no password hashes) authenticated through a TACACS+ authentication profile, and its server profile (no shared secret). More than 20 lines, ending at the device prompt (the engine's completeness gate). HQ also keeps the July run (`20260720_020000`) | services, security baseline, gateways, interface config |
| `history/` (HQ only) | The July collection's snapshot, findings register, revision history and counter sample, written by the engine's own document step (see below) | 10 Changes since previous collection, finding history, interface rates |

**The customer's supplied files** (`<artifact root>/Riverside Technology Group/_supplemental/`, read through the engine's supplemental lookup, shown as supplied, never as discovered):
- `RTG_wan_services_export_20261019.csv`: the carrier's service export (`network.WAN_SERVICES`): internet services ending on the carrier CPE, the HQ–North and HQ–South Ethernet private lines, the HQ–DC1 dark fibre and the public address blocks. Fictional carrier; circuit identifiers `SYN-…`.
- `RTG_support_schedule_20261019.xlsx`: one maintenance record per collected switch unit and firewall, matched by serial, with `RTG_support_schedule_20261019.verified.json` recording the (synthetic) customer's check against the vendors' contract records. It says nothing about software lifecycle, which stays unverified.

**The access-layer endpoint population (`network.ENDPOINT_PLAN`, `populate_endpoints`).** Who is patched into the access switches, within the address plan. Each site has one /24 user VLAN, so wired workstations stay inside VLAN 20's endpoint pool (.21–.250); wireless users are on VLAN 50.

| Site | Desks | Other endpoints |
|---|---|---|
| HQ Building A (a01–a08) | 142, each a Cisco desk phone (CDP/LLDP name `SEP<MAC>`, VLAN 30 voice) with the PC behind it (VLAN 20) | 1 printer per switch (VLAN 70), 2 cameras per switch (VLAN 80), door and building controllers (VLAN 80) |
| HQ Building B (a09–a16) | 80, PC only (softphones) | 1 printer and 1 camera per switch, door and building controllers |
| North | 72 phone + PC | 3 printers (no security VLAN) |
| South (Fabric Engine) | 60 PC only | 3 printers in VLAN 20 (no printer VLAN), 6 cameras, 1 door controller |
| Branch | 14 phone + PC | 1 printer |

DC1's top-of-rack servers are not modelled.
- **Evidence:** endpoints appear only where the product collects and reads them:
  - each port's configuration (description "Desk A1-012", access VLAN, the voice VLAN on desk ports);
  - the port status audit (connected);
  - `show interfaces` (up, counters);
  - VOSS port state;
  - `show power inline` and VOSS PoE (phones 6.3 W, cameras 12.9 W, APs 15.4 W, per stack member);
  - CDP/LLDP for the devices that announce themselves. Workstations announce nothing.
- **Not written:** MAC address tables and ARP. The as-built collector does not save them and the offline report does not read them. Each endpoint's MAC (`02:72:75:…`, unique, locally administered) and address are in the design, where the validators check them.
- **History:** July and October have the same population, so the comparison shows only the recorded changes.

**Deliberate operational risks (HQ, `network.SUPPORT_EXCEPTIONS` and `network.PSU_FAULTS`):**
- c9300-hq-a05's contract ended on 21 Aug 2026, 60 days before the collection (schedule status `Expired`);
- c9300-hq-a06 has no record in the schedule;
- c9300-hq-a03 (C9300-48P, two PWR-C1-715WAC bays) reports power supply 1B `Bad` while 1A is OK; the switch keeps running.

Every other collected asset has an active contract. In July both of c9300-hq-a03's supplies were healthy.

**The July collection (HQ).** `network.as_of_july()` turns the design back to its state on 20 July 2026 (`network.JULY_CHANGES`: the core switches on 17.9.4a, the door controller's port in VLAN 20, HTTP management on the distribution pair, an older printer port description, one access point not yet installed). That collection is written first, with its own run name, device clock, uptimes and counters, and documented by the engine's own document step (`engine.record_history`: `document_from_collection` with history recording on, as the menu runs it after a live collection), with two differences from a live run: NetBox and the interactive maps are not consulted, and the engine's clock reads the July time. The October evidence is then written over it, and the offline report compares the two through the engine's normal snapshot comparison. Every file a collection writes carries that collection's date.

**No credentials are generated.** There are no passwords, communities or keys. SNMP and AAA lines name groups and servers only, and the one mandatory Extreme key field is `****`. `validate.py` and the tests fail on anything that looks like a credential.

**Supported formats only.** Formats were taken from the engine's parsers and its own synthetic test fixtures, not from collected output.

**Where the engine's model shapes the design:**
- **Fortinet:** there is no FortiGate collector, so FortiGates are LLDP neighbours.
- **Routers:** there is no router device kind, so routers are uncollected carrier CPE.
- **Distribution tier:** Sysopty tiers by name (`-cNN` is core), so distribution switches are named `-c03/-c04`.
- **Extreme interfaces:** Fabric Engine (VOSS) names its ports `1/1`, not EXOS-style `1:1`.

## Running it

```bash
cd sysopty_website
python build/make_synthetic_assets.py              # every stage, about 15 minutes
python build/make_synthetic_assets.py --stage validate
python -m pytest tests                             # includes tests/test_synthetic.py
```

Work files go to `%LOCALAPPDATA%\SysoptySiteBuild\synthetic` (override with `SYSOPTY_SYNTH_WORK`):
- `engine/` is the isolated engine copy;
- `artifacts/` is the synthetic customer;
- `reports/` holds the five reports;
- `enterprise_map/`, `vlan_maps/` and `manifest.json` are the other outputs.

The engine refuses artifact roots inside its own checkout, so the work folder must stay outside the platform checkout.

**Isolation of the engine** (`engine.py`):
- **The engine folder is a copy built from an allowlist:** the product's `*.py` source, plus `eol_models.csv`, the vendor lifecycle JSON and the plotly bundle.
- **These are never copied:**
  - site folders;
  - `All_Sites/` (support schedules) and `Panorama/`;
  - the carrier WAN export;
  - `config/` (site map), `.env`, `known_hosts`, `logs`, `backups`.
- **`verify_engine_copy()` rejects** any other file.
- **The engine runs with:**
  - a synthetic customer (`SYSOPTY_CUSTOMER`) and a synthetic site map;
  - a non-existent WAN export path;
  - `ASBUILT_PANORAMA=offline` and `SYSOPTY_NO_ENV_FILES=1`.

  So the offline report cannot read customer reference data even by its fallback paths.

## Dependencies

- Python 3.12 with the product's own dependencies (pandas, openpyxl, networkx, plotly, fpdf2, matplotlib).
- Graphviz `dot`.
- Playwright with Chromium, and Edge or Chrome for the engine's VLAN-map snapshotter.
- `pypdfium2`, installed beside the build scripts: `pip install --target build/.work/pylib pypdfium2`.
- The Sysopty product checkout one folder above `sysopty_site/`, read only.

## Validation

**`validate.validate_network`** checks:
- unique hostnames, management addresses, serials and MACs (all locally administered);
- inventory fields;
- every link endpoint exists, uses its vendor's port naming, and no port is used twice;
- VLANs carried by a link exist at both sites, and access links carry one VLAN;
- every SVI is inside its VLAN's subnet, with no address assigned twice;
- HSRP pairs;
- firewall interfaces have zones, sub-interface tags match, and zone VLANs are carried by the firewall's bundle;
- public addresses come only from the documentation ranges;
- service receivers are in the services subnet;
- every site's switches form one connected fabric;
- every carrier service ends where the model connects it (internet on an uncollected carrier CPE linked to a switch, private lines and dark fibre on a link of that purpose), address blocks are documentation ranges holding the site's firewall address, and every CPE carries a listed service;
- HA pairs are reciprocal, one active and one passive, with the same model and software;
- the deliberate risks are sound: the faulty bay exists on a collected Cisco switch, the expired contract ended before the collection, there is one expired and one unrecorded device, and each scenario is on a different device.

**`validate.validate_endpoints`** (part of `validate_network`) checks the endpoints:
- unique, locally administered unicast MACs and unique identities (hostnames and announced names);
- every address inside its VLAN's endpoint pool and unique;
- every endpoint patched to exactly one existing access port of a collected switch at its site (never an uplink, never a stack member or port the switch does not have);
- access mode in its kind's VLAN, which the switch's uplinks carry;
- each desk phone with exactly one workstation on its PC port;
- only workstations silent on CDP/LLDP;
- no switch with more patched ports than it has.

**`validate.validate_timeline`** checks that the July and October designs differ only by `network.JULY_CHANGES`: no other device, link, address or MAC changes.

**`validate.validate_evidence`** checks the written files, workbooks and CSV included: no credentials, no non-local MACs (a VOSS bridge ID is checked by its MAC) and no blocked words.

**`validate.validate_written`** checks the written evidence against the design:
- the carrier export holds exactly the designed services;
- the support schedule holds one record per collected asset serial, except the device the design leaves unrecorded, with valid dates; only the designed contract has expired, on its designed date, and every other one is active at the collection date;
- both power supply bays of every Cisco switch member are reported, only the designed bay is not OK, and that switch still reports running;
- each of the engine's supplied-file patterns matches exactly the intended file;
- the schedule's verification record is named as the engine reads it and claims no lifecycle verification, and no other verification record exists;
- the port status audit shows up exactly the linked ports;
- each endpoint port's configuration matches its patched endpoint (description, access mode, VLAN), and `show interfaces` shows it up;
- each Cisco member's PoE equals what its powered devices draw;
- every announcing endpoint is in the CDP/LLDP tables under its announced name and MAC, and no silent one is;
- every stack member reports its temperature;
- the HA peers' versions agree with their compatibility lines;
- HQ's history is the July collection (dated 20 July, July software, no later access point) and nothing else has history.

**`validate.validate_report`** checks each generated report against the design: device and capability counts reconcile, the unused-ports finding's count equals what the port status evidence gives, the stated findings totals match the register, every finding has a detailed record with a confidence and its evidence, HQ's medium BPDU guard finding stands, the WAN section lists exactly the supplied circuits, no lifecycle row claims a verified vendor source, the covered, expired and unrecorded assets reconcile with the design, the failed power supply, the expired contract (with its end date) and the unrecorded device each have their finding naming only that device, no collected switch lacks spanning-tree evidence, and HQ is compared with the July collection, including the two core upgrades. The `validate` stage runs it on the reports when they exist.

The tests prove each check fires by injecting the fault. `make_synthetic_assets.py --stage check` compares every generated and published file with the real customer data held on the build machine. It runs only where that comparison data exists, and prints matches only as keyed hashes.
