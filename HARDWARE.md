# Hardware

What runs the gateway, and the one part that makes it safe on a car.

> Bench / dedicated test car only. The on-car gateway is unproven; see the
> blocker in the README. Any board here is a logger until it has a fail-open
> relay that reverts to the stock path.

## Recommended bench stack (RetroPilot)

- **Ocelot Pro** — STM32F413RGT6, **3× TJA1042** CAN transceivers, 12 V in, a
  PA1-switched **IGN_OUT** rail (12 V 3 A), and broken-out STM32 GPIO (H4/H5) +
  SWD. Comma-**panda firmware compatible**, so it works with **Cabana** — handy
  for the blocker-#1 capture without any custom firmware. 3 buses map to:
  ADAS side, chassis side, and a third that taps **V-CAN** to read openpilot's
  0x2B0/0x1C3 commands. There is no spare/free panda bus on the comma's Nissan A harness
  (all three of its buses are used), so the command rides V-CAN — the bus the
  comma is already on for steering. The interceptor only needs the third CAN to
  *listen* there; it never puts the comma on Chassis CAN, so a comma fault can't reach
  the brake bus even after fail-open. Interception is pure software MITM; see the
  relay note below.
- **OBD Power + splitter** — 12 V/OBD bench power and a bus splitter. Convenience.

Our core (`leaf_gw` + `gw_engine`) ports onto it via `backends/panda/`
(`gw_panda.c`, the interrupt-driven interceptor).

A 2-CAN board (e.g. an ESP32-C6) is deliberately **not** supported as the
interceptor: its two controllers are both consumed by the Chassis CAN cut (ADAS side
+ chassis side), leaving none to tap V-CAN for the command — so the command
would have to ride a Chassis CAN segment, putting the comma electrically on the
brake bus. A third CAN (to tap V-CAN) is the requirement, not a nicety.

## Building it on a comma car harness (no cuts to the car)

comma's Nissan A harness already splits Chassis CAN in two. Its car-harness
cable plugs in between the car's loom and the ADAS unit, and it brings the
ADAS-side and car-side halves of Chassis CAN out on **separate** wire pairs to
the 18-pin harness-box connector; the box just joins them inside. That join is
where the gateway goes. So the build is a modified **car-harness cable** (a
spare one, e.g. without a box), used with a stock harness box and comma. The
car's loom and the ADAS connector are never cut, and swapping the stock cable
back undoes everything.

Pins, from comma's open [Nissan A harness](https://github.com/commaai/hardware/blob/master/harness/v3/Nissan_A_Harness.pdf)
and [box pinout](https://github.com/commaai/hardware/blob/master/harness/v3/open_pinout.pdf)
drawings (they match the 2018 ESM):

| signal | ADAS / car connector pin | harness wire | 18-pin box pin |
|---|---|---|---|
| V-CAN, ADAS side (panda bus 2) | ADAS 1 / 2 | CAN2_H orange / CAN2_L green | 16 / 18 |
| V-CAN, car side (panda bus 0) | car 1 / 2 | CAN0_H orange / CAN0_L green | 4 / 6 |
| **Chassis CAN, ADAS side** | ADAS 8 / 9 | CAN1_H pink / CAN1_L blue | **9 / 11** |
| **Chassis CAN, car side** | car 8 / 9 | CAN1_H pink / CAN1_L blue | **8 / 7** |
| IGN | 12 | brown | 2, 14 |
| GND | 5 | black | 1, 17 |
| pass-through (ITS-CAN on 6/7, etc.) | 6, 7, 10, 11, 13, 16–18, 21–24 | PT1–PT12 | — |

The Nissan A harness has no 12 V wire; power the gateway from IGN.

### Build

1. **Meter an uncut reference harness first** (see *Before cutting* below). The
   table above comes from comma's drawings; confirm it on the real cable.
2. On the donor cable, take the two CAN1 pairs **off** the 18-pin connector:
   - ADAS-side pair (pink/blue from the ADAS connector, box pins 9/11) →
     gateway **CAN1**.
   - car-side pair (pink/blue from the car connector, box pins 8/7) → gateway
     **CAN2**, and also on to box pins **8/7**, so the comma's bus 1 still sees
     Chassis CAN as the car receives it (that's what the follow check reads).
     Leave box pins 9/11 unconnected.
3. **NC fail-open relay** across the break: bridges the ADAS-side pair to the
   car-side pair (H↔H, L↔L) when unpowered. The firmware energizes it to open
   the bypass only once it's running (`relay_engage`), so power loss, reset or a
   crash puts Chassis CAN back to stock.
4. **V-CAN tap:** CAN2 orange/green (box pins 16/18), in parallel, to gateway
   **CAN3**. That's the segment openpilot sends `0x2B0`/`0x1C3` on and where
   the gateway's `0x5FF` heartbeat reaches the comma.
5. **Power:** IGN + GND through an inline fuse. 26 AWG harness wire is fine for
   the Ocelot's draw.
6. **Termination** (measure, don't guess). Before the break, Chassis CAN H–L
   reads ~60 Ω with the car off. After the break each segment needs its own two
   120 Ω ends: measure each half, and enable the Ocelot's 120 Ω on whichever
   gateway port lacks one so each segment reads ~60 Ω again. The harness box's
   loopback jumpers (pins 3–5, 13–15) only cover bus 0 and bus 2.
7. Twisted pair throughout, short stubs, heat-shrink and strain relief.

### Before cutting

On the uncut reference harness, with a meter in continuity mode:
- ADAS pins 8/9 reach box pins 9/11; car-connector pins 8/9 reach box 8/7.
- Plugged into a harness box, every ADAS pin is continuous to the same car pin.
- Chassis CAN H–L resistance on each connector side, for the termination plan.

If anything differs from the table, stop and fix the table first.

### Alternative: a second harness box instead of the Ocelot's relay

A harness box's relay joins its two sides by default and opens only under
software control, which is the fail-open behaviour the gateway needs. Wired to
the two Chassis CAN halves instead of V-CAN, a second box plus a second
panda-class device on its OBD-C port could replace the Ocelot and NC relay. The
gateway firmware would need porting from the Ocelot (`gw_panda.c`) to that
device; not done.

## The fail-open relay (mandatory before any on-car use)

No off-the-shelf interceptor ships one — Ocelot included (BOM: F413 + 3×TJA1042
+ LDO, no relay). On reset/brown-out/crash a hard-MITM board **stops** the bus;
a brake bus must instead fall back to stock. So add a **normally-closed relay**
on the Chassis CAN cut that:
- connects ADAS ↔ chassis directly when de-energized (power loss / reset), and
- is held open (MCU in circuit) only while powered, healthy, and watchdog-fed.

Sources:
- **RetroPilot OSHW Relay** ($40, often out of stock) — the openpilot harness
  relay. Open design: https://github.com/lukasloetkolben/OpenpilotHardware .
  Built for the comma harness (SBU-driven, one bus); confirm you can drive it
  from your own GPIO and place it on Chassis CAN, or build/adapt from the files.
- Or a generic automotive **NC** relay / dual-SPDT, driven by an Ocelot GPIO
  (H4/H5) or the IGN_OUT rail, gated by the watchdog.

## Phase-0 validation (no interceptor board)

- Read-only, no cut: you need no board of this project at all. A stock comma on
  the Nissan A harness already hears Chassis CAN on panda bus 1, so a route
  opened in Cabana (or a USB-CAN adapter, or SocketCAN `candump`) gives you
  `0x2B0`/`0x1C3`; check the layouts with `tools/leaf_iccan_check.py`.

## Skip (for the Leaf)

- **comma-pedal** — fits Toyota/Honda/GM/VW/Tesla only; no Nissan harness.
- **standalone panda** — the comma four already contains one, and Ocelot is
  panda-compatible. (Only worth it for the second-harness-box alternative above.)

## End state for a shippable product

A small PCB that integrates the relay as a first-class feature: an Ocelot-style
STM32 (three CAN) + three transceivers + the NC bypass relay + 12 V reg +
automotive connector. Essentially an Ocelot variant with fail-open designed in,
keeping a third CAN to tap V-CAN for the command, so the comma stays off Chassis CAN.
