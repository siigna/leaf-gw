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
would have to ride an Chassis CAN segment, putting the comma electrically on the
brake bus. A third CAN (to tap V-CAN) is the requirement, not a nicety.

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

- Read-only, no cut: you need no board of this project at all. Capture Chassis CAN
  with a panda + Cabana, a USB-CAN adapter, or SocketCAN `candump`, and check
  the layouts with `tools/leaf_iccan_check.py`.

## Skip (for the Leaf)

- **comma-pedal** — fits Toyota/Honda/GM/VW/Tesla only; no Nissan harness.
- **standalone panda** — the comma four already contains one, and Ocelot is
  panda-compatible.

## End state for a shippable product

A small PCB that integrates the relay as a first-class feature: an Ocelot-style
STM32 (three CAN) + three transceivers + the NC bypass relay + 12 V reg +
automotive connector. Essentially an Ocelot variant with fail-open designed in,
keeping a third CAN to tap V-CAN for the command, so the comma stays off Chassis CAN.
