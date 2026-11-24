# Attribution

This project is MIT-licensed (see LICENSE). It reuses knowledge and designs from
the following; grateful credit to their authors.

## CAN message formats (0x2B0, 0x1C3) and the 0x1C3 checksum
Reimplemented in C in `leaf_gw.c` from the Nissan Leaf decode in **openpilot /
opendbc** and the **StarPilot** fork (firestar5683 / StarPilotHQ), both MIT.
Those formats come from StarPilot's **disabled, firmware-pinned** 2025 Leaf SV
Plus longitudinal code (one developer's experiment, gated off by
`ALPHA_LONG_ENABLED = False`, not a shipped feature) — so even on a 2025 they are
lightly proven, and on a 2018–2023 ZE1 entirely unverified. A starting point, not
ground truth.

The openpilot-side longitudinal calibration in `openpilot/leaf_gw_long.py`
(the accel→command mapping, brake gain, and the inactive/brake raw command
values) is StarPilot's as well, and the openpilot patch emits the same real
0x2B0/0x1C3 frames StarPilot does — the difference is it sends them to the
gateway's bus (V-CAN) and keeps the stock ADAS ECU live, rather than silencing
it.
- https://github.com/commaai/opendbc  (MIT)
- https://github.com/StarPilotHQ/StarPilot

## Gateway design (reference only — no code copied)
- **comma Smart DSU / panda** (MIT): inline intercept + substitute, and the
  "inject only when stock isn't asserting" safety guard. The panda backend
  (`backends/panda/gw_panda.c`) also follows the interrupt-driven MITM structure
  of the **RetroPilot ocelot `smart_dsu`** core (CAN RX IRQ → decide → `can_send`)
  and, at build time, reuses that tree's cut-down `can.h` and startup/signing.
  No ocelot source is vendored in this repo; the backend is written against its
  API and copied into an ocelot firmware tree to build (see that backend's README).
  https://github.com/commaai/panda , https://github.com/RetroPilot/ocelot
- **Dala's Nissan-LEAF-Battery-Upgrade** 2-port CAN bridge: the passthrough-by-
  default, rewrite-selected-IDs, recompute-checksum structure on Leaf buses.
  https://github.com/dalathegreat/Nissan-LEAF-Battery-Upgrade
  (Independent reimplementation; check that repo's own license before copying
  any of its code.)

## Vehicle architecture facts
CAN bus topology, the ADAS connector pinout, and the shared single brake path
were taken from the Nissan factory service manual (2018 LEAF ESM/eWD), accessed
under a paid subscription. No Nissan text, diagrams, or data files are
reproduced in this repository — only independently-stated facts.

"Nissan", "LEAF" and "ProPILOT" are trademarks of Nissan. This project is not
affiliated with, endorsed by, or certified by Nissan or comma.ai.
