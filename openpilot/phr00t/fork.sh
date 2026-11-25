#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md.
#
# check-forks.sh hook for phr00t/flowpilot (the base of jagheterfredrik and of the "tarball" install; panda, opendbc and
# cereal are vendored): fork.sh <superproject-worktree> <leaf-gw/openpilot dir>
# Applies the patch, copies the leaf_gw_long spec in, then builds and runs the
# nissan suites inside shell.nix. Prints one line per suite; exit 0 = all passed.
# No `set -e`: every suite reports.

here=$(cd "$(dirname "$0")" && pwd)

if [ "$1" = --inner ]; then
  # inside shell.nix: build the host test libs, then run the suites
  wt=$2
  export PYTHONPATH=$wt
  cp "$here/SConstruct.test" "$wt/" || exit 1
  out=$(cd "$wt" && scons -Q -j8 -f SConstruct.test common/params_pyx.so opendbc/can/ \
          cereal/messaging/messaging_pyx.so common/clock.so common/kalman/simple_kalman_impl.so \
          selfdrive/boardd/boardd_api_impl.so common/transformations/transformations.so 2>&1) \
    || { tail -20 <<<"$out"; echo "FAIL build [SConstruct.test]"; exit 1; }
  out=$(cd "$wt/panda/tests/libpanda" && gcc -shared -fPIC -nostdlib -fno-builtin -std=gnu11 -Wno-pointer-to-int-cast \
          -I. -I../../board panda.c -o libpanda.so 2>&1) || { echo "$out"; echo "FAIL build [libpanda]"; exit 1; }

  # test harness only: common/path.py hardcodes the Android app dir as BASEDIR, which
  # selfdrive/car uses to discover brands; point it at the worktree for pytest
  tmp=$(mktemp -d)
  cat > "$tmp/leafgw_hostroot.py" <<EOF
import common.path
common.path.flowpilot_root = lambda: "$wt"
EOF
  export PYTHONPATH=$wt:$tmp HOME=$tmp   # Params lives in \$HOME/.flowdrive/params

  ok=0
  out=$(cd "$wt/selfdrive/car/nissan" && python3 -B test_leaf_gw_long.py 2>&1) || ok=1
  echo "$(tail -1 <<<"$out")   [test_leaf_gw_long.py]"
  for t in panda/tests/safety/test_nissan.py "selfdrive/car/tests/test_car_interfaces.py -k nissan" selfdrive/car/nissan/tests; do
    out=$(cd "$wt" && python3 -m pytest -q -p no:cacheprovider -p leafgw_hostroot $t 2>&1) || ok=1
    echo "$(grep -E " (passed|failed|error)" <<<"$out" | tail -1)   [$t]"   # libpanda prints "Temporary fault" lines after the summary
  done
  rm -rf "$tmp"
  exit $ok
fi

wt=$1; op=$2
[ -e "$wt/.git" ] || { echo "FAIL not a worktree: $wt"; exit 1; }
git -C "$wt" apply "$here/phr00t-leaf-gw-long.patch" || { echo "FAIL apply phr00t-leaf-gw-long.patch"; exit 1; }
echo "applied phr00t-leaf-gw-long.patch"
cp "$op/leaf_gw_long.py" "$op/test_leaf_gw_long.py" "$wt/selfdrive/car/nissan/" || exit 1

nix-shell "$here/shell.nix" --run "$(printf '%q ' "$here/fork.sh" --inner "$wt")"
