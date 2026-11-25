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

## Gateway heartbeat

The gateway sends `0x5FF` on its V-CAN port at 50 Hz (`'L' 'G' 'W'`, version,
status, counter, checksum; `LEAF_GW_HEARTBEAT` in the Leaf DBC). Two independent
gates use it:

- `interface.py`: `alphaLongitudinalAvailable` only if the heartbeat is in the
  fingerprint on `LEAF_LONG_BUS`. No gateway at startup → no longitudinal toggle.
- panda (`nissan.h`): in LONG mode the heartbeat is an rx check. If it stops for
  ~1 s, the rx checks go invalid and `controls_allowed` drops.

## Engagement

`pcmCruise` stays True, as on Toyota and Honda Nidec openpilot longitudinal: you
engage stock ProPILOT (ICC) as usual, panda keys `controls_allowed` off its cruise
state (`0x30f`), and openpilot supplies the acceleration. With `pcmCruise = False`
openpilot would cancel the stock cruise (`controlsd`: cancel when cruise is on and
not `pcmCruise`) that panda needs, so it could never engage. Stock ICC keeps
sending its own requests and the gateway arbitrates. At a stop, stock ICC's
brake hold wins, so `autoResumeSng` stays off; resume with the stock button.
`opendbc/car/nissan/tests/test_leaf_gw.py` (in the patch) pins this.

## Files

- **`leaf_gw_long.py`** — dependency-free spec of the mapping + the two packers
  (`gateway_longitudinal`, `pack_accel`, `pack_brake`), mirroring what the patch
  puts in `car/nissan`. 0x2B0 is T (higher = more decel); the accel→T curve is the 37-car fleet fit, provisional.
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

Verified against opendbc `341fb3d9` (master, 2026-11-24): the standalone test
passes, all five nissan interfaces (incl. the fuzzed Leaf longitudinal
`CarController.update()`) pass, and `pytest test_nissan.py` → 103 passed / 15
skipped.

## Forks (sunnypilot, StarPilot, RetroPilot, FlowPilot)

The same design, ported per fork. Each fork's nissan code has diverged enough that
the upstream patches don't apply there:

| fork | base | patches |
|---|---|---|
| openpilot (comma) | `commaai/opendbc` master `341fb3d9` | `*.patch` here |
| sunnypilot | `sunnypilot/opendbc` master `11c61f3e` | [`sunnypilot/`](sunnypilot/README.md) |
| StarPilot | `StarPilotHQ/StarPilot` `StarPilot` `0b2061d` (vendored `opendbc_repo/`) | [`starpilot/`](starpilot/README.md) |
| RetroPilot | `RetroPilot/openpilot` `c2` `b9a942ef` (openpilot 0.8.13 base; panda/opendbc submodules) | [`retropilot/`](retropilot/README.md) — `c2` hard-codes the RetroPilot retrofit fingerprint, so the Leaf isn't selected until that's reverted |
| FlowPilot | `jagheterfredrik/flowpilot` `master` `9ea918ea` (openpilot on Android; the maintained fork, panda/opendbc vendored) | [`flowpilot/`](flowpilot/README.md) |

RetroPilot's tree predates the alpha-longitudinal toggle and panda's shared
longitudinal helpers, so it opts in with its own `DisableRadar` param and writes
the same bounds out by hand. RetroPilot and FlowPilot each ship a `fork.sh` that
sets up the tree, its pinned nix env and its tests.

`check-forks.sh` applies each set to a fresh worktree at its pin and runs the
nissan suites; `--latest` tries each fork's branch head instead, to catch drift
before bumping a pin:

```
nix develop .#openpilot --command openpilot/check-forks.sh            # all, at pins
nix develop .#openpilot --command openpilot/check-forks.sh --latest sunnypilot
```

## The bus / frames (must match the firmware)

openpilot emits `0x2B0` and `0x1C3` on `LEAF_LONG_BUS` (V-CAN, panda bus 2 — the
segment is a bench check). The gateway reads them on CAN3, re-stamps the stock
counter/checksum, and substitutes onto Chassis CAN. Because the gateway re-encodes,
openpilot's own counter on these frames doesn't matter.

## Still gating on-car use

- Blocker #1: the `0x2B0`/`0x1C3` layouts on a real 2018–2023 ZE1 (validate with
  `tools/leaf_iccan_check.py`).
- Which V-CAN segment is panda bus 2 — confirm at the bench.
