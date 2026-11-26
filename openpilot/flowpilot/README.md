# FlowPilot: Nissan Leaf longitudinal via leaf-gw

This is the upstream design (see [`..`](../README.md)) ported to FlowPilot, i.e. openpilot on Android.

- openpilot emits the real `0x2B0` (propulsion/regen) and `0x1C3` (friction brake) frames on bus 2 (`LEAF_LONG_BUS`).
- The stock ADAS ECU is not silenced, so AEB stays live, and cruise buttons are not spoofed.
- `pcmCruise` stays True.
- The `0x5FF` gateway heartbeat (50 Hz) gates the feature twice: openpilot offers longitudinal only if the heartbeat is in the bus-2 fingerprint, and panda drops control when the heartbeat stops.

**Target:** [`jagheterfredrik/flowpilot`](https://github.com/jagheterfredrik/flowpilot), the FlowPilot people use today. This port **replaces** the earlier one for `flowdriveai/flowpilot`, which is dormant; those patches are gone. jagheterfredrik is phr00t's fork plus 54 commits, on an openpilot 0.9-era base. panda, opendbc and cereal are **vendored** directories here, so there is one patch at the repo root.

## Base

`jagheterfredrik/flowpilot` master `9ea918eaa0b056fba55d22feb4ec99deab245100` (2025-03-04).

## Files

- **`flowpilot-leaf-gw-long.patch`**: applies at the repo root with `git apply`.
  - `selfdrive/car/nissan/values.py`: `CarControllerParams`, the same values as upstream.
    - `0x2B0` carries T = `(d2 << 4) | (d1 & 0xF)`, with an inverted copy in `d1_hi:d0`. Higher T means more deceleration.
    - Curve: `ACCEL_BP` = [-0.78 … 0.79] m/s² mapped to `T_BP` = [2784 … 2272]. It is provisional: the median of stock Leaf logs, not bench-tested.
    - `PROPILOT_ACCEL_MIN` = `ACCEL_BP[0]` and `ACCEL_MAX` = `ACCEL_BP[-1]`.
    - Idle 2595, brake marker 3415, `ACCEL_MIN` -3.5, `BRAKE_MAX` 659, `BRAKE_GAIN` 264.
  - `nissancan.py`: `LEAF_LONG_BUS`, `LEAF_GW_HEARTBEAT`, and `create_accel_command` / `create_brake_command`. These are byte-identical to `leaf_gw_long.pack_accel` / `pack_brake`: T is clipped to 0..4095, and aux is 2 only for the marker. They return this tree's `[addr, 0, dat, bus]`.
  - `carcontroller.py`:
    - T = `round(interp(accel, ACCEL_BP, T_BP))`, or the marker in brake mode.
    - Pressure = `round(max(0, PROPILOT_ACCEL_MIN - accel) * BRAKE_GAIN)`, or `BRAKE_MAX` when stopping below `vEgoStopping`. Both frames go out every frame.
    - It also sends the UI debug line (see below).
  - `interface.py`:
    - `experimentalLongitudinalAvailable` = Leaf and `0x5FF` in `fingerprint[2]`.
    - `openpilotLongitudinalControl` = `experimental_long and available`.
    - `Panda.FLAG_NISSAN_LEAF_LONG` goes into `safetyParam`; also `stopAccel` -2.0 and `get_pid_accel_limits`.
    - `pcmCruise` stays True and `autoResumeSng` stays False. There is no ECU takeover.
    - It also fixes `apply()` (see below).
  - `tests/test_leaf_gw.py` (new, 19 tests; the 0x180 follow-check tests are described below):
    - Gates: the experimental toggle, the heartbeat (absent, or on the wrong bus), and `pcmCruise`; other Nissans are unchanged.
    - Frames: golden stock frames, pack/decode round-trip for every T, the brake frame, and the DBC heartbeat layout.
    - Controller: T on the curve (higher T means more decel), and the frames when braking, stopped, disengaged, and with long off. Accel limits.
    - The UI debug line.
    - Spec checks: `test_packers_match_spec` compares byte for byte with `pack_accel` / `pack_brake` (T in -8..4199, all counters, both active states). `test_controller_matches_spec` checks (T, pressure) against `gateway_longitudinal`. Both skip unless `leaf_gw_long.py` is copied into `selfdrive/car/nissan/`; `fork.sh` copies it.
  - `opendbc/nissan_leaf_2018.dbc`: `BO_ 1535 LEAF_GW_HEARTBEAT` (50 Hz) and `BO_ 384 PROPULSION_FEEDBACK`, the same as upstream.
  - `panda/board/safety/safety_nissan.h`: mirrors upstream `nissan.h`.
    - `NISSAN_LONG_LIMITS`: `max_gas` 3415, `min_gas` 2272, `inactive_gas` 2595, `max_brake` 659.
    - It uses the shared `longitudinal_gas_checks` / `longitudinal_brake_checks`. These go through `get_longitudinal_allowed()`, so they block when the driver presses the accelerator.
    - Command decode is `(d2<<4)|(d1&0xF)`.
    - The LONG flag (2) selects a TX list with `0x2b0`/`0x1c3` on bus 2, and an rx-check list that adds `0x5ff` on bus 2 at 50 Hz.
  - `panda/python/__init__.py`: `FLAG_NISSAN_LEAF_LONG = 2`.
  - `panda/tests/safety/test_nissan.py`: new `TestNissanLeafLongSafety`. It runs every base test in LONG mode plus:
    - gas and brake limits, engaged and disengaged
    - gateway bus only
    - golden stock frames
    - gas pressed blocks
    - heartbeat required: with it, control stays; when it stops, control drops; a heartbeat on bus 0 doesn't count
    - no heartbeat needed without LONG

    The class is also added to the Nissan exception in `common.py`'s `test_tx_hook_on_wrong_safety_mode`.
- **`fork.sh`**: the `check-forks.sh` hook. It applies the patch, copies the spec in, and inside `shell.nix` builds the host libraries with `SConstruct.test` and `libpanda.so`. It then runs the four suites with a temporary `HOME` and prints one line per suite.
- **`shell.nix`**: nixpkgs pinned by `fetchTarball` + sha256 to leaf-gw's `flake.lock` rev `619c39f6`.
  - Python 3.12 with Cython 3, numpy 2, pycapnp, cffi, pytest, pytest-xdist and the rest.
  - clang, capnproto, zeromq, lmdb, libusb1, eigen and scons.
  - It sets `FP_PY`, `FP_INC` and `FP_LIB`.
- **`SConstruct.test`**: builds `params_pyx`, `clock`, `simple_kalman_impl`, `transformations`, opendbc's `libdbc`/packer/parser, `messaging_pyx` (via `cereal/SConscript`) and `boardd_api_impl`. It is needed because the root SConstruct is Android-only, and `opendbc/can/SConscript` hard-links `-lpython3.11`.

Run: `cd leaf-gw && openpilot/check-forks.sh flowpilot`. No outer dev shell is needed; `fork.sh` enters `shell.nix` itself.

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
  - The UI debug line appends ` FOLLOW FAULT` while latched.
- **Tests:**
  - The 0x180 gate, on the right bus per harness.
  - End to end through `CarInterface.update`/`apply` with packed CAN (wheel speeds plus 0x180), for both Leaf and Leaf IC. The car acting on T 2528 while asked for 2730 faults; following (2730) or slowing more (2784 while asked 2528) never faults.
  - The latch is released when long goes inactive.
  - `test_follow_monitor_matches_spec`: same constants, step-for-step identical to `leaf_gw_long.FollowMonitor`, and the DBC's D decodes like `feedback_t`.
  - `test_follow_check_timing_is_rate_independent`: through the real `CarInterface`, the first fault lands at 1.1–1.3 s with both 10 ms and 20 ms steps.
  - Without a clock, `update(..., now=None)` and `apply(CC, sm, None)` return without raising or faulting.
  - With the monitor disabled (fault never set), 4 tests fail. Fed a fixed 10 ms frame clock instead of `now_nanos`, the rate test fails.

## Things found in this tree and fixed in the patch

1. **Nissan `apply()` doesn't match `controlsd` (pre-existing; the Leaf could not run).**
   - `controlsd.py` calls `CI.apply(CC, self.sm, now_nanos)`, and `nissan/carcontroller.py` takes `update(CC, sm, CS, now_nanos)`.
   - But `nissan/interface.py` had `apply(self, c, now_nanos)` calling `CC.update(c, self.CS, now_nanos)`. That raises a TypeError either way. Toyota, GM, Honda and others have the same mismatch.
   - The patch fixes Nissan only: `apply(self, c, sm, now_nanos=0)`, calling `CC.update(c, sm, self.CS, now_nanos)`. The default keeps the stale `test_car_interfaces` call `apply(CC, 0)` working; `sm` is unused by Nissan.
   - Before the fix, `test_car_interfaces -k nissan` failed 5 of 5.
2. **UI "System Unresponsive!" (phr00t lineage).**
   - `OnRoadScreen.NoDebugMessagesWarning()` warns, with an immediate-warning sound, unless two kinds of UDP debug line (port 9000, via `common.logger.sLogger`) have each arrived within 500 ms: one starting with `"0"`, and one not.
   - The non-`"0"` line comes from `lane_planner.py`. The `"0"` line is up to each car's carcontroller; Hyundai sends one every frame. Nissan sent none.
   - The patch sends `"0nissan"` (lateral only) or `"0leaf-gw T<T> P<pressure>"` every 5th frame (about 50 ms at 100 Hz). `test_ui_debug_line` checks it.
3. **The vendored panda tests don't match the vendored opendbc (pre-existing; every Nissan panda test failed).**
   - panda's `common.py` unpacks `make_can_msg` as `addr, dat, bus`, while this opendbc's packer returns `[addr, 0, dat, bus]`.
   - `test_nissan.py` asks for `*_generated` DBCs that this opendbc doesn't have.
   - The patch makes the unpack take `msg[0], msg[-2], msg[-1]` (one line, harmless for both shapes) and points `test_nissan.py` at `nissan_x_trail_2017` / `nissan_leaf_2018`.

The test harness also needs one host-only shim, which lives in `fork.sh` and is not part of the patch. `common/path.py` hardcodes `BASEDIR` to `/data/data/ai.flow.android/files/app`, which `selfdrive/car` uses to discover brands. `fork.sh` loads a pytest plugin that points it at the worktree.

## Opt-in: experimental longitudinal (default off)

- `get_params(candidate, fingerprint, car_fw, experimental_long, docs)` receives `Params().get_bool("ExperimentalLongitudinalEnabled")` from `controlsd`. This is the same idiom as upstream's `alpha_long`, and Honda, Hyundai, VW, Ford and GM use it here too.
- `controlsd` removes the param whenever `experimentalLongitudinalAvailable` is False. A drive started without the gateway heartbeat therefore clears the opt-in, and it must be set again. Upstream behaves the same with its alpha toggle.
- **UI:** the Android settings (`SettingsScreen.java`) list "easy toggles" as display-name/param pairs, and there is no `ExperimentalLongitudinalEnabled` entry for any car. Enable it with `python common/params.py ExperimentalLongitudinalEnabled 1`. The UI is not changed, because this would expose it for every car. Adding `"Experimental Longitudinal (alpha)", "ExperimentalLongitudinalEnabled"` to `AdditionalToggles` would make it a toggle.
- `DisableRadar` (the flowdriveai idiom) is not used.

**Fingerprint window:** `car_helpers.fingerprint` runs for at least `frame_fingerprint = 100` CAN frames (about 1 s). At 50 Hz, about 50 heartbeats arrive in that window, so missing it isn't a practical concern. If it is somehow missed, longitudinal isn't offered for that drive and the car runs lateral-only, which fails safe.

## Results (nix `shell.nix`, fresh worktrees at `9ea918ea`)

| suite | before | after |
|---|---|---|
| `panda/tests/safety/test_nissan.py` | 81 failed (DBC names and packer tuple) | **103 passed, 12 skipped** (+31 from `TestNissanLeafLongSafety`) |
| `panda/tests/safety/` (all) | 1519 failed, 635 passed, 1010 skipped | 159 failed, 1889 passed, 1022 skipped (+128 subtests). The failures left are other brands' missing `*_generated` DBCs. The `common.py` fix alone gives 159 failed / 1858 passed. |
| `test_car_interfaces.py -k nissan` | 5 failed (`apply` TypeError) | **5 passed** |
| `test_car_interfaces.py` (all) | aborts (Hyundai `CarController.__init__`) | aborts the same way (pre-existing, not Nissan) |
| `selfdrive/car/nissan/tests` | n/a (new) | 16 passed, 3 skipped (spec absent); **19 passed** with `leaf_gw_long.py` copied in |
| `test_leaf_gw_long.py` | passes | passes |
| panda F4 + H7 firmware (leaf-gw `.#panda` shell) | n/a | builds and signs. One test-only flag is needed, `-Wno-error=unterminated-string-initialization`, because `board/obj/gitversion.h` trips gcc 15; this is pre-existing and not in the patch. |

MISRA: no new violations (cppcheck 2.15.0; `panda/tests/misra/test_misra.sh`, F4 + H7).

`openpilot/check-forks.sh flowpilot` passes with no outer shell. From a scratch copy with `MAX_GAS` changed to 3414 in the patched panda test, it prints FAIL: 1 failed, 102 passed, 12 skipped.

Checks that the new tests catch the code they guard:

| change | failures |
|---|---|
| New panda tests on the original `safety_nissan.h` | 5 |
| Heartbeat removed from the LONG rx checks | 1 (`test_leaf_gateway_heartbeat_required`) |
| `0x2B0` decoded with the wrong nibble order | 3 |
| Heartbeat gate in `interface.py` turned into `or` | 2 |
| Debug line removed | 1 (`test_ui_debug_line`) |
| Follow monitor disabled | 4 |

## phr00t/flowpilot master (`84f25d0`, 2024-06-09)

This patch does not apply there: every panda hunk fails, because jagheterfredrik replaced the vendored panda after phr00t. phr00t has its own patch set in [`../phr00t/`](../phr00t/README.md), with its own check-forks row, `phr00t`.

## Deviations from upstream

- **Opt-in:** `experimentalLongitudinalAvailable` / `experimental_long` (this tree's names) replace `alphaLongitudinalAvailable` / `alpha_long`.
- **Old API idioms:**
  - `CAR.LEAF` / `CAR.LEAF_IC` and `Panda.FLAG_NISSAN_LEAF_LONG` replace `NISSAN_LEAF*` and `NissanSafetyFlags`.
  - `make_can_msg` lists replace `CanData`, and `common.numpy_fast` replaces `np`.
- **Panda:** `GET_BYTE` replaces `msg->data`, `RxCheck` uses `.frequency`, and `CanMsg` has no `check_relay`.
- **Extra fixes:** the three items under "Things found" are not in the upstream patches.
- **Panda tests:** LONG mode is its own class, so lateral-only Leafs stay covered too. Upstream switched the Leaf class itself to LONG.
