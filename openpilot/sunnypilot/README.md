# sunnypilot port of the Leaf longitudinal patches

The `../nissan-*.patch` files target upstream commaai/opendbc. These two target
**sunnypilot/opendbc `11c61f3e`** (master, "HKG: Car Port for Kia Carnival 2027").
They produce the same frames, safety bounds and gateway heartbeat gate as upstream.
`nissancan` packs byte-identical frames to `../leaf_gw_long.py`. That was checked
over every command, pressure, frame counter and flag combination (278528 cases).

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

- **`0x2B0` layout** (verified on a stock ZE1 log). With the 12-bit value V and
  its inverse I = ~V & 0xFFF:
  - byte0 = I & 0xFF
  - byte1 = V_hi:V_lo
  - byte2 = I_hi:V_mid

  Two of the decoded values move as a result. Idle is 5260, the stock frame
  `dc53a2ac1b000e03`. The friction-brake marker is 2398, the stock frame
  `a827d5ac5b000e09`. Panda limits: gas 8191 max / 2398 min / 5260 inactive,
  brake max 659.
- **Gateway heartbeat.** The gateway sends `0x5FF` `LEAF_GW_HEARTBEAT` at 10 Hz on
  bus 2 (`LEAF_LONG_BUS`). The car side offers alpha longitudinal only when the
  fingerprint saw `0x5FF` on bus 2. In LONG mode, panda adds `0x5FF` on bus 2 to
  its rx checks, so a missing or silent gateway invalidates them and control
  stops. The message is in `generator/nissan/nissan_leaf_2018.dbc`, the same as
  upstream.
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
| `pytest opendbc/sunnypilot/car/nissan/test_nissan.py` (new) | n/a | 6 passed, 26 subtests |
| `pytest opendbc/car/tests/test_car_interfaces.py -k nissan` | 5 passed | 5 passed |
| `pytest opendbc/safety/tests/test_nissan.py` | 171 passed, 27 skipped | 235 passed, 36 skipped |
| `pytest opendbc/safety/tests -k wrong_safety_mode` (all brands) | 132 passed, 37 skipped | 133 passed, 37 skipped |
| `pytest opendbc/can/tests` (DBC touched) | — | 49 passed |

Nothing failed before the patches. With the ICBM guard reverted, the new
`test_icbm_buttons` fails for both Leafs with longitudinal on.

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
  - the golden stock `0x2B0` frames;
  - a direct CarController run with long on that emits `0x2B0`/`0x1C3` on bus 2;
  - no long frames without the toggle;
  - the ICBM guard.
