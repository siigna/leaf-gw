#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md.
#
# check-forks.sh hook for FlowPilot: fork.sh <superproject-worktree> <leaf-gw/openpilot dir>
# Adds panda/opendbc/cereal worktrees at their submodule pins, applies the three
# patches, copies the leaf_gw_long spec in, then builds and runs the nissan suites
# inside shell.nix. Prints one line per suite; exit 0 = all passed. Removes the
# submodule worktrees it made. No `set -e`: every suite reports.

here=$(cd "$(dirname "$0")" && pwd)

if [ "$1" = --inner ]; then
  # inside shell.nix: build the host test libs, then run the suites
  wt=$2
  export PYTHONPATH=$wt
  cp "$here/SConstruct.test" "$wt/" || exit 1
  out=$(cd "$wt" && scons -Q -j8 -f SConstruct.test common/params_pyx.so opendbc/can/ \
          cereal/messaging/messaging_pyx.so common/clock.so common/kalman/simple_kalman_impl.so \
          selfdrive/boardd/boardd_api_impl.so 2>&1) || { tail -20 <<<"$out"; echo "FAIL build [SConstruct.test]"; exit 1; }
  out=$(cd "$wt/panda/tests/safety" && gcc -w -shared -fPIC -nostdlib -fno-builtin -std=gnu11 -I. -I../../board \
          test.c -o libpandasafety.so 2>&1) || { echo "$out"; echo "FAIL build [libpandasafety]"; exit 1; }

  ok=0
  home=$(mktemp -d)   # Params lives in $HOME/.flowdrive/params
  out=$(cd "$wt/selfdrive/car/nissan" && HOME=$home python3 -B test_leaf_gw_long.py 2>&1) || ok=1
  echo "$(tail -1 <<<"$out")   [test_leaf_gw_long.py]"
  for t in panda/tests/safety/test_nissan.py "selfdrive/car/tests/test_car_interfaces.py -k nissan" selfdrive/car/nissan/tests; do
    out=$(cd "$wt" && HOME=$home python3 -m pytest -q -p no:cacheprovider $t 2>&1) || ok=1
    echo "$(tail -1 <<<"$out")   [$t]"
  done
  rm -rf "$home"
  exit $ok
fi

wt=$1; op=$2
[ -d "$wt/.git" ] || [ -f "$wt/.git" ] || { echo "FAIL not a worktree: $wt"; exit 1; }
SRC=${SRC:-$HOME/src/github}
# submodule  pin (59f5cf3f's gitlinks)
SUBS=(
  "panda   f120999e19fed7208534ae74b542b5cca6bafeaa"
  "opendbc 7d966b5c24db3c4fe49b379511264ebff7a57e91"
  "cereal  92f47d2efb61fcc348c39ebe2fc6a5e73570b2d0"
)

made=()
cleanup() {
  for n in "${made[@]}"; do
    rm -rf "${wt:?}/${n:?}" && git -C "$SRC/flow-drive-ai/$n" worktree prune
  done
}
trap cleanup EXIT

for row in "${SUBS[@]}"; do
  read -r n pin <<<"$row"
  clone=$SRC/flow-drive-ai/$n
  [ -d "$clone/.git" ] || git clone -q "https://github.com/flow-drive-ai/$n" "$clone" || { echo "FAIL clone $n"; exit 1; }
  git -C "$clone" cat-file -e "$pin^{commit}" 2>/dev/null || git -C "$clone" fetch -q origin "$pin" || { echo "FAIL fetch $n $pin"; exit 1; }
  rmdir "${wt:?}/${n:?}" 2>/dev/null   # empty, uninitialised submodule dir
  git -C "$clone" worktree add -q --detach "$wt/$n" "$pin" || { echo "FAIL worktree $n $pin"; exit 1; }
  made+=("$n")
done

for p in ".:flowpilot-leaf-gw-long.patch" "panda:panda.patch" "opendbc:opendbc.patch"; do
  dir=${p%%:*}; f=${p#*:}
  git -C "$wt/$dir" apply "$here/$f" || { echo "FAIL apply $f"; exit 1; }
  echo "applied $f"
done
cp "$op/leaf_gw_long.py" "$op/test_leaf_gw_long.py" "$wt/selfdrive/car/nissan/" || exit 1

nix-shell "$here/shell.nix" --run "$(printf '%q ' "$here/fork.sh" --inner "$wt")"
