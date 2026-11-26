# phr00t/flowpilot: Nissan Leaf longitudinal via leaf-gw

This is the upstream design (see [`..`](../README.md)) ported to phr00t's FlowPilot (openpilot on Android).

- openpilot emits the real `0x2B0` (propulsion/regen) and `0x1C3` (friction brake) frames on bus 2.
- The stock ADAS ECU is not silenced, so AEB stays live, and cruise buttons are not spoofed.
- `pcmCruise` stays True.
- The 50 Hz `0x5FF` gateway heartbeat gates the feature twice: openpilot offers longitudinal only if the heartbeat is in the bus-2 fingerprint, and panda drops control when the heartbeat stops.

## Base and relation to the other FlowPilot ports

`phr00t/flowpilot` master `84f25d0626bfbada0706b46b4b7f68a605b9ff8c` (2024-06-09).

- This is the tree the phr00t wiki's [Simplified "Tarball" install](https://github.com/phr00t/flowpilot/wiki/Simplified-%22Tarball%22-Flow-Pilot-Install-Process) builds from.
- [`jagheterfredrik/flowpilot`](../flowpilot/README.md) is this tree plus 54 commits. Its car side is the same, apart from 4 lines in `nissan/values.py`, but it replaced the vendored panda.
- So the car side and DBC here are the jagheterfredrik patch's hunks unchanged. The panda hunks are written for phr00t's older panda: `AddrCheckStruct` / `addr_checks` rx checks, top-level `NISSAN_TX_MSGS`, and `nissan_init(param)` returning `addr_checks*`.

panda, opendbc and cereal are vendored, so there is one patch at the repo root.

## Files

- **`phr00t-leaf-gw-long.patch`**: apply with `git apply` at the repo root.
  - **Car side and DBC** (identical to `../flowpilot/`, including the 0x180 follow check):
    - `nissan/values.py`: the T curve. `ACCEL_BP` [-0.78 … 0.79] maps to `T_BP` [2784 … 2272]; idle 2595, marker 3415, `BRAKE_MAX` 659, `BRAKE_GAIN` 264.
    - `nissancan.py`: the packers, byte-identical to `leaf_gw_long.pack_accel` / `pack_brake`.
    - `carcontroller.py`: T = `round(interp(accel, ACCEL_BP, T_BP))` or the marker; pressure = `round(max(0, PROPILOT_ACCEL_MIN - accel) * BRAKE_GAIN)`.
    - `interface.py`:
      - `experimentalLongitudinalAvailable` = Leaf and heartbeat in `fingerprint[2]`.
      - `openpilotLongitudinalControl` = `experimental_long and available`.
      - `Panda.FLAG_NISSAN_LEAF_LONG`; `pcmCruise` stays True and `autoResumeSng` stays False.
    - `tests/test_leaf_gw.py` (19 tests): the gates, golden and round-trip frames, the DBC heartbeat, the controller, the UI debug line, the 0x180 follow check, and byte-identity with the spec.
    - `opendbc/nissan_leaf_2018.dbc`: `BO_ 1535 LEAF_GW_HEARTBEAT` and `BO_ 384 PROPULSION_FEEDBACK`.
  - **`panda/board/safety/safety_nissan.h`**:
    - This panda has `LongitudinalLimits` + `longitudinal_gas_checks` / `longitudinal_brake_checks` (through `get_longitudinal_allowed()` = `controls_allowed && !gas_pressed_prev`). So it uses the same `NISSAN_LONG_LIMITS` as upstream: `max_gas` 3415, `min_gas` 2272, `inactive_gas` 2595, `max_brake` 659.
    - Command decode is `(d2<<4)|(d1&0xF)`.
    - `nissan_init` uses `GET_FLAG`; the old `param ? 1 : 0` would have read the LONG flag (2) as alt-EPS.
    - The LONG flag selects `NISSAN_LEAF_LONG_TX_MSGS` (adds `0x2b0`/`0x1c3` on bus 2) and `nissan_leaf_long_addr_checks` (adds `0x5ff` on bus 2, `expected_timestep` 20000 us = 50 Hz).
  - **`panda/python/__init__.py`**: `FLAG_NISSAN_ALT_EPS_BUS = 1` and `FLAG_NISSAN_LEAF_LONG = 2`. This panda had no Nissan flags.
  - **`panda/tests/safety/test_nissan.py`**: `TestNissanLeafLongSafety`. It reruns every base test in LONG mode and adds:
    - gas and brake limits, engaged and disengaged
    - gateway bus only
    - golden stock frames
    - gas pressed blocks (via an rx gas message with disengage-on-gas off, since this panda has no `set_gas_pressed_prev`)
    - the heartbeat rx check: control stays while it arrives, drops after it stops, and a heartbeat on bus 0 doesn't count
    - no heartbeat needed without LONG

    The DBC names now point at this opendbc's `nissan_x_trail_2017` / `nissan_leaf_2018`; the `*_generated` names aren't vendored here. `common.py` adds the new class to the existing Nissan exception in `test_tx_hook_on_wrong_safety_mode`.
- **`fork.sh`**: the `check-forks.sh` hook (`openpilot/check-forks.sh phr00t`). It is the same as `../flowpilot/fork.sh` apart from the patch name.
- **`shell.nix`**: nixpkgs pinned to leaf-gw's lock rev with `fetchTarball` + sha256. Python 3.12 with Cython 3, plus a separate Cython 0.29 `cythonize` for `boardd_api_impl` (see below).
- **`SConstruct.test`**: the host test build.

## Follow check (0x180)

This is the same as upstream `FollowMonitor` / `leaf_gw_long.feedback_t`: a one-sided check that the car actually follows what openpilot sent.

- **DBC:** `BO_ 384 PROPULSION_FEEDBACK` (`SG_ D : 23|12@0-`) plus its `CM_`. The car reports the T it is acting on about 160 ms later: D ≈ -0.796·T + 2067.
- **Gate:** `experimentalLongitudinalAvailable` also needs `LEAF_FEEDBACK_ADDR` (0x180) in `fingerprint[0]` (Leaf, Nissan A harness) or `fingerprint[1]` (Leaf IC).
- **carstate:**
  - Only when `openpilotLongitudinalControl` is on, `PROPULSION_FEEDBACK.D` is added to the bus-0 parser (Leaf) or the bus-1 parser (Leaf IC). Its check frequency is 0, so a missing 0x180 never affects `canValid`; lateral-only cars are unaffected.
  - `leaf_feedback = (2067.1 - D) / 0.796`. It goes to None when `ts_nanos` hasn't changed for more than 5 updates.
  - `ret.accFaulted = gw_follow_fault`. `create_common_events` turns that into `accFaulted`, which disengages.
- **carcontroller:** `FollowMonitor` as upstream: time-based, with LAG 0.16 s, TOL 60 and WINDOW 1.0 s. It keeps a history of (time, T sent) and is fed the controller's `now_nanos * 1e-9`, which comes from `controlsd`'s `sec_since_boot()`, so it holds at any controller rate. With no clock (`now` is None) it resets and returns False instead of raising.
  - It evaluates only when `vEgo > 2 and not gasPressed and not brakePressed`.
  - It skips while the brake marker is in the history or there is no feedback.
  - It faults when `hist[0] - feedback > TOL` for WINDOW frames, and latches until long goes inactive.
  - The UI debug line appends `FOLLOW FAULT` while latched.
- **Tests:**
  - The 0x180 gate, on the right bus per harness.
  - End to end through `CarInterface.update`/`apply` with packed CAN (wheel speeds plus 0x180), for both Leaf and Leaf IC. The car acting on T 2528 while asked for 2730 faults; following (2730) or slowing more (2784 while asked 2528) never faults.
  - The latch is released when long goes inactive.
  - `test_follow_monitor_matches_spec`: same constants, step-for-step identical to `leaf_gw_long.FollowMonitor`, and the DBC's D decodes like `feedback_t`.
  - `test_follow_check_timing_is_rate_independent`: through the real `CarInterface`, the first fault lands at 1.1–1.3 s with both 10 ms and 20 ms steps.
  - Without a clock, `update(..., now=None)` and `apply(CC, sm, None)` return without raising or faulting.
  - With the monitor disabled (fault never set), 4 tests fail. Fed a fixed 10 ms frame clock instead of `now_nanos`, the rate test fails.

## Things this tree needed, also in the patch

1. **Nissan `apply()` doesn't match `controlsd`.**
   - This is the same as jagheterfredrik, which inherited it from here. `controlsd` calls `CI.apply(CC, self.sm, now_nanos)`, and `nissan/carcontroller.py` takes `update(CC, sm, CS, now_nanos)`. But `nissan/interface.py` had `apply(self, c, now_nanos)`, which is a TypeError on every frame.
   - Fixed with `apply(self, c, sm, now_nanos=0)` calling `CC.update(c, sm, self.CS, now_nanos)`. The default keeps the stale `test_car_interfaces` call `apply(CC, 0)` working.
   - Other brands still have the mismatch, and the patch doesn't touch them. That accounts for most of the 202 non-Nissan `test_car_interfaces` failures.
2. **UI "System Unresponsive!".**
   - `OnRoadScreen.NoDebugMessagesWarning()` requires a `"0…"` and a non-`"0"` UDP debug line (`common.logger.sLogger`) within 500 ms.
   - The Nissan carcontroller now sends `"0nissan"` or `"0leaf-gw T<T> P<pressure>"` every 5th frame (about 50 ms at 100 Hz). Hyundai sends one every frame.
3. **Python 3.11+ dataclass defaults.**
   - `car_parts: CarParts = CarParts(...)` is a mutable dataclass default, which Python 3.11+ rejects at import. That makes every brand fail to import, because `car_helpers` loads them all.
   - The patch applies jagheterfredrik's fix (`adf63ab`, "all running"): `field(default_factory=…)` in `docs_definitions.py` and the chrysler, ford, mazda, nissan, subaru, toyota and volkswagen `values.py` files.
   - It changes nothing on Python 3.10 and older. The wiki doesn't say which Python the tarball install runs; on 3.11+ this tree can't import `selfdrive.car` without the fix.

Host-only, in `fork.sh` and `shell.nix` and not in the patch:

- `common/path.py` hardcodes `BASEDIR` to the Android app dir, so a pytest plugin points it at the worktree.
- `boardd_api_impl.pyx` declares `can_list_to_can_capnp_cpp`, which is `extern "C"` in the `.cc`, with a bare `cdef extern`. Cython 3 gives that C++ linkage, so the module fails to import (undefined symbol). `SConstruct.test` builds just that module with Cython 0.29.

## Opt-in, UI, fingerprint

These are the same as jagheterfredrik.

- Longitudinal is opt-in through experimental longitudinal: `python common/params.py ExperimentalLongitudinalEnabled 1`. Default is off.
- `controlsd` clears that param on a drive started without the heartbeat.
- There is no settings toggle for it; the README in `../flowpilot/` gives the one-line `AdditionalToggles` entry that would add one.
- `frame_fingerprint = 100` (about 1 s), so about 50 heartbeats arrive in the window.

## Results (nix `shell.nix`, fresh worktrees at `84f25d0`)

| suite | before | after |
|---|---|---|
| `panda/tests/safety/test_nissan.py` | 52 failed (`*_generated` DBCs missing) | **76 passed, 9 skipped** |
| `panda/tests/safety/` (all) | 57 failed, 1581 passed, 858 skipped | 5 failed, 1657 passed, 867 skipped. The 5 left are Hyundai `test_spam_can_buses`, failing before and after. |
| `test_car_interfaces.py -k nissan` | collection error (Python 3.11 dataclass default) | **5 passed** |
| `test_car_interfaces.py` (all) | collection error | 5 passed, 202 failed (other brands: the same `apply()`/`update()` signature mismatch, plus a few CAN-parser setup errors) |
| `selfdrive/car/nissan/tests` | n/a (new) | **19 passed** with `leaf_gw_long.py` copied in; 16 passed, 3 skipped without it |
| `test_leaf_gw_long.py` | passes | passes |
| panda F4 + H7 firmware (leaf-gw `.#panda`) | n/a | builds and signs |

MISRA: no new violations (cppcheck e1cff1d1 + 7199dde1, as `panda/tests/misra/install.sh` pins; F4 + H7 + pedal).

`openpilot/check-forks.sh phr00t` passes. With a deliberately broken panda test (`MAX_GAS` 3414) it prints FAIL.

Checks that the new panda tests catch the code they guard:

| change | failures |
|---|---|
| New tests on the original `safety_nissan.h` | 17 |
| Heartbeat removed from the LONG addr checks | 1 |
| `0x2B0` decoded with the wrong nibble order | 3 |

The car-side mutation checks are the same as in `../flowpilot/`; with the follow monitor disabled, 4 tests fail.

## Deviations from upstream

- **Opt-in:** `experimental_long` / `experimentalLongitudinalAvailable` replace `alpha_long` / `alphaLongitudinalAvailable`.
- **Old API idioms:** `CAR.LEAF*` and `Panda.FLAG_*` replace the newer names and `NissanSafetyFlags`; `make_can_msg` lists replace `CanData`.
- **Panda:** `AddrCheckStruct` with `expected_timestep` replaces `RxCheck` with frequency. In this panda era, lag is enforced by the 1 Hz safety tick, so control drops 1 to 2 s after the heartbeat stops.
- **Extra fixes:** the three items under "Things this tree needed" are not in the upstream patches.
- **Panda tests:** LONG mode is its own test class.
