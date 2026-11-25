# FlowPilot: Nissan Leaf longitudinal via leaf-gw

This is the same design as the upstream patches in [`..`](../README.md), ported to
FlowPilot (openpilot on Android). openpilot emits the real `0x2B0`
(propulsion/regen) and `0x1C3` (friction brake) frames on bus 2 (`LEAF_LONG_BUS`).
The stock ADAS ECU is not silenced, so AEB stays live, and cruise buttons are not
spoofed. `pcmCruise` stays True. The `0x5FF` gateway heartbeat gates the feature
twice: openpilot offers longitudinal only if the heartbeat is in the fingerprint,
and panda drops control if the heartbeat stops.

FlowPilot is a hard fork of openpilot `05b37552` (late 2022). Its car code
predates opendbc's `car/` split, `LongitudinalLimits`, `alpha_long` and
`CanData`, so the upstream patches don't apply here. This port rewrites them
against the old APIs.

## Base commits

| repo | path | commit |
|---|---|---|
| `flowdriveai/flowpilot` | `.` | `59f5cf3ff0fb5ca7b483b146f3bf4fee30239410` (master, 2024-05-17, `FLOWPILOT_VERSION` 0.2.3) |
| `flow-drive-ai/panda` | `panda/` | `f120999e19fed7208534ae74b542b5cca6bafeaa` (2022-09-14) |
| `flow-drive-ai/opendbc` | `opendbc/` | `7d966b5c24db3c4fe49b379511264ebff7a57e91` (2022-09-15) |
| `flow-drive-ai/cereal` | `cereal/` | `92f47d2efb61fcc348c39ebe2fc6a5e73570b2d0` (unchanged) |

## Files

- **`flowpilot-leaf-gw-long.patch`** applies at the flowpilot root and touches `selfdrive/car/nissan/`:
  - `values.py`: `CarControllerParams` longitudinal constants (ACCEL_MIN -3.5, ACCEL_MAX 2047/2048, offset 6144, scale 2048, INACTIVE 5260, BRAKE_RAW 2398, BRAKE_MAX 659, BRAKE_GAIN 264).
  - `nissancan.py`: `LEAF_LONG_BUS = 2`, `LEAF_GW_HEARTBEAT = 0x5FF`, and `create_accel_command` / `create_brake_command`. The bytes are identical to `leaf_gw_long.pack_accel` / `pack_brake`; the code returns this era's `[addr, 0, dat, bus]`.
  - `carcontroller.py`: maps accel to (raw command, pressure) exactly as in the upstream patch, sends both frames every frame, and clips `actuators.accel` in the returned actuators.
  - `interface.py`: adds the opt-in (below), the heartbeat gate, `Panda.FLAG_NISSAN_LEAF_LONG` in `safetyParam`, and `get_pid_accel_limits`. It adds no ECU takeover and leaves `pcmCruise` True.
  - `tests/test_leaf_gw.py` (new, 11 tests): the opt-in, heartbeat and `pcmCruise` gates; other Nissans unchanged; golden stock frames; pack/decode round-trip; the DBC heartbeat layout; the controller's frames when engaged, braking, stopped and disengaged; accel limits. `test_packers_match_spec` compares the packers exhaustively against `leaf_gw_long.py` when that file is copied into `selfdrive/car/nissan/`, and skips otherwise.
- **`panda.patch`** applies at the panda submodule root:
  - `board/safety/safety_nissan.h`:
    - Flags: `NISSAN_PARAM_ALT_EPS_BUS = 1`, `NISSAN_PARAM_LEAF_LONG = 2`. `GET_FLAG` replaces the old `param ? 1 : 0`, which would have read the new flag as alt-EPS.
    - LONG mode switches to its own TX list (adds `0x2b0` and `0x1c3` on bus 2) and its own addr-check list (adds `0x5ff` on bus 2, 20 ms / 50 Hz).
    - Explicit bounds use the tx hook's `longitudinal_allowed`, which is `get_longitudinal_allowed()`: controls allowed and gas not pressed. This panda has no `LongitudinalLimits` helpers.
    - `0x2B0`: `raw12 = ((d1>>4)<<8)|((d2&0xF)<<4)|(d1&0xF)` and `command = raw12<<2 | (d7>>2)&3`. It must be 2398..8191 while longitudinal is allowed; otherwise only 5260 passes.
    - `0x1C3`: pressure must be <= 659, and 0 when longitudinal is not allowed.
  - `python/__init__.py`: `FLAG_NISSAN_ALT_EPS_BUS = 1` and `FLAG_NISSAN_LEAF_LONG = 2`.
  - `tests/safety/test_nissan.py`: new `TestNissanLeafLongSafety` class that subclasses the Leaf test, so every base test also runs in LONG mode. It adds gas and brake limits (engaged and disengaged), gateway bus only, golden stock frames, gas-pressed blocking, the heartbeat as an rx check (it lags and controls drop, and a heartbeat on bus 0 doesn't count), and no heartbeat needed without LONG. `tests/safety/common.py` adds the new class to the existing Nissan exception in `test_tx_hook_on_wrong_safety_mode`.
- **`opendbc.patch`** applies at the opendbc submodule root. It adds `BO_ 1535 LEAF_GW_HEARTBEAT` (with the same signals and comment as upstream) to `nissan_leaf_2018.dbc`. This opendbc has no `generator/` for Nissan, so the edit goes into the hand-written DBC.

## Opt-in: `DisableRadar` (default off)

FlowPilot's `get_params(candidate, fingerprint, car_fw)` has no `experimental_long` / `alpha_long` argument, and its `CarParams` has no `experimentalLongitudinalAvailable` / `alphaLongitudinalAvailable` or `autoResumeSng`. This tree already has an alpha-longitudinal opt-in, used by Honda Bosch and Hyundai: `Params().get_bool("DisableRadar")` inside `get_params`. `flowinitd.py` deletes `DisableRadar` at every start unless `DisableRadar_Allow` is set, so it is off by default and needs two explicit settings. The Leaf uses the same toggle, and only when the heartbeat is in `fingerprint[2]`:

```
python common/params.py DisableRadar_Allow 1
python common/params.py DisableRadar 1
```

**UI / Android layer:** no change is needed. The Java settings (`selfdrive/ui/java/ai.flow.app/SettingsScreen.java`) expose no `DisableRadar` toggle for any car (Honda and Hyundai have the same gap), and nothing on the Java side reads `openpilotLongitudinalControl`, `pcmCruise` or `safetyParam`. `boardd.cc` forwards `safetyParam` to panda as is. `pandad.py` reflashes `panda/board/obj/panda*.bin.signed` when the signature changes, so rebuilding the patched tree on the device is enough to get the new safety mode. A UI toggle would be a separate, optional feature.

## Apply

```
cd flowpilot                      # at 59f5cf3, submodules at the commits above
git apply  /path/to/flowpilot/flowpilot-leaf-gw-long.patch
git -C panda   apply /path/to/flowpilot/panda.patch
git -C opendbc apply /path/to/flowpilot/opendbc.patch
```

All three were checked with `git apply` on fresh worktrees at those commits.

## Test environment (nix; leaf-gw/flake.nix not touched)

`fork.sh` (the `check-forks.sh` hook) does all of the below: it adds the submodule worktrees, applies the patches, copies the spec in, and builds and runs the suites inside `shell.nix` (nixpkgs pinned to leaf-gw's `flake.lock` rev) with `SConstruct.test`. Run it as `openpilot/check-forks.sh flowpilot`. The manual recipe follows.

The tree needs Cython 0.29 (`cython_0`; Cython 3 isn't tested). Everything else comes from current nixpkgs: Python 3.12.16, numpy 2.5.4, pycapnp 2.2.3, cffi 2.1.1, capnproto 1.5.0, clang 21, scons 4.10. `env.nix`:

```nix
let pkgs = import (builtins.getFlake "nixpkgs") {}; in with pkgs; {
  inherit clang capnproto zeromq scons;
  lmdb = lmdb.dev; lmdbOut = lmdb.out; usb = libusb1.dev;
  py = python312.withPackages (ps: with ps; [ cython_0 numpy pycapnp cffi pytest parameterized
         hypothesis tqdm pyyaml setuptools libusb1 requests pyzmq crcmod ]);
}
```

Enter it with `nix shell --impure -f env.nix py clang capnproto zeromq lmdb lmdbOut scons`. The root `SConstruct` needs acados and other Android deps, so the test libs are built with a small out-of-tree `SConstruct.test`, copied to the repo root and run as `scons -f SConstruct.test`. It builds:

- `common/params_pyx.so`: `params.cc` + `util.cc` + lmdb only, because `swaglog` needs json11, which isn't in nixpkgs and isn't needed here
- `common/clock.so`
- `common/kalman/simple_kalman_impl.so`
- `opendbc/can/` (`libdbc`, `packer_pyx`, `parser_pyx`)
- `cereal/SConscript` (for `messaging_pyx.so`)
- `selfdrive/boardd/boardd_api_impl.so`

Notes on that build:

- `FP_INC` / `FP_LIB` point at the capnproto, zeromq, lmdb and libusb store paths. `FP_PY` is the env's python3, because the scons wrapper puts its own python 3.14 first on `PATH`.
- `-include iterator` is needed because `opendbc/can/dbc.cc` uses `std::ostream_iterator` without the header, and gcc 16's libstdc++ no longer pulls it in.
- `AddOption("--test")` is needed for `cereal/SConscript`.

The panda test library is built directly:
`cd panda/tests/safety && gcc -shared -fPIC -nostdlib -fno-builtin -std=gnu11 -I. -I../../board test.c -o libpandasafety.so`.

Tests run with `PYTHONPATH=<root> HOME=/tmp/fphome` (Params lives in `$HOME/.flowdrive/params`):

```
python3 -m pytest -q panda/tests/safety/test_nissan.py
python3 -m pytest -q panda/tests/safety/
python3 -m pytest -q selfdrive/car/tests/test_car_interfaces.py [-k "NISSAN or nissan"]
python3 -m pytest -q selfdrive/car/nissan/tests/
cp ../leaf_gw_long.py ../test_leaf_gw_long.py selfdrive/car/nissan/ && (cd selfdrive/car/nissan && python3 test_leaf_gw_long.py)
```

The panda firmware was built with leaf-gw's `nix develop .#panda` (gcc-arm-embedded):
`scons board/obj/panda.bin.signed board/obj/panda_h7.bin.signed`.

## Results (fresh worktrees)

| suite | before | after |
|---|---|---|
| `panda/tests/safety/test_nissan.py` | 42 passed, 6 skipped | **70 passed, 9 skipped** (+28 in `TestNissanLeafLongSafety`) |
| `panda/tests/safety/` (all modes) | 972 passed, 435 skipped | **1000 passed, 438 skipped** |
| `test_car_interfaces.py -k nissan` | 5 passed | 5 passed |
| `test_car_interfaces.py` (all) | 149 passed, 7 failed | 149 passed, 7 failed (the same 7 Chrysler/Jeep cases, which fail before the patch: `chrysler_pacifica_2017_hybrid` is a generated DBC that is not committed) |
| `selfdrive/car/nissan/tests/` | n/a (new) | 10 passed, 1 skipped (spec absent); **11 passed** with `leaf_gw_long.py` copied in |
| `test_leaf_gw_long.py` | passes | passes |
| panda F4 + H7 firmware (`-Werror`) | n/a | builds and signs |

Checks that the new tests catch the code they guard:

- New panda tests on the old `safety_nissan.h`: 13 fail.
- Heartbeat removed from the LONG addr checks: `test_gateway_heartbeat_required` fails.
- `longitudinal_allowed` dropped from the `0x2B0` bound: 3 fail.
- Heartbeat gate dropped from `interface.py`: `test_long_needs_gateway_heartbeat` fails.

## Not run

- **`test_models.py` (nissan routes):** it downloads comma CI route logs and needs the full process stack.
- **MISRA (`panda/tests/misra/test_misra.sh`):** it builds a pinned cppcheck from source, which was not done. The new C code follows the file's existing style (unsigned literals, no new casts).
- **On-device Android build and HIL:** not available.

## Deviations from the upstream patches

- **Opt-in:** `Params().get_bool("DisableRadar")` replaces `alpha_long`. There is no `alphaLongitudinalAvailable` field, so availability shows only as the `openpilotLongitudinalControl` result.
- **Car names:** `CAR.LEAF` / `CAR.LEAF_IC` replace `NISSAN_LEAF*`. `make_can_msg` lists replace `CanData`. `common.numpy_fast.clip` replaces `np.clip`. `stopAccel` is already -2.0 from `get_std_params`.
- **Panda bounds:** the bounds are open-coded. They match `longitudinal_gas_checks` (`allowed && min<=x<=max` or `x == inactive`) and `longitudinal_brake_checks` (`x > max` or `!allowed && x != 0`).
- **Heartbeat check:** it is an `AddrCheckStruct` (`expected_timestep` 20000 us; the heartbeat is 50 Hz). In this panda era, lag is only enforced by the 1 Hz `safety_tick` with a 1 s floor, so control drops 1 to 2 s after the heartbeat stops. Upstream behaves the same way.
- **Panda safety tests:** LONG mode is a separate class, `TestNissanLeafLongSafety`. Upstream instead switched `TestNissanLeafSafety` itself to the LONG flag. Here both lateral-only and LONG Leafs stay covered.
- **Fingerprint window (risk):** FlowPilot ends fingerprinting after about 10 CAN frames (about 0.1 s) once there is a single candidate. At 50 Hz about 5 heartbeats land in that window, so missing it takes a gateway that is late or dropping frames at startup. If it is missed, longitudinal is not enabled for that drive and the car runs lateral-only, which fails safe; restart to retry.
