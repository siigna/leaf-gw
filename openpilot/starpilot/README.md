# leaf-gw gateway mode for StarPilot

`starpilot-leaf-gw-long.patch` adds a **leaf-gw gateway mode** for Nissan Leaf
longitudinal to StarPilot. It also fixes a `0x2B0` packing bug in StarPilot's
existing 2025-SV-Plus ADAS-silencing mode (see below). Apart from that fix, the
silencing mode is left as it is.

- Base: `StarPilotHQ/StarPilot` branch `StarPilot`, commit `0b2061d`. opendbc is vendored
  at `opendbc_repo/`.
- Paths are rooted at the StarPilot repo root. Apply from that root. Running
  `git apply` from inside `opendbc_repo/` skips every file and reports nothing.

```
cd StarPilot
git apply --check /path/to/starpilot-leaf-gw-long.patch
git apply /path/to/starpilot-leaf-gw-long.patch
```

## What gateway mode is

openpilot sends the Leaf's real `0x2B0` (propulsion/regen) and `0x1C3` (friction
brake) frames on **panda bus 2**. The inline leaf-gw gateway reads them there and
relays them onto Chassis CAN. The stock ADAS ECU is never taken over, so stock AEB
keeps working.

| | silencing mode (existing) | gateway mode (new) |
|---|---|---|
| enabled when | `LEAF_2025_SV_PLUS_ALPHA_LONG_ENABLED` (False) **and** `NISSAN_LEAF` **and** camera fw `6WK2CDB` | alpha-long toggle on `NISSAN_LEAF` / `NISSAN_LEAF_IC`, any firmware, **and** the gateway heartbeat `0x5FF` in `fingerprint[2]` |
| safety flag | `LONG_CONTROL = 2` | `LEAF_GW_LONG = 4` |
| frames | `0x2B0`/`0x1C3` on bus 1 | `0x2B0`/`0x1C3` on bus 2 |
| ADAS ECU | KWP `10 C0` + `28 02`, tester present `0x707`, silence check, restore on deinit | untouched: no KWP, no `0x707`, no silence check |
| engagement | openpilot reads SET/RES itself (`pcmCruise = False`), panda enables on button release | stock ProPILOT (`pcmCruise = True`), panda follows `CRUISE_STATE 0x30f`, like Toyota / Honda Nidec openpilot long |
| panda RX checks | reduced set (no `0x30f`) | stock set **plus** `0x5FF` on bus 2 at 10 Hz. If the heartbeat stops, the RX checks go invalid and `controls_allowed` drops |
| `autoResumeSng` | True | False (stock cruise owns resume) |

**Precedence.** The car side picks silencing mode only when the silencing mode
itself is eligible. The heartbeat plays no part in that decision. Otherwise it
picks gateway mode, and only when the heartbeat is present. It never sets both
flags. If panda gets both flags, it runs silencing mode and ignores the gateway
flag. All of these rules are tested.

**Heartbeat.** The gateway sends `0x5FF` on bus 2 at 10 Hz. Its bytes are `'L' 'G' 'W'
0x01 status counter(4-bit) 0x00 checksum`, where checksum = `(0xFF + sum(bytes 0..6)) &
0xFF`. The patch adds `BO_ 1535 LEAF_GW_HEARTBEAT` to
`dbc/generator/nissan/nissan_leaf_2018.dbc` and to the vendored
`nissan_leaf_2018_generated.dbc`. Running `generator.py` reproduces the generated
file byte for byte.

## Bug fix to StarPilot's existing alpha: the 0x2B0 nibble order

StarPilot's `create_accel_command`, and its panda decode, swap two nibbles of the
12-bit value V and its inverse I = `~V & 0xFFF`. The correct layout was confirmed on
a stock ZE1 rlog (a public US `NISSAN_LEAF_IC` route, 24k frames):

```
byte0 = I & 0xFF
byte1 = (V >> 8) << 4 | (V & 0xF)
byte2 = (I >> 8) << 4 | ((V >> 4) & 0xF)
panda: raw = ((d1 >> 4) << 8) | ((d2 & 0xF) << 4) | (d1 & 0xF);  inverse = ((d2 >> 4) << 8) | d0
```

The fix is made once, in the shared packer and in the shared panda decode, so it
covers both modes.

StarPilot's constants were wrong for the same reason. The stock frames it copied
are byte-correct, but StarPilot decoded them with the swapped layout, so it read the
wrong numbers out of them:

| constant | was | now | stock frame (same bytes) |
|---|---|---|---|
| `PROPILOT_INACTIVE_RAW` | 5320 | **5260** | `dc53a2ac1b000e03` |
| `PROPILOT_BRAKE_RAW` | 2518 | **2398** | `a827d5ac5b000e09` |

The panda checks follow: inactive is now 5260, and an active frame must be raw 2398
or 4096..8191.

**Golden vectors.** None of StarPilot's existing golden **byte strings** changed. Each
one either has V_mid equal to V_lo (6144, 4096, 8191), or is a stock frame whose raw
value only gets relabelled. The **raw labels** in `test_nissancan.py` changed from
5320 to 5260 and from 2518 to 2398. In the panda tests, the literals 5320, 2518,
2517 and 2519 changed to 5260, 2398, 2397 and 2399. Under the old packer, raw 5320
would have produced `cd52a3…`, which is not the stock idle frame.

## Changes

- `values.py`: adds `NissanSafetyFlags.LEAF_GW_LONG = 4` and the corrected constants.
- `nissancan.py`:
  - The nibble fix.
  - `create_accel_command` / `create_brake_command` take a `bus` argument (default 1,
    so existing callers don't change).
  - Adds `LEAF_GW_LONG_BUS = 2` and `LEAF_GW_HEARTBEAT = 0x5FF`.
- `interface.py`:
  - Adds `is_leaf_gw_longitudinal(candidate, fingerprint, car_fw)` (the heartbeat gate)
    and `is_leaf_adas_silencing(CP)`.
  - `init`/`deinit` (the KWP takeover and its restore) now run only when the
    `LONG_CONTROL` flag is set.
  - Accel limits now cover `NISSAN_LEAF_IC` as well.
- `carcontroller.py`:
  - Leaf long covers both Leaf platforms.
  - Frames go on bus 2 in gateway mode, and the `0x707` keepalive goes out only in
    silencing mode.
  - The seatbelt-spoof cancel is now gated on `CP.pcmCruise`. That keeps the old
    result for stock and silencing mode, and lets gateway mode cancel stock cruise.
- `carstate.py`: the SET/RES engage events now also require `not CP.pcmCruise`, so
  they only appear in silencing mode, as before.
- `safety/modes/nissan.h`:
  - The nibble fix and the corrected constants.
  - Gateway mode uses its own TX list: base messages plus `0x2B0`/`0x1C3` on bus 2,
    without `0x707` and without bus 1.
  - Gateway mode has its own RX checks: the stock set plus `{0x5ff, 2, 8, 10U}`, with
    checksum, counter and quality ignored.
  - It keeps all of StarPilot's frame checks: inverse copy, fraction, fixed bytes,
    checksum, the active bit tied to pressure, and `get_longitudinal_allowed`.
  - It also runs the shared `longitudinal_gas_checks` with max 8191 / min 2398 /
    inactive 5260. The brake limit stays at `max_brake = 659`.
  - Like silencing mode, it only works in an `ALLOW_DEBUG` panda build.
- `dbc/`: the heartbeat message.
- Tests:
  - Car: gateway params, the heartbeat gate (absent, or seen on bus 0 or 1 → no
    gateway mode), precedence, init/deinit never touching the ADAS, 200 controller
    frames on bus 2 with no `0x707`, stock golden frames, and every-value nibble
    layout. `pcmCruise` is True with long, no button engage, and cancel works.
  - Safety, in a new `TestNissanLeafGwLongSafety`: the heartbeat is required and
    accepted only on bus 2, losing it drops control, and the other modes don't need
    it. Also stock golden frames, full gas/brake sweeps, bus 1 and `0x707` rejected,
    both-flags precedence, and StarPilot's frame-format tests replayed on bus 2.
  - `safety/tests/common.py` adds the new class to the existing Nissan exception
    list in `test_tx_hook_on_wrong_safety_mode`.

## Packer check

After the fix, StarPilot's `create_accel_command` / `create_brake_command` with
`bus=2` produce the same bytes as `../leaf_gw_long.py` `pack_accel` / `pack_brake`.
That was checked over every input: raw 0..16383 × frame 0..31 × active, and pressure
0..1023 × frame 0..15 × active × brake_mode, 1,114,112 frames in all. Every
mapping constant also matches.

## Tests

Run inside `nix develop .#openpilot`, from `opendbc_repo/`. Two things are needed:

- `PYTHONPATH=opendbc_repo:<StarPilot root>`. StarPilot's opendbc imports `cereal` and
  `openpilot.*` from the repo root.
- Build `libsafety.so` first with `scons -Q opendbc/safety/tests/libsafety/libsafety.so`.

| suite | before (0b2061d) | after |
|---|---|---|
| `pytest opendbc/car/nissan/tests` | 29 passed | 68 passed |
| `pytest opendbc/car/tests/test_car_interfaces.py -k nissan` | 5 passed | 5 passed |
| `pytest opendbc/safety/tests/test_nissan.py` | 111 passed, 20 skipped | 151 passed, 25 skipped |
| `test_leaf_gw_long.py` | pass | pass |

The new tests were also run against the unpatched code. With the test and DBC
files applied but no code changes, collection fails with 17 errors.

The 5 extra skips come from `TestNissanLeafGwLongSafety`. It inherits the stock
Leaf class's skipped `test_acc_buttons` and the common skipped tests. None of
StarPilot's existing car tests had to change their assertions. Without the
heartbeat, a Leaf still has no alpha long, exactly as those tests expect.

## Open points

- Gateway TX entries use `check_relay = false`, as upstream leaf-gw does. This
  assumes the stock car never sends `0x2B0`/`0x1C3` on bus 2. Verify this at the bench.
- For an active frame, panda allows raw 2398 or 4096..8191, which is StarPilot's
  command shape. Upstream leaf-gw allows anything in 2398..8191. The car side never
  sends 2399..4095.
- Heartbeat checksum and counter are ignored by panda, as in upstream.
- StarPilot's `selfdrive/` Leaf-long code (`card.py`, `controlsd.py`, `selfdrived.py`) is
  driven by `EcuDisableFailed`, a param that clears on manager start. Only the
  silencing `init()` writes it, so gateway mode never triggers it, and that code
  needs no change. `selfdrive/controls/tests/test_nissan_leaf_fallback.py` was not
  run because it needs a compiled `msgq`.
- MISRA/cppcheck was not run.
