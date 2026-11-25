#!/usr/bin/env bash
# check-forks.sh hook for RetroPilot c2: fork.sh <superproject-worktree> <leaf-gw/openpilot dir>
# Adds panda/opendbc/cereal worktrees at their pins, applies the three patches, builds
# the python extensions the tests need, and runs the nissan suites in ./shell.nix.
# No `set -e`: every suite reports. Exit 0 only if all nissan suites pass.
wt=$1 op=$2
here=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$HOME/src/github}
SUBS="panda:9e6d47f63675d5a45170ae7972c24412034dc136 opendbc:6b90fafe59e81822bfae58e4ecb080248e9de40d cereal:a7193d0f0e472f90709e6671ce6ff01d1534c2a5"
ok=1
created=()

cleanup() {
  for r in "${created[@]}"; do rm -rf "${wt:?}/${r:?}"; git -C "$SRC/RetroPilot/$r" worktree prune; done
}
trap cleanup EXIT

for s in $SUBS; do
  r=${s%%:*} pin=${s#*:} clone=$SRC/RetroPilot/${s%%:*}
  [ -d "$clone/.git" ] || git clone -q --filter=blob:none "https://github.com/RetroPilot/$r.git" "$clone" || { echo "FAIL clone $r"; exit 1; }
  git -C "$clone" cat-file -e "$pin^{commit}" 2>/dev/null || git -C "$clone" fetch -q origin "$pin" || { echo "FAIL fetch $r $pin"; exit 1; }
  rmdir "$wt/$r" 2>/dev/null   # empty gitlink dir from the superproject checkout
  git -C "$clone" worktree add -q --detach "$wt/$r" "$pin" || { echo "FAIL worktree $r"; exit 1; }
  created+=("$r")
done

# from each repo root: git apply inside a subdirectory silently skips paths
for p in openpilot:. panda:panda opendbc:opendbc; do
  if git -C "$wt/${p#*:}" apply "$here/${p%%:*}.patch"; then echo "applied ${p%%:*}.patch"; else echo "FAIL apply ${p%%:*}.patch"; exit 1; fi
done
cp "$op/leaf_gw_long.py" "$op/test_leaf_gw_long.py" "$wt/selfdrive/car/nissan/"

# Minimal build of the extensions the car/panda tests import (openpilot's own
# SConstruct needs Qt/OpenCL/device toolchains).
sc=$(mktemp /tmp/leafgw-retropilot-sconstruct.XXXXXX)
cat > "$sc" <<'EOF'
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
EOF

home=$(mktemp -d /tmp/leafgw-retropilot-home.XXXXXX)   # Params() writes $HOME/.comma/params
WT=$wt SC=$sc HOME=$home nix-shell "$here/shell.nix" --run '
  cd "$WT" || exit 1
  PY=$(command -v python3) scons -Q -C "$WT" -f "$SC" --site-dir="$WT/site_scons" -j"$(nproc)" >"$HOME/build.log" 2>&1 \
    || { tail -20 "$HOME/build.log"; echo "FAIL scons extensions"; exit 1; }
  scons -Q -C panda/tests/safety -f SConscript >>"$HOME/build.log" 2>&1 || { echo "FAIL scons libpandasafety"; exit 1; }
  export PYTHONPATH=$WT
  rc=0
  out=$(cd selfdrive/car/nissan && python3 test_leaf_gw_long.py 2>&1) || rc=1
  echo "$(tail -1 <<<"$out")   [test_leaf_gw_long.py]"
  for t in panda/tests/safety/test_nissan.py selfdrive/car/tests/test_nissan_leaf_gw.py "selfdrive/car/tests/test_car_interfaces.py -k NISSAN"; do
    out=$(python3 -m pytest -q -p no:cacheprovider $t 2>&1) || rc=1
    echo "$(tail -1 <<<"$out")   [$t]"
  done
  exit $rc
' || ok=0
rm -rf "$home" "$sc"
[ $ok = 1 ]
