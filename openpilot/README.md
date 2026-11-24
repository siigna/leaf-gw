# openpilot side — Nissan Leaf longitudinal via the gateway

openpilot already does **lateral** on the Leaf. This adds **longitudinal**
(gas/brake) the opendbc-idiomatic way: the `car/nissan` port emits the car's
**real** ADAS frames — `0x2B0` (propulsion/regen) and `0x1C3` (friction brake) —
bounded by the standard panda longitudinal safety. It does **not** silence the
stock ADAS ECU (so AEB stays live) and does **not** spoof cruise buttons.

The twist vs a normal port: those frames go out on the bus the comma can reach
(**V-CAN**, panda bus 2), not their native Chassis CAN. The inline `leaf-gw` gateway
reads them off V-CAN, re-emits them onto Chassis CAN with the stock rolling counter,
and yields to a stronger stock request (magnitude arbitration). openpilot
doesn't know the gateway exists — to it, this is just a longitudinal port.

So there is **no custom command frame** anymore; openpilot sends the real frames
and panda bounds them like any other car (`longitudinal_gas_checks` /
`longitudinal_brake_checks` + `LongitudinalLimits`).

## Files

- **`leaf_gw_long.py`** — dependency-free spec of the mapping + the two packers
  (`gateway_longitudinal`, `pack_accel`, `pack_brake`), mirroring what the patch
  puts in `car/nissan`. StarPilot's 2025-SV-Plus calibration.
- **`test_leaf_gw_long.py`** — standalone test: the accel mapping, and a
  pack→decode round-trip whose decoders mirror the firmware core (`leaf_gw.c`),
  proving the frames openpilot emits are valid and gateway-readable (checksum,
  inverse-copy, command/pressure). `python3 test_leaf_gw_long.py`.
- **`nissan-longitudinal.patch`** — the opendbc car port:
  - `nissancan.py`: `create_accel_command` / `create_brake_command` (real
    `0x2B0`/`0x1C3`, emitted on `LEAF_LONG_BUS`).
  - `carcontroller.py`: `actuators.accel → raw_accel / brake_pressure`, send both.
  - `interface.py`: enable Leaf long, accel limits, the LONG safety flag. **No
    ECU takeover in `init()`.**
  - `values.py`: `CarControllerParams` longitudinal constants + `NissanSafetyFlags.LONG_CONTROL`.
- **`nissan-safety-longitudinal.patch`** — panda safety: a LONG flag gates a TX
  allowlist that includes `0x2B0`/`0x1C3` on bus 2, bounded with the shared
  `longitudinal_gas_checks` / `longitudinal_brake_checks` (via `NISSAN_LONG_LIMITS`)
  and `get_longitudinal_allowed()` (which also blocks when the driver presses the
  accelerator). Adds the `TestNissanLeafSafety` longitudinal tests.

## Apply

```
cd opendbc
cp /path/to/leaf_gw_long.py test_leaf_gw_long.py opendbc/car/nissan/   # optional, for its test
git apply /path/to/nissan-longitudinal.patch
git apply /path/to/nissan-safety-longitudinal.patch
python3 opendbc/car/nissan/test_leaf_gw_long.py
python3 -m pytest opendbc/car/tests/test_car_interfaces.py -k nissan -q
python3 -m pytest opendbc/safety/tests/test_nissan.py -q
```

Verified against opendbc `c55bd39e` (master, 2026-11-22): the standalone test
passes, all five nissan interfaces (incl. the fuzzed Leaf longitudinal
`CarController.update()`) pass, and `pytest test_nissan.py` → 103 passed / 15
skipped.

## The bus / frames (must match the firmware)

openpilot emits `0x2B0` and `0x1C3` on `LEAF_LONG_BUS` (V-CAN, panda bus 2 — the
segment is a bench check). The gateway reads them on CAN3, re-stamps the stock
counter/checksum, and substitutes onto Chassis CAN. Because the gateway re-encodes,
openpilot's own counter on these frames doesn't matter.

## Still gating on-car use

- Blocker #1: the `0x2B0`/`0x1C3` layouts on a real 2018–2023 ZE1 (validate with
  `tools/leaf_iccan_check.py`).
- Which V-CAN segment is panda bus 2 — confirm at the bench.
