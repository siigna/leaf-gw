# leaf-gw longitudinal for RetroPilot (openpilot 0.8.13.1, C2)

> **On stock `c2` the Leaf is never selected.** `selfdrive/car/car_helpers.py` line 86
> (at `b9a942ef`) hard-codes `fixed_fingerprint = "RETROPILOT RETROFIT"`, so every car
> runs as the RetroPilot retrofit and none of this Nissan code runs. Revert that line
> to real fingerprinting first. For example, restore the commented-out line 84,
> `fixed_fingerprint = os.environ.get('FINGERPRINT', "")`. Also note that line 88
> sets `skip_fw_query = True`. These patches do not touch either line.

`fork.sh` (with `shell.nix`) is the `check-forks.sh` hook for this fork. Run
`openpilot/check-forks.sh retropilot` from the leaf-gw root. It does every step
below, then runs the nissan suites.

The same design as the upstream patches in `..` (real `0x2B0`/`0x1C3` on panda
bus 2, stock ProPILOT engagement, no ECU silencing, no button spoofing, 50 Hz
`0x5FF` heartbeat gate), ported to RetroPilot's `c2` branch. That tree predates
opendbc's `car/` split, `LongitudinalLimits`, the alpha-long toggle and
`CC.longActive`, so the code is written against what 0.8.13 has.

## Base

| repo | commit |
|---|---|
| `RetroPilot/openpilot` branch `c2` | `b9a942efd3cb210127bb5efb5cf9ccf6a811c728` (2025-08-14, "remove Pipfile from lfs") |
| `panda` submodule (`RetroPilot/panda`) | `9e6d47f63675d5a45170ae7972c24412034dc136` (2025-06-13) |
| `opendbc` submodule (`RetroPilot/opendbc`) | `6b90fafe59e81822bfae58e4ecb080248e9de40d` (2025-07-24) |
| `cereal` submodule (`RetroPilot/cereal`), unchanged | `a7193d0f0e472f90709e6671ce6ff01d1534c2a5` |

The submodule URLs in `.gitmodules` are `../../RetroPilot/<repo>.git`; the
panda/opendbc commits are not in `commaai/*`.

## Apply

Each patch applies at its own repo root (`git apply` from a subdirectory skips
files without saying so):

```
cd openpilot           && git apply /path/to/retropilot/openpilot.patch
cd openpilot/panda     && git apply /path/to/retropilot/panda.patch
cd openpilot/opendbc   && git apply /path/to/retropilot/opendbc.patch
```

All three were applied with `git apply --check` and `git apply` to fresh worktrees
at the commits above. The suites below were run on that tree.

## What changes

`openpilot.patch` (`selfdrive/car/nissan/`):
- `values.py`: the longitudinal `CarControllerParams` constants, identical to
  `leaf_gw_long.py`:
  - `ACCEL_BP` and `T_BP`, the provisional accel→T curve;
  - `PROPILOT_ACCEL_MIN = -0.78` and `ACCEL_MAX = 0.79`;
  - inactive T 2595 and brake-marker T 3415;
  - `BRAKE_MAX` 659 and `BRAKE_GAIN` 264.
- `nissancan.py`: `LEAF_LONG_BUS = 2`, `LEAF_GW_HEARTBEAT = 0x5FF`, and
  `create_accel_command` / `create_brake_command`. They return 0.8.13's
  `[addr, 0, dat, bus]` and are byte-identical to `pack_accel` / `pack_brake`.
  This was checked over T -4..4099 (which crosses the 0..4095 clip) and pressure
  0..1023, × frame 0..31 × active × brake_mode.
  - `0x2B0` carries the 12-bit `T = (d2 << 4) | (d1 & 0xF)`; higher T means more
    deceleration.
  - The inverted copy sits in `d1_hi:d0`.
  - `d7 = aux<<2 | (~aux & 3)`, where aux is 2 only for the brake marker (T 3415).
- `carcontroller.py`: the `gateway_longitudinal` mapping:
  - `T = round(interp(accel, ACCEL_BP, T_BP))`;
  - the brake marker below `PROPILOT_ACCEL_MIN` or when stopping;
  - `pressure = round(max(0, PROPILOT_ACCEL_MIN - accel) * BRAKE_GAIN)`.

  The curve uses `common.numpy_fast.interp`, which does the same float operations
  as the spec's `_interp`. `CC.longActive` does not
  exist in 0.8.13, so it uses `c.active`. `actuatorsOutput.accel` is the clipped
  accel.
- Follow check (`FollowMonitor` in `carcontroller.py`, identical to upstream's
  time-based version):
  - It is fed each frame with the T sent, `CS.leaf_feedback`, `c.active`,
    `evaluate = vEgo > 2 and not gasPressed and not brakePressed`, and `now`.
  - It keeps (time, T) history and compares the newest T sent at or before
    `now - 0.16 s` against the feedback T. It faults once that T exceeds the
    feedback by more than 60 continuously for 1.0 s, i.e. the car slows less than
    asked.
  - It skips when the history doesn't reach back 0.16 s yet, while not evaluating,
    with no feedback, or while the brake marker is in the history. A fault latches
    until long goes inactive.
  - `now is None` (no clock) resets the monitor like inactive and returns False,
    so the controller can never crash on a missing clock. `sec_since_boot()`
    always returns a float here, so the caller has no missing value to pass.
  - **Time source:** `common.realtime.sec_since_boot()`, called in the controller.
    0.8.13's `CI.apply(CC)` passes no timestamp, so the monitor takes this tree's
    monotonic clock, the same one controlsd's `Ratekeeper` uses. `frame * DT_CTRL`
    would assume 100 Hz, and that assumption is exactly what the time-based
    monitor removes.
- `carstate.py`:
  - With long on, `PROPULSION_FEEDBACK.D` is added (100 Hz check) to the bus-0
    parser for the Leaf and to the bus-1 parser for the Leaf IC. Lateral-only
    cars' parsers are unchanged.
  - `leaf_feedback = (2067.1 - D) / 0.796`.
  - This CANParser has no per-message timestamps, so a stale `0x180` shows up as
    that parser's `can_valid` going False, and `leaf_feedback` is then None.
- 0.8.13's `CarState` has no `accFaulted` field. `interface.update` instead adds
  `EventName.accFaulted` when `CS.gw_follow_fault` is set. That is an
  IMMEDIATE_DISABLE "Cruise Faulted" alert, the closest equivalent.
- `interface.py`: the opt-in, the heartbeat and `0x180` gates, `FLAG_NISSAN_LEAF_LONG`, and
  `get_pid_accel_limits` of (-3.5, 0.79). `pcmCruise` stays at the default
  (True) and `autoResumeSng` is not touched. The Altima's literal
  `safetyParam = 1` became `Panda.FLAG_NISSAN_ALT_EPS_BUS`, with the same value.
- `selfdrive/car/tests/test_nissan_leaf_gw.py` (new). It checks:
  - the toggle × heartbeat-bus matrix, `pcmCruise`, and the safety flags;
  - a fingerprint with no bus-2 key;
  - that the other Nissans get no long;
  - the PID limits and the stock golden frames;
  - the controller's frames on bus 2, decoded;
  - no frames without long;
  - `0x180` required on the harness's bus (0 for Leaf, 1 for Leaf IC);
  - `FollowMonitor`'s rules at 100 Hz and 50 Hz, mirroring `test_leaf_gw_long.py`:
    lag in time, window, latch, reset, and each skip;
  - end to end through `CarInterface.update`/`apply`, with real bus-0 CAN
    including `0x180`:
    - `accFaulted` fires when the car slows less than asked;
    - the clock is patched, so the fault time is checked at 100 Hz and at 50 Hz,
      and must be 1.1–1.3 s in both;
    - it does not fire when the car follows or slows more.

  With `FollowMonitor.update` patched to always return False, the fault test
  fails, so the test proves the monitor is what raises the event.

  When `leaf_gw_long.py` has been copied into `selfdrive/car/nissan/`, one more
  test compares against the spec:
  - every constant;
  - the full packer input space;
  - the controller's frames against `gateway_longitudinal` + `pack_*`;
  - `FollowMonitor` against `leaf_gw_long.FollowMonitor` over a seeded random
    drive with jittered 5–30 ms steps, which does reach the fault path. Without that copy it skips.

`panda.patch`:
- `board/safety/safety_nissan.h`:
  - `NISSAN_PARAM_LEAF_LONG = 2` adds its own TX list (base plus `0x2B0`/`0x1C3`
    on bus 2) and its own rx checks (base plus `{0x5ff, 2, 8, expected_timestep = 20000U}`,
    which is 50 Hz).
  - Explicit bounds, because this panda has no `LongitudinalLimits`.
    `long_allowed = controls_allowed && !gas_pressed_prev`.
  - `0x2B0`: `command = (d2 << 4) | (d1 & 0xF)`. It must be in 2272..3415 when
    allowed, and exactly 2595 otherwise. T counts up with deceleration, so 3415
    (the brake marker) is the ceiling.
  - `0x1C3`: pressure must be ≤ 659, and 0 when not allowed.
  - The checks run only in LONG mode. A violation drops `controls_allowed`, like
    every other violation in this file.
  - Fixes `nissan_alt_eps = param ? 1 : 0` to `GET_FLAG(param, 1)`. The old line
    would have put a LONG-flagged Leaf on the Altima's EPS bus.
- `python/__init__.py`: `FLAG_NISSAN_ALT_EPS_BUS = 1`, `FLAG_NISSAN_LEAF_LONG = 2`.
- `tests/safety/test_nissan.py`: a new `TestNissanLeafLongSafety`, which also
  inherits every Leaf/Nissan test under the LONG flag. It covers:
  - gas and brake sweeps with their boundaries;
  - disengaged → inactive only;
  - gas pressed blocks;
  - stock golden frames;
  - long frames only on bus 2;
  - heartbeat required (`addr_checks_valid`), and only on bus 2;
  - heartbeat lost → `safety_tick` drops `controls_allowed`;
  - no long TX without the flag, or with the Altima flag.

  `common.py` adds the class to the existing Nissan exception in
  `test_tx_hook_on_wrong_safety_mode`.

`opendbc.patch`: `BO_ 384 PROPULSION_FEEDBACK` (`D : 23|12@0-`) and
`BO_ 1535 LEAF_GW_HEARTBEAT` in `nissan_leaf_2018.dbc`, with the same signals and
`CM_` comments as upstream. This opendbc has no Nissan generator, so the DBC is
edited directly. The old `process_dbc` compiles it.

## Opt-in: `DisableRadar`, default off

0.8.13's longitudinal opt-in is the **"openpilot Longitudinal Control"** toggle,
param `DisableRadar`. Honda Bosch and Hyundai read it the same way, with
`Params().get_bool("DisableRadar")` in `get_params`. The UI shows it only when
`DisableRadar_Allow` is set, and `manager.py` deletes `DisableRadar` on every
start unless `DisableRadar_Allow` is set. So it is off by default and needs two
deliberate steps.

Long is on only when all four of these hold:
- the car is a Leaf or Leaf IC;
- `0x5FF` is in `fingerprint.get(2, {})`;
- `0x180` is in `fingerprint.get(0 if Leaf else 1, {})`;
- `DisableRadar` is set.

`get_params(candidate, fingerprint, car_fw)` has no flag argument in this
version, so a Params read is the idiomatic route. The `disable_radar`,
`experimental_long` and alpha-long arguments came later.

## Deviations from the upstream patches

- **`ALLOW_DEBUG` gate.** Panda honours the LONG flag only in `ALLOW_DEBUG`
  builds, as this panda does for Hyundai long. Without it, the flag is ignored and
  the Leaf stays lateral-only. Non-`RELEASE` builds (what a C2 dev branch flashes)
  have `ALLOW_DEBUG`.
- **The toggle's description is wrong for the Leaf.** It still says it "will
  disable the car's radar … this disables AEB". That is untrue here: nothing is
  disabled, and AEB stays. The shared UI text was left as it is.
- **Fixed fingerprint.** RetroPilot `c2` hard-codes
  `fixed_fingerprint = "RETROPILOT RETROFIT"` in `selfdrive/car/car_helpers.py`, so
  no Nissan is ever selected on a stock `c2` install. The port works once that is
  changed back to real fingerprinting. The patch does not touch it.
- **`stopAccel`.** Upstream sets `ret.stopAccel = -2.0`. 0.8.13's
  `get_std_params` already defaults to -2.0, so the line was left out.
- **No counters or checksums.** As upstream, panda does not check the heartbeat's
  checksum or counter, or the frames' inverse copy (the gateway validates those).
- **Fingerprint window.** 0.8.13 ends fingerprinting about 10 frames (0.1 s)
  after one candidate remains. The heartbeat is 50 Hz so that window sees it.

## Tests

Environment: `nix-shell` with the expression below (nixos-23.05: Python 3.11.5,
Cython 0.29.34, numpy 1.24, pycapnp 1.1). Newer channels fail for two reasons:
nixos-24.05 marks pycapnp broken, and numpy 2 breaks
`common/transformations/transformations.pyx`. The compiled extensions are built
with the small SConstruct below, not openpilot's own, which needs Qt, OpenCL and
the device toolchain. Run with `HOME` pointed at a scratch directory, because
`Params()` writes to `$HOME/.comma/params`.

```nix
# shell.nix
{ pkgs ? import (builtins.fetchTarball "https://github.com/NixOS/nixpkgs/archive/70bdadeb94ffc8806c0570eb5c2695ad29f0e421.tar.gz") {} }:
pkgs.mkShell {
  hardeningDisable = [ "fortify" ];
  packages = [
    pkgs.clang pkgs.capnproto pkgs.zeromq pkgs.libusb1 pkgs.eigen pkgs.git
    (pkgs.python311.withPackages (ps: with ps; [
      numpy cython pycapnp cffi pytest parameterized crcmod pyzmq libusb1 pyserial
      hypothesis tqdm setproctitle psutil requests jinja2 pyyaml smbus2 pycryptodome
    ]))
    pkgs.scons  # after python so 3.11 wins on PATH; scons runs on its own interpreter, hence PY=
  ];
}
```

```python
# SConstruct: PY=$(command -v python3) scons -Q -C <openpilot root> -f SConstruct --site-dir=<root>/site_scons -j8
import os, subprocess
PY = os.environ["PY"]
pyinc, npinc = subprocess.check_output([PY, "-c", "import sysconfig,numpy;print(sysconfig.get_paths()['include']);print(numpy.get_include())"], encoding="utf8").split()
env = Environment(ENV=os.environ, CC="clang", CXX="clang++",
  CCFLAGS=["-g", "-fPIC", "-O2", "-Wno-unused", "-Wno-deprecated-declarations"],
  CFLAGS="-std=gnu11", CXXFLAGS=["-std=c++17", "-include", "cstdint"],
  CPPPATH=["#", "#cereal", "#cereal/messaging", "#opendbc/can", "#third_party/json11", "#third_party", pyinc],
  LIBPATH=["#opendbc/can", "#third_party/json11"], CYTHONCFILESUFFIX=".cpp", tools=["default", "cython"])
envCython = env.Clone(); envCython["CPPPATH"] += [npinc]
envCython["CCFLAGS"] += ["-Wno-#warnings", "-Wno-shadow"]; envCython["LINKFLAGS"] = ["-pthread", "-shared"]; envCython["LIBS"] = []
schema = ["log.capnp", "car.capnp", "legacy.capnp"]
env.Command(["cereal/gen/c/include/c++.capnp.h"], [], "mkdir -p cereal/gen/c/include && touch $TARGETS")
env.Command([f"cereal/gen/cpp/{s}.c++" for s in schema] + [f"cereal/gen/cpp/{s}.h" for s in schema],
            [f"cereal/{s}" for s in schema], "capnpc --src-prefix=cereal $SOURCES -o c++:cereal/gen/cpp/")
cereal = env.Library("cereal/cereal", [env.SharedObject(f"cereal/gen/cpp/{s}.c++") for s in schema])
dbcs = [env.Command(f"opendbc/can/dbc_out/{x[:-4]}.cc", [f"opendbc/{x}", "opendbc/can/dbc_template.cc"],
                    f"PYTHONPATH=. {PY} opendbc/can/process_dbc.py opendbc $TARGET")
        for x in sorted(os.listdir(Dir("#opendbc").abspath)) if x.endswith(".dbc")]
libdbc = env.SharedLibrary("opendbc/can/libdbc", [f"opendbc/can/{f}" for f in ("dbc.cc", "parser.cc", "packer.cc", "common.cc")] + dbcs, LIBS=[cereal, "capnp", "kj"])
lenv = envCython.Clone(); lenv["LINKFLAGS"] += [libdbc[0].get_labspath(), "-Wl,-rpath," + Dir("#opendbc/can").abspath]
for p in ("parser_pyx", "packer_pyx"):
  lenv.Depends(lenv.Program(f"opendbc/can/{p}.so", f"opendbc/can/{p}.pyx"), libdbc)
json11 = env.Library("third_party/json11/json11", ["third_party/json11/json11.cpp"])
common = env.Library("selfdrive/common/common", [f"selfdrive/common/{f}" for f in ("params.cc", "swaglog.cc", "util.cc")])
envCython.Program("common/clock.so", "common/clock.pyx")
envCython.Program("common/params_pyx.so", "common/params_pyx.pyx", LIBS=[common, json11, "zmq"])
services_h = env.Command("cereal/services.h", "cereal/services.py", f"{PY} cereal/services.py > $TARGET")
messaging = env.Library("cereal/messaging", [env.SharedObject(f"cereal/messaging/{f}.cc") for f in ("messaging", "impl_zmq", "impl_msgq", "msgq", "socketmaster")])
env.Depends("cereal/messaging/impl_zmq.cc", services_h)
envCython.Program("cereal/messaging/messaging_pyx.so", "cereal/messaging/messaging_pyx.pyx", LIBS=[messaging, common, json11, "zmq"])
c2c = env.Library("selfdrive/boardd/can_list_to_can_capnp", ["selfdrive/boardd/can_list_to_can_capnp.cc"])
envCython.Program("selfdrive/boardd/boardd_api_impl.so", "selfdrive/boardd/boardd_api_impl.pyx", LIBS=[c2c, cereal, "capnp", "kj"])
envCython.Program("common/kalman/simple_kalman_impl.so", "common/kalman/simple_kalman_impl.pyx")
env.Library("common/transformations/transformations", ["common/transformations/orientation.cc", "common/transformations/coordinates.cc"])
envCython.Program("common/transformations/transformations.so", "common/transformations/transformations.pyx")
```

Commands, from the openpilot root inside that shell:

```
PY=$(command -v python3) scons -Q -C . -f /path/SConstruct --site-dir=$PWD/site_scons -j8
scons -Q -C panda/tests/safety -f SConscript             # libpandasafety.so
export HOME=$(mktemp -d) PYTHONPATH=$PWD
cp /path/leaf-gw/openpilot/leaf_gw_long.py /path/leaf-gw/openpilot/test_leaf_gw_long.py selfdrive/car/nissan/
(cd selfdrive/car/nissan && python3 test_leaf_gw_long.py)
python3 -m pytest -q panda/tests/safety/test_nissan.py
python3 -m pytest -q selfdrive/car/tests/test_nissan_leaf_gw.py
python3 -m pytest -q selfdrive/car/tests/test_car_interfaces.py -k NISSAN
```

| suite | before (base) | after |
|---|---|---|
| `test_leaf_gw_long.py` (standalone) | pass | pass |
| `panda/tests/safety/test_nissan.py` | 42 passed | 72 passed |
| `panda/tests/safety` (all) | 537 passed, 240 skipped, 1 failed | 567 passed, 240 skipped, 1 failed |
| `selfdrive/car/tests/test_nissan_leaf_gw.py` | n/a | 12 passed (11 + 1 skipped without the spec copy) |
| `selfdrive/car/tests/test_car_interfaces.py` | 157 passed (5 NISSAN) | 157 passed (5 NISSAN) |

- The one failure, in both columns, is `test_toyota.py::TestToyotaSafety::test_torque_measurements`.
  It is unrelated and was not investigated.
- `openpilot/check-forks.sh retropilot` (via `fork.sh`) PASSes with these
  counts. With a deliberately wrong spec copy (`PROPILOT_INACTIVE_RAW = 2596`),
  `fork.sh` exits 1: `test_leaf_gw_long.py` fails, and the spec cross-check in
  `test_nissan_leaf_gw.py` fails. That run was before the follow check, when the
  file had 8 tests.
- The new tests fail on the old code (measured before the T-layout update). Run against the unpatched panda C (with only
  the test and flag files applied), `test_nissan.py` gives 15 failed / 57 passed.
  The inherited Leaf tests fail too, because the old `param ? 1 : 0` turns on
  alt-EPS. `test_nissan_leaf_gw.py` fails at import.
- The panda firmware (F4 + H7, DEBUG, `-Wall -Wextra -Werror`) builds with the
  patch, using `gcc-arm-embedded`.
- MISRA: no new violations (cppcheck e1cff1d1, as `Dockerfile.panda` pins; `tests/misra/test_misra.sh` default and with `-DALLOW_DEBUG`).

Not run:
- Process replay and `test_models.py`. They need routes, and no Leaf route has
  the gateway.
- `controlsd` end to end. The longitudinal MPC needs acados.
- Anything on a car.
