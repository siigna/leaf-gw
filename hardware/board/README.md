# leaf-gw board

The inline gateway board from [SPEC.md](SPEC.md). Phase 2 is the schematic as
SKiDL code, the BOM with LCSC numbers, and the checks that stand in for a
schematic review. Phase 3 is the layout: a 75 × 50 mm, 4-layer board built by
script from the netlist, routed (pairs by script, the rest by freerouting),
checked, and turned into JLCPCB fab files. Nobody reviews the layout by eye, so
the checks are the review; each of them has a mutation test that proves it
fails on a broken board.

## Files

| path | what |
|---|---|
| `SPEC.md` | the contract |
| `ORDER.md` | how to order from JLCPCB (files, options, what to check in the preview) and how to make the board-to-box cable |
| `schematic/` | SKiDL, one module per block: `connectors`, `mcu`, `can`, `relay`, `power`, `usb`; `parts.py` holds every part with its LCSC number; `nets.py` names the nets; `board.py` builds the board and writes `out/` |
| `footprints/leaf_gw.pretty/` | project footprints for parts KiCad's library lacks (the Molex iGrid header) |
| `out/leaf_gw.net` | KiCad netlist, for phase 3 to import into the PCB |
| `out/bom_jlcpcb.csv` | JLCPCB BOM: Comment, Designator, Footprint, LCSC |
| `out/parts.csv` | the same parts with manufacturer, MPN, JLC basic/extended and stock as checked |
| `out/no_connects.csv` | every pin left unconnected on purpose, with its reason |
| `checks/` | netlist reader, safety-net checks, BOM/footprint checks, mutation tests; `layout.py` and `test_layout_mutations.py` for the PCB |
| `check.sh` | runs the schematic checks (`board-schematic`) |
| `layout/` | the PCB build: `build.py`, `placement.py`, `routes.py`, `repair.py`, `board.py` (rules, stack-up, net classes), `impedance.py`, `logo.py`, `fab.py`, `render.sh` |
| `layout/leaf_gw.kicad_pcb`, `.kicad_pro`, `.kicad_dru` | the generated board, project (net classes, JLC rules) and custom DRC rules |
| `out/fab/` | gerbers + drill, `leaf_gw-gerbers.zip`, JLC BOM and CPL, the CPL rotation corrections with their sources |
| `out/render/` | `top.png`, `bottom.png` (3D) and SVG plots of each copper layer and the assembly view |
| `check_layout.sh` | runs the PCB checks (`board-layout`) |

`out/` and `layout/leaf_gw.*` are generated, but committed so the next phase
and the board house have them; the checks fail if they are stale.

There is no `.kicad_sch`: SKiDL 2.2.1 generates schematics only for KiCad 5 to
8 (`gen_schematic` for KiCad 9 and later is an unimplemented stub), and KiCad 10's
libraries are what nixpkgs ships. The netlist is the design's source of truth
between phases.

## Running the checks

```bash
nix develop .#hardware --command ./hardware/board/check.sh            # check
nix develop .#hardware --command ./hardware/board/check.sh --update   # after editing schematic/
nix flake check                                                       # includes board-schematic and board-layout
```

`nix flake check` copies the flake's git tree, so new files have to be
`git add`ed before it sees them.

Stages, in order (one failing stage doesn't stop the others):

1. **Build + SKiDL ERC.** Any ERC error or warning fails. Unused pins are
   connected to `NC` only through `nets.nc(pin, reason)`, which records the
   reason in `out/no_connects.csv`; every other unconnected pin is an ERC warning.
2. **Freshness.** `out/` must match a fresh build byte for byte.
3. **Safety-net checks** (`checks/safety.py`), on the netlist file and
   independent of the SKiDL code (expected pin numbers come from the
   datasheets, roles from SPEC.md's tables):
   - pass-through: pins 3, 5, 13, 15, 4, 6, 10, 12 join J1.n to J2.n and nothing
     else; GND, IGN, V-CAN ADAS-side and car-side CAN1 join J1 and J2 with no
     other harness pin; IGN enters the board only through the fuse;
   - box-side J2.9 / J2.11 connect to nothing;
   - relay: pole A COM on J1.9, NC on J1.8; pole B COM on J1.11, NC on J1.7;
     NO contacts open; the two CAN1 halves are not hard-wired;
   - CAN lines: each line holds exactly its harness pins, one transceiver pin
     (CANH on H), one ESD pin, one termination jumper and, on CAN1, its relay
     contact. Termination is default-open jumper → 60.4 Ω → split midpoint
     → 60.4 Ω → jumper, midpoint → 4.7 nF → GND. Anything else on a CAN line
     fails, so a CAN line has no other path to power or ground;
   - coil driver: coil+ on the IGN-derived 5 V, coil− on the low-side FET drain
     with a flyback diode; the gate net holds only the AND output and one
     pull-down; AND input A is PB12 with one pull-down; input B is the
     open-drain watchdog RESET, which is also MCU NRST; WDI is driven only by the
     kick pin;
   - USB isolation: the coil supply is not DC-reachable from VBUS (diodes
     forward only), and it is reachable from IGN;
   - MCU pins, by LQFP64 pin number: CAN1/2/3 RX/TX and standby go to the
     transceiver on the right bus, PA1 to the IGN divider, PA11/PA12 to USB D−/D+;
     no two table pins share a net.
4. **BOM + footprints** (`checks/bom.py`): every assembled part has an LCSC
   number and a JLC library type; designators are unique in the netlist and in
   the CSV; the CSV lists exactly the assembled parts; parts off the BOM are bare
   copper (test pads, solder jumpers) with a reason. Every footprint exists and
   has a pad for each connected pin.
5. **Mutation tests** (`checks/test_mutations.py`): 41 in-memory mutations of
   the real netlist, each of which must make its check fail (relay NC/NO
   swapped, poles crossed, box 9/11 connected, gate pull-down dropped, gate fed
   from PB12 directly, watchdog off NRST, CAN1 on the CAN2 pins, RX/TX swapped,
   resistor from a CAN line to GND, closed termination jumper, coil on the USB
   rail, OR diode reversed, missing LCSC, duplicated designator, pin without a
   pad, and more), plus the unmutated netlist passing everything.

## Layout (phase 3)

### Pipeline

`layout/build.py` builds `layout/leaf_gw.kicad_pcb` from `out/leaf_gw.net`.
It takes about 40 minutes, most of it in the pre-route searches and freerouting.

1. **Project and rules.** It writes `leaf_gw.kicad_pro` (net classes, the JLC
   minimums, DRC severities) and `leaf_gw.kicad_dru` (12 V track width, via
   drill and ring).
2. **Board.** A 75 × 50 mm outline with 1 mm corner radii goes on a 4-layer
   board. Every footprint comes from the netlist with its fields and pad nets,
   placed by `placement.py`, all on the top side. Two M2 mounting holes go in
   opposite corners.
3. **Critical routes by script** (`routes.py`). The four CAN pairs and the USB
   pair are drawn coupled at the impedance geometry, split evenly around their
   tap clusters, and length-matched with small rectangular bumps (`TUNE`).
   freerouting has no differential-pair support, so the pairs never reach it.
   The same file draws a few hand routes into spots freerouting can't reach:
   CC1, SWDIO, the MCU supply pins boxed in by their neighbours, and the
   USBLC6's VBUS via. It also draws the short local copper that must not be
   left to chance (`LOCAL_LINKS`, `POWER_LINKS`): each transceiver's VCC and
   VIO cap, U5/U6's supply cap, the termination chains off the relays' NO
   contacts, the two coils in parallel, and the buck's own copper (switch
   node, hot-loop VIN and GND, bootstrap, feedback and its sense at the output
   cap, the input protection).
4. **Fanout** (`build.fanout`). Each SMD pad on GND or +3V3 gets a via to its
   plane. So does each signal pin the CAN lines close in on (`routes.FANOUT_SIGNALS`).
   A spot is accepted only where the via's In1 antipad stays clear of the GND
   plane under the pairs, and where its ring keeps `board.VIA_PAD_WEB` from
   every SMD pad, its own net's included (no via in or touching a pad).
5. **Pre-routes** (`repair.preroute`, list in `routes.PREROUTE`). The
   transceivers' STB lines and the MCU's top-row CAN pins and BOOT0 are
   routed first with the
   grid router (step 8), while the board is still open. Each search is capped
   (8 M expansions, 900 s, a box 14 mm around its ends) and logs why it gave
   up; whatever fails is left to freerouting.
6. **Silkscreen.** Library silkscreen that would print on a pad or overlap
   other silkscreen is dropped (`silk_cleanup`). Then the logo, the text, the
   back-side pin names and the bench warning go on, and a cathode bar beyond
   pad 1 of every diode and LED whose library mark was dropped
   (`polarity_marks`).
7. **freerouting.** The board is exported to DSN and the DSN is patched. In1
   and In2 become power layers, so nothing routes on them. The pairs and the
   plane nets leave the network, and their copper turns into keepouts. Each
   pair also gets a via keepout as wide as the reference-plane check needs,
   and the strip between J2's edge-side pin row and the board edge gets one
   too (`routes.VIA_KEEPOUT`: via antipads there pinch the In2 plane). New vias
   use a padstack 0.05 mm wider than the real one, so freerouting's via-to-via
   clearance also keeps 0.5 mm hole to hole; they are shrunk back after the
   import. The DSN also says `via_at_smd off`, and B.Cu under the buck's
   switch node and L1 is a keepout (`build.quiet_zone`). freerouting 2.5 then runs single-threaded (`-mt 1`) with a fixed
   pass count (wall time capped at 900 s), and the SES is imported back.
8. **Repair.** If freerouting leaves anything open, `repair.py` routes it on a
   0.05 mm grid (A* over F.Cu and B.Cu with vias, capped at 4 M expansions
   and 240 s per search), clear of every other net's copper, of the via
   keepouts and, for its vias, of every SMD pad. On the committed board freerouting finished everything, so the
   repair had nothing to do.
9. **Clean-up and zones.** Tracks that freerouting necked below the minimum
   are widened back where there is room (`widen_necks`); one that can't be
   widened is taken out and its gap repaired at full width. Every lone via
   on a 12 V or 5 V net gets a twin 0.85–1.4 mm away, joined on both layers
   (`twin_power_vias`). The zones go on: In1 solid GND, In2 solid +3V3, and
   GND pours on F.Cu and B.Cu with thermal reliefs, and are filled. Then
   `stitch_gnd` puts GND vias along the board edge about every 5 mm where
   both pours leave room, gives every outer pour island at least two vias to
   In1, and cuts an island that can't take them out of its pour (a rule
   area), unless a pad hangs on it alone. Then `drop_dangling` deletes every via joined on
   fewer than two layers and every track with a loose end (freerouting's
   leftovers, fanout and escape vias it bypassed), one at a time and only if
   nothing comes apart without it.
10. **Normalise.** Every UUID is renumbered in file order from a fixed
   namespace, so the same inputs give the same file, and `leaf_gw.kicad_pro`
   is written again after pcbnew's save (which rewrites it).

`layout/fab.py` then writes `out/fab/` and `layout/render.sh` writes
`out/render/`.

### Placement

`placement.py` and `routes.py` are drawn on the first, 59 × 39.5 mm board.
That was too dense: freerouting and the repair left 1 to 3 connections open
on every run. `board.spread()` opens the drawing up into the 75 × 50 mm
outline by moving whole blocks rigidly. It adds 1, 10 and 5 mm in x at three
vertical cuts (J1's pin field | the clusters and MCU, ADAS side and relay |
car side, car side | J2's pin field), 3 mm in y below the top band and 7.5 mm
below CAN0, between the headers. Groups that sit in room the spread opened,
or would straddle a cut, are placed and routed in board mm after the spread
(`placement.CAR`, `ADAS_TERM`, `POWER`; `routes.car_side`, `POWER_LINKS`):
the car side right of K1 with K2, both termination chains, the power entry
and the buck, the LDO strip, and U5/U6's supply caps. Nothing in them moves
with a cut. Only straight runs along the shift cross a
cut, so every scripted route keeps its shape (`routes._spread` asserts it),
and the pair lengths change equally on both lines. A 70 × 45 mm version of
the same spread still left one connection open (CAN2_STB, then RELAY_GATE),
so the board went to the 75 × 50 mm limit.

The two headers sit on the short edges in the same orientation: rotation 90,
pin 1 at the bottom, the even row toward +x. Pin n of J1 and pin n of J2 are
then at the same height, so the pass-through nets run straight across. The
blocks are:

| where | what |
|---|---|
| top left | CAN2 (V-CAN tap): ESD array, transceiver 3, termination, between the CAN2 lines; under it the LDO with its caps |
| top right | the buck as one group (below); right of it the power entry: reverse diode, TVS, PTC tapping the B.Cu IGN lane; the power LED; test pads TP7–TP10 |
| middle left | CAN1 ADAS side next to J1: ESD array, transceiver 1 |
| middle | K1 on all four CAN1 lines, between the two halves; the ADAS-side termination along its top, off its NO contacts |
| middle right | K2 on the car-side lines, the car-side termination beside its NO contacts, then the car-side ESD array and transceiver 2 |
| across | CAN0, straight through |
| bottom | MCU (crystal and decoupling at its pins), USB-C on the bottom edge with the USBLC6 beside it, relay driver and watchdog, SWD pads, DFU button, ignition sense |

Each CAN tap cluster sits between its own two bus lines, L over the top and H
underneath. The ESD array (rotation 180, pads 1/2 on its right) faces the
transceiver's CANL/CANH pins (rotation 180, pins 6/7 on its left) across a
0.77 mm channel. Short spurs drop into that channel from each line. This is
how the lines tap the cluster without crossing each other, so the CAN copper
needs no vias at all.

The buck (U7) is one tight group: D8 right above the SW pin, the input caps
right of VIN with C26 first and their GND pads under D8's anode (hot loop
C26–VIN–SW–D8–GND 10.3 mm², from 60.9), L1 beside D8 on the same SW copper
as the bootstrap cap, the output caps under L1's output, and the feedback
divider between them and the FB pin, so FB, CB and the sense at C28 are a few
mm on F.Cu. The output caps' GND is on the far side of the group from D8's
anode (about 12 mm, through the pour and In1 0.2 mm below); keeping both
loops on the same side would have pushed the sense trace and the input feed
across each other.

K2 (rotation 90) takes the car pair through the channel between its pad
rows: the L line leaves up through COM_B and the H line down through COM_A,
so the contacts sit on the lines with no stub, and its NO pads face the
car-side jumpers. Its coil pads sit next to K1's; the two coils are joined on
F.Cu (+5V_IGN) and share the driver and flyback diode.

The relay is DPDT, pole B (L) in the left column and pole A (H) in the right.
ADAS L lands on COM_B from the left. ADAS H passes between COM_B and NC_B to
COM_A from inside. Car L lands on NC_B and leaves between COM_A and NC_A. Car
H passes under NC_B to NC_A. None of the four lines crosses another.

### Stack-up and impedance

JLC04161H-7628, 1.6 mm, as listed at
[jlcpcb.com/impedance](https://jlcpcb.com/impedance) (read 2026-11-26):

| layer | role | copper | to next layer |
|---|---|---|---|
| L1 F.Cu | signal (pairs) | 35 µm | 7628 prepreg 0.2104 mm, εr 4.4 |
| L2 In1.Cu | GND plane | 15.2 µm | core 1.065 mm, εr 4.6 |
| L3 In2.Cu | +3V3 plane | 15.2 µm | 7628 prepreg 0.2104 mm, εr 4.4 |
| L4 B.Cu | signal | 35 µm | |

`layout/impedance.py` computes the pairs as edge-coupled microstrip on L1 over
L2. The single line uses Hammerstad & Jensen with the finite-thickness
correction; the coupling uses Garg & Bahl's even/odd capacitances. Both are
static and ignore solder mask, which lowers the impedance by a few percent.
IPC-2141A is shown as a coarse cross-check:

| pair | width | gap | Zdiff (Garg-Bahl) | IPC-2141A | target |
|---|---|---|---|---|---|
| CAN (4 pairs) | 0.19 mm | 0.20 mm | 120.0 Ω | 111 Ω | 120 Ω |
| USB D+/D− | 0.35 mm | 0.20 mm | 89.8 Ω | 81 Ω | 90 Ω |

As a sanity check, the same single-line model puts 50 Ω at 0.36 mm on this
stack-up. Before ordering, confirm both pairs in JLC's own impedance
calculator, which includes the mask. You may also order "impedance control"
on this stack-up (see Ordering).

### JLCPCB rules

The rules come from [jlcpcb.com/capabilities/pcb-capabilities](https://jlcpcb.com/capabilities/pcb-capabilities)
(multilayer, 1 oz, read 2026-11-26). They live in `layout/board.py` and are
written into the project file:

| rule | board | JLC |
|---|---|---|
| track / space | 0.127 / 0.127 mm (SPEC); net classes 0.15 clearance | 0.09 / 0.09 mm |
| via | 0.3 mm drill / 0.6 mm pad (0.15 mm ring) | 0.15 / 0.25 mm min; ring ≥ 0.15 mm absolute minimum |
| hole to hole | 0.5 mm | 0.2 (vias), 0.45 (pads) |
| copper to routed edge | 0.25 mm | 0.2 mm |
| silkscreen | 0.15 mm line, 1.0 mm text, 0.15 mm from pads | the same |
| 12 V input (IGN, IGN_FUSED, VIN_PROT, VIN12_10/12) | ≥ 0.5 mm (custom DRC rule) | |

Net classes: CAN 0.19 mm, USB 0.35 mm, 12V 0.67 mm, Power 0.4 mm and Default
0.17 mm. Two of these are wider than the floor on purpose. Where freerouting
squeezes between pads it necks a track to about 3/4 of its class width, and
these class widths keep a necked track at or above 0.127 mm and 0.5 mm.

### Checks

`check_layout.sh` (flake check `board-layout`) runs these stages:

1. **Self-checks.** The impedance geometries are within 3 % of target, and
   the logo conversion works: the cleaned leaf has no line or gap under
   0.15 mm, a keyholed polygon with holes survives the round trip, and the
   SVG path parser gets an arc's area right and still reads the old snail.
2. **Freshness.** `leaf_gw.kicad_pro` and `.kicad_dru` match the generator.
3. **DRC.** `kicad-cli pcb drc --severity-all` reports 0 errors, 0 warnings
   and 0 unconnected items, against the JLC rules above. Schematic parity is
   left to stage 4, because there is no schematic.
4. **Layout checks** (`checks/layout.py`). They work on pcbnew's own copper
   shapes, independent of the build scripts:
   - parity: every netlist part is on the board with its footprint, every pad
     has the netlist net of (ref, pad), and pads the netlist leaves open have
     none. Nothing extra is allowed except H1, H2 and LOGO;
   - every footprint is on the top side;
   - pairs: all pair copper is on F.Cu, with no via, at the impedance width.
     The only narrower pieces allowed are the USB plug-flip links within
     2.5 mm of J3. Outside the listed `routes.UNCOUPLED` zones (header pin
     fields, the cluster splits, the relay, the USBLC6, the tuning bumps),
     each line sits exactly width + gap from its partner (±10 µm);
   - mismatch: the H/L copper length from the reference end to each bus end
     and transceiver is under 1 mm. The lengths are computed over the track
     graph and printed;
   - reference plane: under every pair track, the In1 GND fill covers the
     track width plus one prepreg height (0.21 mm) on each side, so there is
     no split, no void and no other net's antipad. The header pin fields and
     the USBLC6 are exempt; their own PTH and via antipads are unavoidable;
   - 12 V: every IGN, IGN_FUSED, VIN_PROT and VIN12 track is ≥ 0.5 mm;
   - keepouts: no other courtyard sits within 0.5 mm of either header body
     (the mating face). The USB-C front is at the bottom edge (−0.1 to
     +0.6 mm), and no courtyard sits in the 12.35 mm plug-overmold zone along
     that edge;
   - copper safety: islands are built by physical overlap of every pad,
     track, via and zone fill, per layer and through the holes, ignoring
     their net labels. No island may join two netlist nets, or a net and an
     open pad, and every net must be one island. The relay COM pads reach
     only the ADAS-side lines and the NC pads only the car side, so the two
     CAN1 halves touch only through the contacts. Box pins J2.9 and J2.11
     touch no track or zone on any layer;
   - silkscreen: the logo, as drawn on the board, has lines and gaps of at
     least 0.15 mm, is about 12 mm wide and sits on the top. No silkscreen on
     either side comes within 0.15 mm of a solder-mask opening or runs off
     the board;
   - pin labels: each header has exactly one back-side label per pin row
     ("n … / n+1 …"), its centre within 0.3 mm of that row's pins, on the
     header's inner side with its near end 0.15 to 5 mm from the pads;
   - In2: only short hops on the +3V3 plane, which stays one region with no
     neck under 1.0 mm (see "Known limits");
   - vias and pads: no via ring overlaps or touches any SMD pad, its own net's
     included, so the hole edge keeps at least 0.15 mm of copper web;
   - polarity marks: every diode and LED has top silkscreen within 1 mm beyond
     pad 1 (the cathode), across at least half the pad's width;
   - power vias: every via on a 12 V or 5 V net has a second via of its net
     within 1.5 mm (the USBLC6's VBUS reference pin, boxed in by the USB pair
     and carrying no load current, is exempt), and the switch node has none;
   - GND stitching: every F.Cu or B.Cu GND pour island reaches In1 through at
     least two vias or plated GND pins, and along the board edge (1 mm in),
     wherever both pours leave room for a via, one sits within 3.5 mm
     (except the via keepout strip beside J2);
   - 12 V off the MCU: no VIN_PROT or IGN_FUSED copper within 3 mm of U1's
     courtyard;
   - switch node: nothing but GND on B.Cu under the buck's switch node and
     L1 (0.3 mm around), and no other net on F.Cu inside L1's courtyard.
5. **Mutation tests** (`checks/test_layout_mutations.py`). Each test loads the
   real board, breaks it in memory and asserts that its check fails for the
   intended reason:

   | mutation | caught by |
   |---|---|
   | two pads' nets swapped | parity |
   | a footprint deleted | parity |
   | an extra footprint added | parity |
   | a capacitor flipped to the bottom | top side |
   | a CAN0_L run moved 0.3 mm | pairs (uncoupled) |
   | a via dropped into CAN0_H | pairs (via) |
   | a CAN2_L run moved to B.Cu | pairs (layer) |
   | a USB D+ run narrowed to 0.2 mm | pairs (width) |
   | a 1.2 mm detour added to CAN0_H | mismatch |
   | a 1 mm slot cut in In1 under CAN0 | reference plane |
   | the In1 GND zone deleted | reference plane |
   | an IGN track narrowed to 0.3 mm | 12 V width |
   | a resistor moved onto J1's mating face | keepouts |
   | J3 moved 2 mm in from the edge | keepouts |
   | a resistor moved into the USB plug zone | keepouts |
   | a track across relay COM_A to NC_A | copper safety (short) |
   | the ADAS L track to COM_B removed | copper safety (open) |
   | a track touching J2.9 | copper safety (box pin) |
   | a pass-through loop's tracks removed | copper safety (open) |
   | the logo moved onto MCU pins | silkscreen (pad opening) |
   | a 0.1 mm line added to the logo | silkscreen (line width) |
   | a J2 pin label moved 1 mm off its row | pin labels |
   | a relay K2 COM track removed | copper safety (K2) |
   | a GND fanout via moved onto C26's pad / its ring 0.2 mm into the pad | vias and pads |
   | D6's cathode mark removed | polarity marks |
   | a +5V_IGN via's twin removed | power vias |
   | a via on the switch node | power vias |
   | one of the two vias of a GND pour island removed | GND stitching (island) |
   | the GND vias along the middle of the top edge removed | GND stitching (edge) |
   | a VIN_PROT track across the MCU | 12 V off the MCU |
   | an IGN_SENSE track on B.Cu under L1 | switch node |
   | a 10 mm SWDIO track on In2, In2 split, In2 neck | In2 |
   | a CAN0_H stub run into CAN0_L, saved and run through `kicad-cli pcb drc` | DRC |

   The unmutated board must pass every check.
6. **Fab outputs.** `fab.py` must reproduce `out/fab/` byte for byte. The fab
   BOM must match `out/bom_jlcpcb.csv` part for part (LCSC, footprint, MPN),
   every BOM line must have an LCSC number, and the CPL must list exactly the
   BOM parts.

`./check_layout.sh --rebuild` also builds a fresh board in /tmp/lgw/rebuilt
and requires it to pass the DRC and the layout checks. That takes about 40
minutes, so the flake check leaves it out. Fresh builds don't reliably
converge yet (see "Known limits").

Silkscreen-only changes don't need a re-route: `kicad-python build.py
--silk-only` (in `layout/`) redraws the logo and all silkscreen text on the
saved board from `placement.py` and `logo.py` and leaves copper and fills
alone.

### Regenerating

```bash
nix develop .#hardware --command ./hardware/board/check_layout.sh --update   # rebuild board, fab, renders; then check
nix develop .#hardware --command ./hardware/board/check_layout.sh            # check only
```

After editing `placement.py` or `routes.py`, look at the mismatch report that
`checks/layout.py` prints and adjust `routes.TUNE` if a pair moved.

### Ordering (JLCPCB)

**PCB:** upload `out/fab/leaf_gw-gerbers.zip`. Pick these options:

- Layers 4, dimensions 75 × 50 mm (detected), thickness 1.6 mm, FR-4.
- Impedance control yes, stack-up JLC04161H-7628. That is the stack-up the
  pair widths were computed for.
- Via covering tented, which is what the board assumes; silkscreen runs over
  vias.
- Green mask, white silkscreen. Surface finish: HASL lead-free, or ENIG for
  the 0.5 mm-pitch MCU.
- Remove order number: "specify a location" or pay to remove it. There is no
  marked spot, so pick "remove".
- Board outline tolerance standard. Leave edge rails and tooling holes to
  JLC's assembly options.

**Assembly:** PCBA on the top side, Standard (not Economic). The board has
through-hole headers and extended parts. Upload:

- `out/fab/leaf_gw-bom.csv` as the BOM. All 37 lines have LCSC numbers.
- `out/fab/leaf_gw-cpl.csv` as the CPL. Mid X/Y are in mm from the board's
  bottom-left corner, all parts on the top.

In the placement preview, check every part listed as "verify" in
`out/fab/leaf_gw-cpl-corrections.csv`. Those are the relay, the MCU, the
SOT-23-6 parts, the iGrid headers and every polarized two-terminal part,
whose rotations come from footprint-family tables rather than part-specific
evidence. Adjust the rotations there if a body or pin-1 mark is off. The
headers J1/J2 are through-hole on the top side; JLC solders those by
selective/wave or by hand as part of Standard PCBA. Buy the MCU (C468260,
90 in stock on 2026-11-26) early.

**The box cable** is a separate order. It is a 501646-1800 receptacle on both
ends, crimped 501647-1000 terminals, pin n to pin n, positions 9 and 11 left
empty, 26 AWG, about 100 mm. Order it from a harness service with a drawing,
for example LCSC Cable ([lcsccable.com](https://lcsccable.com), no MOQ). See
"Connectors" above for the part numbers. Leaving positions 9 and 11 empty is
part of the safety design, so state it on the drawing.

### Known limits of the layout

- **Routing is complete.** The committed board is a fresh `build.py` output
  (no hand edits): DRC 0 errors, 0 warnings, 0 unconnected, and every layout
  check and mutation test passes. The pre-order review revision was validated by two fresh
  `check_layout.sh --rebuild` runs on 2026-11-27, both valid on the first
  routing attempt; an earlier pair had one run leave SWCLK unrouted on all six
  attempts, so SWCLK is now pre-routed (`routes.PREROUTE`).
- **The buck's output loop closes through the pour.** The output caps' GND
  sits about 12 mm from D8's anode, on the far side of the group (see
  "Placement"); the return runs in the F.Cu pour and the In1 plane 0.2 mm
  below. The input hot loop, the one with the fast edges, is 10.3 mm².
- **USBLC6 VBUS has one via.** U9's VBUS pin is the clamp's reference and
  carries no load current; it is boxed in by the USB pair, so its single via
  is exempt from the twin-via rule. The load path from J3 to D10 has twins.

- **CAN1 ADAS pair is never coupled.** It runs from J1's pins around
  transceiver 1 to the relay's COM contacts. All of that is header breakout,
  cluster split or relay, so its uncoupled zone covers the whole run. The
  length match still holds (0.00 mm to the transceiver and to the relay). At
  500 kbit/s and about 30 mm the coupling doesn't matter, but the
  120 Ω-everywhere ideal isn't met there.
- **Reference-plane margin is one prepreg height** (0.21 mm beyond the track
  edge), not two. With two, there were too few via spots for freerouting.
  The tighter margin still keeps every void and antipad out from under the
  pairs.
- **Routing is retried until valid.** freerouting gives a few different
  tracks on every run from the same input, and some runs leave a connection
  open. `build.py` validates each routed board (DRC plus every layout check)
  and routes again from the placed board, up to `ROUTE_ATTEMPTS` times, so a
  fresh build either produces a valid board or fails loudly. The board files
  still differ byte for byte between builds; `check_layout.sh --rebuild`
  checks that validity reproduces.
- **The non-CAN pass-throughs are scripted** (`routes.passthrough`). J1 and J2
  sit in the same orientation, so each even pin is on J1's board-side row and
  on J2's edge-side row, and a 0.5 mm track can't pass between J2's 1.5 mm
  pads on 2 mm pitch. Left to the routers, the 12 V and IGN tracks went around
  J2's ends, crossed each other and failed differently on every build. Now the
  bus loops, IGN and 12 V run on B.Cu in pin order (no crossings), VIN12_10/12
  enter J2 on a ~4.5 mm In2 hop (two vias) between its holes (J2's other pads have no
  inner rings), and IGN, which carries the comma's supply, reaches J2.14/J2.2
  on an outer-layer lane along the board edge. In2 carries nothing else:
  `check_in2` limits any In2 copper to 5 mm per net and requires the +3V3
  fill to stay one region with no neck under 1.0 mm. A 1.0 mm neck of 15.2 µm inner copper carries 0.65 A at 10 °C
  rise by IPC-2221's internal-conductor formula, a conservative bound next to
  IPC-2152. That is over 4 × the 150 mA load.
- **CPL rotations** for the parts marked "verify" are from family tables (see
  `fab.py`), not from each LCSC part's EasyEDA footprint. The per-part
  resolver (`jlcfootprint` from kicad-jlcpcb-tools, a flake input) needs
  EasyEDA's answers recorded first, and fetching them wasn't done here.
  Running `tools/jlcfootprint/fetch_easyeda_fixture.py` for the 37 LCSC
  numbers and then its `validate_board.py` on this board would replace the
  table with per-part rotations.
- **Silkscreen** text is narrower than KiCad's default: 1.0 mm high, 0.6 to
  0.8 mm wide, 0.15 mm strokes. The text kept its place from the
  compact drawing: the copyright
  line runs above the MCU, the name runs vertically beside J2, and the bench
  warning sits over J1. The back carries the pin names of both headers and
  the warning again, large.
- **Reference designators** are on F.Fab only, not the silkscreen; at this
  density they would print on pads. The assembly SVG in `out/render/` shows
  them.

## Connectors

comma's car-harness cable ends in a Molex **501646-1800** iGrid receptacle
(2.00 mm, 2×9). Molex lists three mating headers: 501645 (vertical, through
hole), 503091 (vertical) and 501876 (right angle; the harness box uses
501876-1840).

- **J1, J2: Molex 501645-1820** (LCSC C504976), vertical through-hole with a PCB
  locator, 5765 in stock. The right-angle 501876-1840 (C293583) had 4 in stock,
  not enough for 5 boards; 503091 18-way isn't stocked. JLCPCB assembles
  through-hole parts on the top side, so assembly stays single-sided.
  The iGrid header is rated for 30 mating cycles.
- **Board to box:** the box's 501876 header needs a 501646-1800 receptacle, so
  the link is a short cable with a 501646-1800 on **both** ends, wired 1:1
  (pin n to pin n), 26 AWG, about 100 mm, positions 9 and 11 left empty. Parts:
  2 × 501646-1800 (C564678), 16 × 501647-1000 terminals (C122426). Molex lists
  no off-the-shelf iGrid cable assembly, so order it pre-made from a harness
  service (LCSC Cable, lcsccable.com, takes drawings with no MOQ; Molex's custom
  cable service is the alternative). The user only plugs it in. Leaving 9/11
  empty in the cable keeps the box's CAN1 ADAS pins open even if the board were
  wrong.

The header footprint is project-local because KiCad's library has no iGrid
part. Its geometry is verified against Molex's drawing SD-501645-001: 0.80 mm
pin holes (±0.05) in 1.5 mm pads, 2.00 mm pitch both ways, and the 1.4 mm
locator (1.3 +0.1/−0) 1.2 mm outside the pin 1/2 column and 3.1 mm from the
lock-side row. The body is 20 × 8.2 mm. `checks/test_footprint.py` pins these
numbers. The drawing is Molex-proprietary and is not in the repo.

## Part choices

All 38 BOM lines are JLCPCB-assemblable: 20 basic, 1 preferred extended, 17
extended. `out/parts.csv` has the lot, with stock as of 2026-11-27.

| block | part | LCSC | note |
|---|---|---|---|
| MCU | STM32F413RGT6 | C468260 | as spec; only 11 in stock on 2026-11-27, so buy it early |
| CAN ×3 | TJA1042T/3/1J | C132227 | STB and TXD pulled up to VIO inside (datasheet 7.2.3), so standby by default |
| CAN ESD ×3 | PESD2CAN,215 | C75176 | |
| relay ×2 | Omron G6K-2F-Y DC5 | C2982926 | as spec; K2 switches the car-side termination, coil parallel to K1's |
| coil FET | AO3400A | C20917 | logic-level at 3.3 V gate |
| AND | SN74LVC1G08DBVR | C7666 | |
| watchdog | TPS3828-33DBVR | C20032 | **substitution**, see below |
| buck | LMR16006YDDCR, 6.8 µH SWPA4030S6R8MT | C290195, C62684 | 4–60 V in, 600 mA, 2.1 MHz (above the AM band) |
| LDO | MCP1700T-3302E/TT | C39051 | −40…+125 °C; low dropout, so USB-only power works |
| input | mSMD050-60V PTC (1812), SMBJ33A, SS210 | C70113, C224019, C14996 | fuse → TVS → reverse diode |
| USB | HRO TYPE-C-31-M-12, USBLC6-2SC6 | C165948, C7519 | |

Pin picks the spec left open: watchdog kick **PC6**, status LED **PC7**, both
unused by the Ocelot gateway board. BOOT1 (PB2) is pulled down so ROM DFU boots
system memory.

## Deviations from SPEC.md

- **Watchdog TPS3828-33 instead of TPS3823-33.** Same family, pinout and
  timing (SLVS165O), but the RESET output is open drain. TPS3823's push-pull
  output on NRST would fight the STM32, which drives NRST low itself on IWDG and
  software resets. Open drain on a shared NRST net also means every MCU reset
  releases the relay.
- **Floating WDI disables the timer** (SLVS165O 7.3.4). WDI has no pull
  resistor, so the watchdog does not bite while the MCU is in reset, in ROM DFU
  or halted under SWD reset. That is what makes flashing possible, and in all
  three states PB12 is high-Z and its pull-down keeps the relay off. While
  firmware runs, a stalled kick pin times out in 0.9–2.5 s. The firmware must
  toggle PC6 at least every 0.9 s; the board image does so every 100 ms from
  the main loop, only while healthy (`gw_supervisor.c`).
  Breakpoints longer than that reset the MCU.
- **Buck at 5.32 V, not 5.0 V** (28k / 4.7k on the 0.765 V reference). After the
  OR diode, +5V_SYS has to stay inside the TJA1042's 4.5–5.5 V VCC range. The
  relay coil runs from +5V_IGN before the diode; it is rated for 150 % of 5 V.
- **Vertical headers**, not right-angle (stock, above).
- **Ignition sense**: 100k / 22k from the protected IGN rail, 100 nF, and a
  1N4148W clamp to 3V3 (12 V in gives 2.16 V on PA1, 3.3 V at 18.3 V). The
  100k sits at the 12 V source by the buck, so only the divided IGN_SENSE
  runs to the MCU.
- **No `.kicad_sch`**, so phase 2's ERC is SKiDL's, not `kicad-cli sch erc`.
