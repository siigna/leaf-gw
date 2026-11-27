# leaf-gw board: spec

An inline module that plugs in between comma's Nissan A car-harness cable and
the stock harness box, and puts the leaf-gw gateway on Chassis CAN without
cutting anything.

```text
car-harness cable ──18-pin──▶ [ leaf-gw board ] ──18-pin──▶ stock harness box ──OBD-C──▶ comma
```

> Bench and a dedicated test car only. This board sits on the brake path. The
> fail-open relay and its gating below are the safety design; don't change them
> without re-reading this file.

## Requirements

1. **Unpowered, reset or crashed = stock.** With no power, a held reset, a hung
   firmware or a tripped watchdog, Chassis CAN's two halves are joined by relay
   contacts and every other pin passes straight through. The car and the comma
   behave exactly as if the board weren't there.
2. **Firmware compatible.** Same MCU and the same pins as the RetroPilot Ocelot
   gateway (`firmware/boards/gateway.h`), so `backends/panda/gw_panda.c` runs
   with no more than a pin-map change.
3. **No car or harness modification.** Both 18-pin sides use the connector system
   comma's harness uses.
4. **Assembled by the board house.** Every part on the board is available for
   JLCPCB assembly (LCSC part numbers in the BOM); hand work is limited to
   plugging in cables.
5. **Checked in CI.** ERC, DRC, schematic/PCB parity, the safety-net checks below
   and fab outputs all run in `nix flake check`.

## The 18-pin connector

From comma's open drawings ([Nissan A harness](https://github.com/commaai/hardware/blob/master/harness/v3/Nissan_A_Harness.pdf),
[box pinout](https://github.com/commaai/hardware/blob/master/harness/v3/open_pinout.pdf)).
Connector: Molex 501646-1800 (cable side), crimp 501647-1000. The board's input
is a vertical through-hole 501645-1820 header, which the harness cable plugs
into. The board reaches the box through a second 501645-1820 and a short cable
with a 501646-1800 on both ends, pin n to pin n, positions 9 and 11 left empty.
No such cable is sold off the shelf; order it made from a drawing (for example
LCSC's cable service).

| pin | signal | on this board |
|---|---|---|
| 1, 17 | GND | through; board ground |
| 2, 14 | IGN | through; board power input |
| 3, 5 | bus-0 termination loopback | through (the box's jumper) |
| 13, 15 | bus-2 termination loopback | through |
| 4 / 6 | CAN0_H / CAN0_L (V-CAN, car side) | through |
| 16 / 18 | CAN2_H / CAN2_L (V-CAN, ADAS side) | through, **tapped** by transceiver 3 |
| 9 / 11 | CAN1_H / CAN1_L, ADAS side (from the cable) | **to transceiver 1**, and relay common |
| 8 / 7 | CAN1_H / CAN1_L, car side (from the cable) | **to transceiver 2**, relay NC, and through to the box's 8 / 7 |
| 10, 12 | 12VIN | through (not wired on the Nissan A harness) |

On the box side, pins 9 / 11 are left unconnected: the box would otherwise join
them to 8 / 7 and short around the gateway. The comma's bus 1 then sees Chassis
CAN as the car receives it, which is what the openpilot follow check reads.

## Blocks

### MCU

STM32F413RGT6 (LQFP64), 8 MHz HSE crystal (the panda clock setup expects it),
BOOT0 with a pull-down and a test pad / button for ROM DFU, NRST with a pad,
SWD pads (SWDIO, SWCLK, NRST, 3V3, GND).

Pins, matching the Ocelot gateway:

| function | pin |
|---|---|
| CAN1 RX / TX (Chassis, ADAS side) | PB8 / PB9 |
| CAN2 RX / TX (Chassis, car side) | PB5 / PB6 |
| CAN3 RX / TX (V-CAN tap) | PA8 / PA15 |
| transceiver 1 / 2 / 3 standby (high = standby) | PC1 / PC13 / PA0 |
| ignition sense (IGN through a divider) | PA1 |
| relay enable (high = energize) | PB12 |
| watchdog kick | PC6 |
| USB D− / D+ | PA11 / PA12 |
| status LED | PC7 |

### CAN

Three TJA1042T/3 (VCC 5 V, VIO 3.3 V). TJA1042 is passive when unpowered, so an
unpowered board doesn't load either bus. Each port:

- split termination (2 × 60.4 Ω + 4.7 nF to GND), enabled by a solder jumper,
  default **open**. Whether a segment needs it is measured on the car
  (`HARDWARE.md`, termination step).
- CAN ESD diode array (e.g. PESD2CAN class) at the connector side.
- 120 Ω differential routing.

### Fail-open relay

Omron G6K-2F-Y DC5 (DPDT signal relay, 5 V coil; rated to +70 °C, which
matters for where the board is mounted). Each pole's **NC** contact joins the ADAS-side and car-side CAN1 line
(H to H, L to L). Energized, the bypass opens and only the gateway connects the
two halves.

The coil is driven by a low-side N-MOSFET with a flyback diode, and it is
energized only when **both** of these hold:

1. the MCU drives relay enable (PB12) high, and
2. an independent hardware watchdog (TPS3828-33, open-drain) has been kicked
   within its timeout; its output goes low on timeout, and it also resets the
   MCU. Open-drain, because the STM32 drives NRST low itself on internal resets;
   a push-pull output would fight it.

The watchdog's WDI is left floating when the MCU isn't driving it, which
disables its timer (TI SLVS165O, 7.3.4). That keeps ROM DFU and SWD reset-halt
usable; in those states PB12's pull-down holds the relay off. The firmware must
toggle the kick pin (PC6) at least every 0.9 s once it engages the relay.

Gated by a single-gate AND (or two series MOSFETs). Pull-downs keep the gate off
while the MCU is in reset or unprogrammed.

Firmware order (not a board requirement, but the board must allow it): bring up
the transceivers, then energize the relay, then start forwarding. On any fault,
stop forwarding first, then release the relay.

### Power

From IGN (harness pins 2 / 14), about 150 mA at most including the relay coil:

- reverse-polarity protection (series Schottky or P-FET),
- load-dump / transient TVS for a 12 V vehicle system,
- input fuse (PTC or a fusible 0 Ω),
- wide-input buck converter → 5.16 V (so the 5 V rail stays in the TJA1042's
  4.5–5.5 V range after the USB OR diode; the relay coil is rated to 150 %),
- LDO 5 V → 3.3 V (MCU, VIO, watchdog),
- a power-good LED.

### USB

USB-C receptacle (USB 2.0 only), 5.1 kΩ CC pull-downs, ESD on D+/D−. USB VBUS
can power the logic on the bench through a diode-OR with the 5 V rail, so the
board can be flashed and used with Cabana without the car. The relay coil only
runs from the IGN-derived 5 V, so a board on USB alone stays in passthrough.

## PCB

- 4 layers, 1.6 mm, JLCPCB standard capabilities: 0.127 mm (5 mil) track and
  space, 0.3 mm vias.
- Stack-up: signal / GND / power / signal. A solid GND plane under the CAN and
  USB pairs.
- CAN pairs as 120 Ω differential pairs; USB D+/D− as 90 Ω.
- 12 V input traces at least 0.5 mm; relay and power pins with thermal relief.
- Pass-throughs scripted, not autorouted: every non-CAN pass-through runs on
  B.Cu in pin order, so none crosses another; the 12 V pins reach J2 on a short
  In2 hop between J2's holes (its other pads have no inner rings), and IGN
  reaches J2 on an F.Cu lane in the board-edge strip (`routes.passthrough`).
- Size target: 75 × 50 mm at most (about 70 × 45 aimed for), both 18-pin
  connectors on the short edges, USB-C on a long edge. The first target,
  under 60 × 40 mm, was too dense to route: freerouting and the grid repair
  left 1–3 connections open on every run. At 70 × 45 one connection still
  stayed open, so the board is 75 × 50 mm.
- Mounting holes ×2; silkscreen with the pin-1 marks, the bus names, and
  "bench / test car only".

### Silkscreen branding

- A leaf, `art/leaf.svg` (Phosphor Icons' "leaf", fill weight, MIT; notice in
  `art/LICENSE-phosphor-icons`), about 12 mm wide on the top side. Convert it to
  a footprint by script: flatten the curves to polygons and keyhole any holes,
  since KiCad graphic polygons can't have holes. Keep every line and gap at
  least 0.15 mm (JLCPCB's silkscreen minimum).
- Plain silkscreen text beside it: `leaf-gw`, the board revision, and
  `© 2026 Stephen Bouche · MIT`.
- The board first carried the ESCargot snail; the leaf replaced it as a better
  fit for a Leaf project.
- Knockout text (a filled silkscreen box with the letters left bare) for the
  bench warning on both sides and the two header names on the back.
- On the back, an ESD mark: a warning triangle with a paw cut out of it, drawn
  in code (`logo.esd_paw`, our own art, so MIT like the rest), about 8 mm wide.
- On the back, a QR code to <https://github.com/siigna/leaf-gw> (`logo.qr`;
  the URL in upper case so it fits version 2, 25 × 25 modules of 0.45 mm), dark
  modules left bare, so it reads dark-on-light on a dark mask. A white or
  yellow mask with black silkscreen needs the other polarity
  (`logo.QR_DARK_SILK = True`): zbar could not read the inverted code in the
  white-mask render.
- Functional labels next to their parts (`placement.LABELS`, placed by
  `build.labels` clear of pads, courtyards and other silkscreen): the
  termination jumpers by bus, SWD pads, BOOT0 pad and DFU button, status and
  power LEDs, USB, and which header is which. SWD's lower row is boxed in by
  parts, so it is named on a line above the upper row's labels.
- Mask colour is still open: `render.sh` renders both sides in every JLCPCB
  mask colour into `out/render/colors/`.

## Automated checks (the reviewer stand-in)

Nobody will review the layout by eye, so these run in `nix flake check` and must
all pass before any order:

1. **ERC** clean: SKiDL's ERC, errors and warnings (SKiDL can't generate a KiCad
   10 `.kicad_sch`, so there is no `kicad-cli sch erc`).
2. **DRC** clean against JLCPCB's rules (`kicad-cli pcb drc`), and **parity** by
   script: every PCB pad's net must match `out/leaf_gw.net`.
3. **Safety-net checks** (script, netlist-based):
   - every pass-through pin connects input to output and nothing else;
   - box-side pins 9 / 11 connect to nothing;
   - each relay NC contact joins the right ADAS-side and car-side line, and the
     relay common and NC nets are exactly as in the table above;
   - the coil driver's gate has a pull-down and is driven through the AND of
     relay enable and the watchdog output;
   - no CAN line connects to power or ground except through termination parts
     and its ESD array.
4. **Layout checks** (script, PCB-based): differential pairs routed as pairs
   with length mismatch under 1 mm, no CAN or USB pair crossing a plane split,
   12 V track widths, every part on the top side for single-sided assembly.
5. **Fab outputs:** gerbers, drill, JLCPCB BOM and pick-and-place generated from
   the PCB, every BOM line with an LCSC number.
6. **Renders** of both sides, so a person (or I) can at least look at it.

## Phases

1. Spec (this file).
2. Schematic as code (SKiDL → KiCad netlist), BOM with LCSC numbers, ERC and
   safety-net checks in CI.
3. Layout: placement by script, routing with freerouting, DRC, parity and layout
   checks in CI.
4. Fab outputs, a first order of about 5 assembled boards.
5. Bring-up: firmware pin-map port, bench tests from `HARDWARE.md`. Firmware done, not yet run on a board: the `leaf_gw_board` image and the host-tested relay/watchdog supervisor in [`backends/panda/`](../../backends/panda/README.md); bench steps in [`BRINGUP.md`](../../backends/panda/BRINGUP.md).
6. Enclosure: a 3D-printed case generated by code from the board's own files
   (outline, holes, part positions, and hulls of the parts' KiCad 3D models;
   manifold3d in nix), with cutouts for both headers, USB-C and the LEDs, a
   DFU pinhole, standoffs on the mounting holes, and checks for board/case
   interference, minimum wall thickness and connector clearance. Print in ASA or
   PETG, not PLA: a cabin behind the windshield gets hotter than PLA's ~55 °C
   softening point, and the relay is only rated to +70 °C.
   Printable by anyone: no supports, flat on the bed, fits a small (≤ 180 mm)
   bed, and fine in PETG on an open printer. Ship STL plus a pre-oriented 3MF;
   ASA wants an enclosed printer (tested target: Bambu H2D), and print services
   (e.g. JLC3DP) can print it for people without one. Done in
   [`hardware/enclosure/`](../enclosure/README.md); not yet printed.
