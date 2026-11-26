# sunnypilot port of the Leaf longitudinal patches

The `../nissan-*.patch` files target upstream commaai/opendbc. These two target
**sunnypilot/opendbc `11c61f3e`** (master, "HKG: Car Port for Kia Carnival 2027").
They produce the same frames, safety bounds, gateway heartbeat gate and follow check as upstream.
`nissancan` packs byte-identical frames to `../leaf_gw_long.py`. That was checked
over T -16..4111 (to exercise the clip), every pressure, frame counter and flag
combination (148480 cases).

## Apply

```
cd opendbc                                   # sunnypilot fork, at 11c61f3e
git apply /path/to/sunnypilot/nissan-longitudinal.patch
git apply /path/to/sunnypilot/nissan-safety-longitudinal.patch   # its test needs the first patch
cp /path/to/leaf_gw_long.py /path/to/test_leaf_gw_long.py opendbc/car/nissan/   # optional
```

To check both patches from scratch:
`nix develop .#openpilot --command openpilot/check-forks.sh sunnypilot`. It applies
them to a fresh worktree at the pin and runs the suites; the result is PASS.

## Frames and engagement

- **`0x2B0` layout** (from SHIOKAZE's data, verified on 38 cars). The frame
  carries a 12-bit value `T = (b2 << 4) | (b1 & 0xF)`, with its inverted copy in
  `b1_hi:b0`. **Higher T means more deceleration.**
  - Byte 7 is `aux<<2 | (~aux & 3)`. aux is 2 only for the brake marker, else 0.
  - The accel to T curve is linear interpolation over
    `ACCEL_BP = [-0.78 … 0.79]` and `T_BP = [2784 … 2272]`. It is the median of
    37 stock Leafs and is **provisional** until bench-tested.
  - Below `PROPILOT_ACCEL_MIN` (-0.78 m/s^2), openpilot sends the stock
    friction-brake marker T 3415 (`a827d5ac5b000e09`). The 0x1C3 pressure is then
    `round((PROPILOT_ACCEL_MIN - accel) * 264)`; that gain is StarPilot's and is
    unverified.
  - Idle is T 2595 (`dc53a2ac1b000e03`).
  - Panda limits: T 2272..3415, inactive 2595, brake max 659. The shared
    helper's "gas" here is just the bounded T range.
- **Gateway heartbeat.** The gateway sends `0x5FF` `LEAF_GW_HEARTBEAT` at 50 Hz on
  bus 2 (`LEAF_LONG_BUS`). The car side offers alpha longitudinal only when the
  fingerprint saw `0x5FF` on bus 2. In LONG mode, panda adds `0x5FF` on bus 2 to
  its rx checks, so a missing or silent gateway invalidates them and control
  stops. The message is in `generator/nissan/nissan_leaf_2018.dbc`, the same as
  upstream.
- **Follow check (0x180).** `0x180` `PROPULSION_FEEDBACK` (in the DBC) reports
  the T the car is acting on, about 160 ms after the request:
  `D ~= -0.796 * T + 2067`.
  - **Gate.** Longitudinal is offered only when 0x180 is in the fingerprint on
    panda bus 0 (Leaf, Nissan A harness) or bus 1 (Leaf IC). The heartbeat on bus
    2 is still required as well.
  - **CarState.** Reads `D`, from the bus 0 parser for the Leaf and the bus 1
    parser for the Leaf IC. A frame unchanged for more than 5 updates counts as
    stale and is ignored. `leaf_feedback = (2067.1 - D) / 0.796`, and
    `ret.accFaulted` (the standard CarState field) mirrors the controller's result.
  - **CarController.** `FollowMonitor` is time-based: LAG 0.16 s, TOL 60,
    WINDOW 1.0 s.
    - It keeps a history of `(time, T)`. `update()` takes `now = now_nanos * 1e-9`,
      so it behaves the same at any controller rate. With no timestamp
      (`now_nanos` None) it skips the check and returns False instead of raising.
    - It is the same logic as `leaf_gw_long.FollowMonitor`; a randomized
      comparison with mixed time steps (120000 calls) found them identical.
    - It faults when the car slows less than asked (`T sent 0.16 s ago -
      feedback > 60`) for 1 s straight.
    - It does not evaluate before 0.16 s of history exists, while the brake
      marker is in the history, below 2 m/s, with gas or brake pressed, or
      without feedback.
    - Once faulted it stays faulted until longitudinal goes inactive. Slowing
      more than asked is allowed, since that is stock winning the arbitration.
- **Engagement.** `pcmCruise` stays True and `autoResumeSng` stays False, as in
  upstream and following the Toyota / Honda Nidec precedent:
  - The driver engages stock ProPILOT ICC, which puts `0x30f` in
    `pcm_cruise_check`.
  - That one cruise state gates both openpilot and panda.
  - openpilot then supplies the accel.

  With `pcmCruise` False, openpilot would cancel the very cruise state panda
  depends on (controlsd:
  `cancel = CS.cruiseState.enabled and (not CC.enabled or not CP.pcmCruise)`).

## Tests

Run in `nix develop .#openpilot` with `PYTHONPATH=<opendbc root>`.

| suite | before (11c61f3e) | after |
|---|---|---|
| `python3 opendbc/car/nissan/test_leaf_gw_long.py` | n/a | passes |
| `pytest opendbc/sunnypilot/car/nissan/test_nissan.py` (new) | n/a | 11 passed, 38 subtests |
| `pytest opendbc/car/tests/test_car_interfaces.py -k nissan` | 5 passed | 5 passed |
| `pytest opendbc/safety/tests/test_nissan.py` | 171 passed, 27 skipped | 235 passed, 36 skipped |
| `pytest opendbc/safety/tests -k wrong_safety_mode` (all brands) | 132 passed, 37 skipped | 133 passed, 37 skipped |
| `pytest opendbc/can/tests` (DBC touched) | — | 49 passed |

Nothing failed before the patches. Two checks show the new tests catch real
failures:
- With the ICBM guard reverted, `test_icbm_buttons` fails for both Leafs with
  longitudinal on.
- With the follow monitor disabled, `test_faults_when_car_slows_less_than_asked`
  and `test_timing_is_rate_independent` fail for both Leafs.

MISRA: no new violations (cppcheck 2.21.0).

## How it differs from upstream

- **Safety API.** Uses sunnypilot's globals and the shared helpers it already has
  (`longitudinal_gas_checks`, `longitudinal_brake_checks`, `LongitudinalLimits`,
  `get_longitudinal_allowed()` = `controls_allowed && !gas_pressed_prev`).
- **Flag gating.** `NissanSafetyFlags.LONG_CONTROL = 2` goes in `safetyParam`, as
  upstream does. It only takes effect together with sunnypilot's
  `NissanSafetyFlagsSP.LEAF` (in `current_safety_param_sp`); without LEAF it is
  ignored.
- **TX list.** LONG selects a new `NISSAN_TX_MSGS_LEAF_LONG`: sunnypilot's Leaf
  list (with `0x239` CRUISE_THROTTLE on bus 2, not upstream's `0x20b`/`0x280`)
  plus `0x2b0` and `0x1c3` on bus 2.
- **RX checks.** LONG uses `nissan_leaf_long_rx_checks` =
  `NISSAN_COMMON_RX_CHECKS` + the heartbeat. Non-LONG modes are unchanged.
- **Car side.** Same mapping, packers and heartbeat gate as upstream, written
  against `update(CC, CC_SP, CS, now_nanos)`; `get_pid_accel_limits` takes
  `CP_SP`. There is no ECU takeover in `init()` and no button spoofing for speed.
- **ICBM.** `intelligentCruiseButtonManagementAvailable` is False when openpilot
  longitudinal is on. `icbm.py` also ignores `sendButton` in that case, so no
  SET/RES press can be spoofed even if a request gets through. The `0x239`
  passthrough and cancel still run. Nothing changes when longitudinal is off,
  including when the heartbeat is missing.
- **Test harness.** sunnypilot's cffi exposes only functions, not
  `safety_a.state`. So `libsafety/safety.c` gains `get_rx_checks_len()` and
  `get_rx_check_msg_seen(i)` for the heartbeat test.
- **Safety tests.** The upstream longitudinal tests, including
  `test_leaf_stock_frames` and `test_leaf_gateway_heartbeat_required`, are in a
  new `TestNissanLeafLongSafety` subclass. The existing `TestNissanLeafSafety`
  keeps covering stock sunnypilot Leaf behaviour. One more test checks that LONG
  without LEAF opens nothing. The new class is added to the Nissan exception list
  in `common.py`'s `test_tx_hook_on_wrong_safety_mode`.
- **Car tests.** The new `opendbc/sunnypilot/car/nissan/test_nissan.py` covers:
  - the params for every Nissan with alpha_long on and off: `pcmCruise` True,
    `autoResumeSng` False, LONG flag and ICBM availability;
  - the heartbeat gate (absent, bus 0, bus 1);
  - the 0x180 gate (absent, or on the other harness's bus);
  - the golden stock `0x2B0` frames (2304, 2595 and 3415);
  - direct CarController runs with long on: accel 0 gives T 2528 with no friction
    brake; accel -2 gives the brake marker with pressure 322; both go out on bus 2;
  - no long frames without the toggle;
  - the ICBM guard;
  - the follow check end to end, through the real CarInterface fed
    `WHEEL_SPEEDS_*` and `PROPULSION_FEEDBACK` at 10 m/s, for both Leafs. It
    faults about 1.2 s after the car starts slowing less than asked, and stays
    quiet when the car follows or slows more;
  - a missing clock (`update(..., now=None)`) returns False and does not raise;
  - rate independence: the first fault comes 1.1–1.3 s in, with controller
    steps of both 100 Hz and 50 Hz.
