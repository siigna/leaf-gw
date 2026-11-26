# leaf-gw gateway mode for StarPilot

`starpilot-leaf-gw-long.patch` adds a **leaf-gw gateway mode** for Nissan Leaf
longitudinal to StarPilot. It also corrects the `0x2B0` encoding that StarPilot's
existing 2025-SV-Plus ADAS-silencing mode uses (see below). Apart from that, the
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

`nix develop .#openpilot --command openpilot/check-forks.sh starpilot` applies the
patch to a fresh worktree at the pin, runs every suite, and prints PASS.

## What gateway mode is

openpilot sends the Leaf's real `0x2B0` (propulsion/regen) and `0x1C3` (friction
brake) frames on **panda bus 2**. The inline leaf-gw gateway reads them there and
relays them onto Chassis CAN. The stock ADAS ECU is never taken over, so stock AEB
keeps working.

| | silencing mode (existing) | gateway mode (new) |
|---|---|---|
| enabled when | `LEAF_2025_SV_PLUS_ALPHA_LONG_ENABLED` (False) **and** `NISSAN_LEAF` **and** camera fw `6WK2CDB` | alpha-long toggle on `NISSAN_LEAF` / `NISSAN_LEAF_IC`, any firmware, **and** the gateway heartbeat `0x5FF` in `fingerprint[2]` **and** `0x180` in `fingerprint[0]` (Leaf) / `fingerprint[1]` (Leaf IC) |
| safety flag | `LONG_CONTROL = 2` | `LEAF_GW_LONG = 4` |
| frames | `0x2B0`/`0x1C3` on bus 1 | `0x2B0`/`0x1C3` on bus 2 |
| ADAS ECU | KWP `10 C0` + `28 02`, tester present `0x707`, silence check, restore on deinit | untouched: no KWP, no `0x707`, no silence check |
| engagement | openpilot reads SET/RES itself (`pcmCruise = False`), panda enables on button release | stock ProPILOT (`pcmCruise = True`), panda follows `CRUISE_STATE 0x30f`, like Toyota / Honda Nidec openpilot long |
| panda RX checks | reduced set (no `0x30f`) | stock set **plus** `0x5FF` on bus 2 at 50 Hz. If the heartbeat stops, the RX checks go invalid and `controls_allowed` drops |
| `autoResumeSng` | True | False (stock cruise owns resume) |
| follow check | none | `FollowMonitor` on `0x180`; a fault sets `accFaulted` |

**Precedence.** The car side picks silencing mode only when the silencing mode
itself is eligible. The heartbeat plays no part in that decision. Otherwise it
picks gateway mode, and only when the heartbeat is present. It never sets both
flags. If panda gets both flags, it runs silencing mode and ignores the gateway
flag. All of these rules are tested.

**Heartbeat.** The gateway sends `0x5FF` on bus 2 at 50 Hz. Its bytes are `'L' 'G' 'W'
0x01 status counter(4-bit) 0x00 checksum`, where checksum = `(0xFF + sum(bytes 0..6)) &
0xFF`. The patch adds `BO_ 1535 LEAF_GW_HEARTBEAT` to
`dbc/generator/nissan/nissan_leaf_2018.dbc` and to the vendored
`nissan_leaf_2018_generated.dbc`. Running `generator.py` reproduces the generated
file byte for byte.

**Follow check (gateway mode only).** This mirrors upstream `FollowMonitor`. `0x180`
(`PROPULSION_FEEDBACK.D`, signed 12-bit) follows the T the car is acting on about 160 ms
later, as `D ≈ -0.796·T + 2067` (SHIOKAZE, 37 cars).

- **Reading it.** `carstate.py` reads `D` from bus 0 on `NISSAN_LEAF` and from bus 1
  on `NISSAN_LEAF_IC`. It converts it to `leaf_feedback = (2067.1 - D) / 0.796`. The
  value is `None` when the frame is missing or its timestamp hasn't changed for more
  than 5 updates. `ret.accFaulted` is set from the controller's result.
- **The check.** It is time-based, so it behaves the same at any controller rate.
  `carcontroller.py` passes `now_nanos * 1e-9` and keeps the T it sent with timestamps,
  dropping all but the newest sample at or before `now - 0.16 s`. It counts the car as
  behind when that T minus `leaf_feedback` is above 60. Once the car has been behind
  for 1.0 s without a break, it faults.
- **When it runs.** Only while `vEgo > 2` with neither pedal pressed, while feedback is
  present, once 0.16 s of history exists, and while the brake marker is not in that
  history. Otherwise the timer resets.
- **Clearing.** A fault latches until long goes inactive.
- **No clock.** If `now_nanos` is `None`, the check is skipped and resets. It never crashes
  the controller.
- **One-sided.** The car slowing *more* than asked is allowed: that is stock winning
  the arbitration.
- **Scope.** Silencing mode has no follow check and doesn't need `0x180`.

The patch adds `BO_ 384 PROPULSION_FEEDBACK` (`SG_ D : 23|12@0-`) and its `CM_` to both
DBC files. The generated file still matches the generator byte for byte.

## Correction to StarPilot's existing alpha: what 0x2B0 encodes

StarPilot treats `0x2B0` as a linear accel value: 2048 counts per m/s², 6144 = 0,
plus 2 "fraction" bits in byte 7. SHIOKAZE's data, checked on 38 cars, shows the
field is actually a 12-bit **T, where higher T means more deceleration**:

```
T = (data[2] << 4) | (data[1] & 0xF)            inverse = ((data[1] >> 4) << 8) | data[0] == ~T & 0xFFF
byte0 = ~T & 0xFF   byte1 = (~T >> 8) << 4 | (T & 0xF)   byte2 = T >> 4
byte3 0xAC   byte4 0x5B / 0x1B   byte5 0   byte6 counter << 4 | 0xE
byte7 = aux << 2 | (~aux & 3), with aux = 2 only for the brake marker (T == 3415), else 0
```

Under this reading StarPilot's map makes no sense. Its "0 m/s²" command (6144)
lands at T 2304, which is about +0.6 m/s². The fix is made once, in the shared
packer, the shared accel map in `carcontroller.py` and the shared panda decode, so
it covers **both** modes. Silencing mode stays disabled and firmware-pinned, but if
someone turns it on it now sends the stock encoding.

| | was (StarPilot) | now (mirrors `../leaf_gw_long.py`) |
|---|---|---|
| map | `round(accel * 2048 + 6144)`, with accel clipped to -1..+1 | `round(np.interp(accel, ACCEL_BP, T_BP))` |
| `ACCEL_BP` / `T_BP` | — | `[-0.78, -0.45, -0.11, -0.04, 0.0, 0.05, 0.09, 0.59, 0.79]` / `[2784, 2720, 2656, 2592, 2528, 2464, 2400, 2336, 2272]` |
| `PROPILOT_ACCEL_MIN` | -1.0 | -0.78 (`ACCEL_BP[0]`) |
| `ACCEL_MAX` = `PROPILOT_ACCEL_MAX` | 2047/2048 | 0.79 (`ACCEL_BP[-1]`) |
| inactive | 5320 | 2595 (stock idle `dc53a2ac1b000e03`) |
| brake marker | 2518 | 3415 (stock `a827d5ac5b000e09`) |
| brake pressure | `(-accel - 1) * 264` | `(PROPILOT_ACCEL_MIN - accel) * 264` |
| `PROPILOT_ACCEL_OFFSET` / `_SCALE` | 6144 / 2048 | removed |

The accel→T curve is the median of 37 stock Leafs' ICC logs, so it is
**provisional** until bench-tested. StarPilot's friction-brake gain is also
unverified.

**Panda, both modes.** These checks apply to silencing and gateway mode alike:
- T decode and the inverse check, as above.
- The aux self-check in byte 7, plus a new rule that aux is 2 only at the brake
  marker.
- The fixed bytes, unchanged.
- The command shape. An active frame must be T == 3415 or 2272..3071. An inactive
  frame must be T == 2595.
- `active && !get_longitudinal_allowed()` is a violation.
- `longitudinal_gas_checks(T)` with max 3415 / min 2272 / inactive 2595. This
  replaces StarPilot's `longitudinal_accel_checks` on the linear scale.

The brake limit stays at `max_brake = 659`.

### Golden vectors that changed

`test_nissancan.py` accel vectors (raw → expected bytes):

| before | after | change |
|---|---|---|
| `(5260, 0, False)` → `dc53a2ac1b000e03` | `(2595, …)` | label only (stock idle) |
| `(6144, 0, True)` → `ff6090ac5b000e03` | `(2304, …)` | label only (stock cruise frame) |
| `(4096, 0, True)` → `ff40b0ac5b000e03` | `(2816, …)` | label only |
| `(2398, 0, True)` → `a827d5ac5b000e09` | `(3415, …)` | label only (stock brake marker) |
| `(8191, 15, True)` → `007f8fac5b00fe0c` | `(2272, 15, True)` → `1f708eac5b00fe03` | replaced: the old frame has aux 3, which the packer never sends |

StarPilot's controller tests:
- accel 0 (`test_alpha_long_controller_sends_stock_shaped_commands_and_keepalive`):
  `ff6090ac5b000e03` → **`1f609eac5b000e03`** (T 2528).
- clamp (`test_alpha_long_controller_clamps_to_panda_accel_limit`, accel 5.0):
  `007f8fac5b000e0c` → **`1f708eac5b000e03`** (T 2272).
- friction blend at -2.0 m/s²: the pressure was 264 and is now **322**, because
  the blend now starts at -0.78. The 0x2B0 brake-marker frame is unchanged.
- the inactive frame is unchanged.

The same three new values apply to the gateway-mode copies of these tests.

Panda test literals:
- allowed: (4096, 6144, 8191, 2398) → (2272, 2528, 3071, 3415).
- rejected: (0, 2397, 2399, 4095, 8192, 0x3FFF) → (0, 2271, 3072, 3414, 3416, 4095).
- inactive: 5260 → 2595.
- engaged example: 6144 → 2528.

## Changes

- `values.py`: the new curve and constants, and `NissanSafetyFlags.LEAF_GW_LONG = 4`.
- `nissancan.py`:
  - The T packer.
  - `create_accel_command` / `create_brake_command` take a `bus` argument (default 1,
    so existing callers don't change).
  - Adds `LEAF_GW_LONG_BUS = 2`, `LEAF_GW_HEARTBEAT = 0x5FF` and `LEAF_FEEDBACK_ADDR = 0x180`.
- `carcontroller.py`:
  - The interp map and the new pressure formula.
  - `FollowMonitor`, fed with the T sent, in gateway mode only.
  - Leaf long covers both Leaf platforms.
  - Frames go on bus 2 in gateway mode, and the `0x707` keepalive goes out only in
    silencing mode.
  - The seatbelt-spoof cancel is now gated on `CP.pcmCruise`, so gateway mode can
    cancel stock cruise.
- `interface.py`:
  - Adds `is_leaf_gw_longitudinal(candidate, fingerprint, car_fw)` (the heartbeat
    and `0x180` gate) and `is_leaf_adas_silencing(CP)`.
  - `init`/`deinit` (the KWP takeover and its restore) now run only when the
    `LONG_CONTROL` flag is set.
  - Accel limits now cover `NISSAN_LEAF_IC` as well.
- `carstate.py`:
  - The SET/RES engage events now also require `not CP.pcmCruise`, so they only
    appear in silencing mode, as before.
  - In gateway mode, reads `0x180` as `leaf_feedback` and sets `accFaulted`.
- `safety/modes/nissan.h`:
  - The decode and bounds above.
  - Gateway mode uses its own TX list: base messages plus `0x2B0`/`0x1C3` on bus 2,
    without `0x707` and without bus 1.
  - Gateway mode has its own RX checks: the stock set plus `{0x5ff, 2, 8, 50U}`, with
    checksum, counter and quality ignored.
  - Like silencing mode, gateway mode only works in an `ALLOW_DEBUG` panda build.
- `dbc/`: `LEAF_GW_HEARTBEAT` and `PROPULSION_FEEDBACK`.
- Tests:
  - Car: the T layout over all 4096 values, clipping, a monotonic map with 0 → 2528,
    and stock golden frames. Also gateway params, the heartbeat gate (absent, or
    seen on bus 0 or 1 → no gateway mode), precedence, init/deinit never touching
    the ADAS, 200 controller frames on bus 2 with no `0x707`, `pcmCruise` True with
    long, no button engage, and cancel. The `0x180` gate and the follow check are
    covered under Tests.
  - Safety, in a new `TestNissanLeafGwLongSafety`: the heartbeat is required and
    accepted only on bus 2, losing it drops control, and the other modes don't need
    it. Also stock golden frames, full T and brake sweeps, aux only at the marker,
    bus 1 and `0x707` rejected, both-flags precedence, and StarPilot's frame-format
    tests replayed on bus 2.
  - `safety/tests/common.py` adds the new class to the existing Nissan exception
    list in `test_tx_hook_on_wrong_safety_mode`.

## Packer check

StarPilot's `create_accel_command` with `bus=2` produces the same bytes as
`../leaf_gw_long.py` `pack_accel` for every command from -100 to 4999 (so clipping
is covered too) × frame 0..31 × active. `create_brake_command` produces the same
bytes as `pack_brake` for every pressure 0..1023 × frame 0..15 × active ×
brake_mode. That is 391,936 frames in all.

Every constant matches: `ACCEL_MIN/MAX`, `ACCEL_BP`, `T_BP`, `PROPILOT_ACCEL_MIN/MAX`,
inactive, marker, `BRAKE_MAX` and `BRAKE_GAIN`. `np.interp` agrees with
`leaf_gw_long._interp` at every 0.001 m/s² step from -1 to +1.

## Tests

Run inside `nix develop .#openpilot`, from `opendbc_repo/`, with
`PYTHONPATH=opendbc_repo:<StarPilot root>`, after
`scons -Q opendbc/safety/tests/libsafety/libsafety.so`. `check-forks.sh` already
does all of this.

| suite | before (0b2061d) | after |
|---|---|---|
| `pytest opendbc/car/nissan/tests` | 29 passed | 81 passed |
| `pytest opendbc/car/tests/test_car_interfaces.py -k nissan` | 5 passed | 5 passed |
| `pytest opendbc/safety/tests/test_nissan.py` | 111 passed, 20 skipped | 152 passed, 25 skipped |
| `test_leaf_gw_long.py` | pass | pass |

`check-forks.sh starpilot` runs the safety and car-test directories together:
233 passed, 25 skipped, then 5 passed, then PASS. The 5 extra skips come from the
new safety class, which inherits the stock Leaf class's skipped tests.

MISRA: no new violations (cppcheck 2.18.3), checked both default and with -DALLOW_DEBUG.

Follow-check tests, all run through the real `CarInterface.update`/`apply`:
- The gate: 0x180 absent, or on the other harness's bus, for each Leaf.
- A fault when the car slows less than asked, on both Leaf and Leaf IC.
- No fault when the car follows, or slows more than asked.
- Skipped below 2 m/s, with no feedback, and while braking.
- The fault latches until long goes inactive.
- The fault fires 1.1-1.3 s in at both 100 Hz and 50 Hz controller steps (rate independence).

With the monitor disabled (`CS.gw_follow_fault = False`), both fault tests and the
rate-independence test fail
(`3 failed, 4 passed` for `-k follow`). The quiet and skip tests pass either way,
as they should.

## Open points

- The accel→T curve and the friction-brake gain are provisional (stock-log fit
  only). They need a bench or test-car check.
- Gateway TX entries use `check_relay = false`, as upstream leaf-gw does. This
  assumes the stock car never sends `0x2B0`/`0x1C3` on bus 2. Verify this at the bench.
- panda allows active T only as 3415 or 2272..3071. Upstream leaf-gw allows anything
  in 2272..3415. The car side never sends 2785..3414.
- panda accepts only byte 3 = `0xAC` (StarPilot's check). The gateway firmware also
  accepts other state values such as `0x8C` (Park).
- Heartbeat checksum and counter are ignored by panda, as in upstream.
- StarPilot's `selfdrive/` Leaf-long code is driven by `EcuDisableFailed`, a param
  that clears on manager start and that only the silencing `init()` writes. That code
  needs no change. `test_nissan_leaf_fallback.py` was not run because it needs a
  compiled `msgq`.
