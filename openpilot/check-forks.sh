#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md.
#
# Apply each fork's leaf-gw patch set to a fresh worktree at its pinned commit
# and run the nissan suites. Run inside the dev shell:
#   nix develop .#openpilot --command openpilot/check-forks.sh [--latest] [fork...]
# --latest tests each fork's current branch head instead of the pin (drift check).
# Clones live in $SRC/<owner>/<repo> (default ~/src/github); missing ones are cloned.
# No `set -e`: one failing fork must not hide the others.
#
# A fork whose tree doesn't fit the default (one opendbc-style repo) ships
# openpilot/<patch-dir>/fork.sh. It is run as `fork.sh <worktree> <openpilot-dir>`
# after the superproject worktree exists at the pinned rev, and owns everything
# else: submodule worktrees, applying its patches, its own nix env, building,
# running tests (printing one summary line per suite) and cleaning up what it
# created. Exit 0 = PASS.

here=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$HOME/src/github}
latest=0
want=()
for a in "$@"; do
  case $a in --latest) latest=1 ;; *) want+=("$a") ;; esac
done

# name  owner/repo  branch  pin  patch-dir  opendbc-root-inside-repo
FORKS=(
  "opendbc    commaai/opendbc       master     341fb3d9 .          ."
  "sunnypilot sunnypilot/opendbc    master     11c61f3e sunnypilot ."
  "starpilot  StarPilotHQ/StarPilot StarPilot  0b2061d  starpilot  opendbc_repo"
  "retropilot RetroPilot/openpilot  c2         b9a942ef retropilot ."
  "flowpilot  flowdriveai/flowpilot master     59f5cf3f flowpilot  ."
)

fail=0
for row in "${FORKS[@]}"; do
  read -r name repo branch pin pdir root <<<"$row"
  if [ ${#want[@]} -gt 0 ] && [[ ! " ${want[*]} " =~ " $name " ]]; then continue; fi
  echo "=== $name ($repo)"
  clone=$SRC/$repo
  [ -d "$clone/.git" ] || git clone -q "https://github.com/$repo" "$clone" || { echo "  FAIL clone"; fail=1; continue; }
  git -C "$clone" fetch -q origin "$branch" || { echo "  FAIL fetch"; fail=1; continue; }
  rev=$pin; [ $latest = 1 ] && rev=$(git -C "$clone" rev-parse FETCH_HEAD)
  wt=$(mktemp -d /tmp/leafgw-$name.XXXXXX)
  git -C "$clone" worktree add -q --detach "$wt" "$rev" || { echo "  FAIL worktree $rev"; fail=1; continue; }
  echo "  at $(git -C "$wt" log -1 --format='%h %cs %s')"

  ok=1
  if [ -x "$here/$pdir/fork.sh" ]; then
    "$here/$pdir/fork.sh" "$wt" "$here" 2>&1 | sed 's/^/  /'
    [ "${PIPESTATUS[0]}" = 0 ] || ok=0
    rm -rf "$wt" && git -C "$clone" worktree prune
    if [ $ok = 1 ]; then echo "  PASS"; else echo "  FAIL"; fail=1; fi
    continue
  fi
  shopt -s nullglob
  patches=("$here/$pdir"/*.patch)
  [ ${#patches[@]} -gt 0 ] || { echo "  FAIL no patches in openpilot/$pdir"; ok=0; }
  for p in "${patches[@]}"; do
    # from the repo root: git apply inside a subdirectory silently skips paths
    if git -C "$wt" apply "$p"; then echo "  applied $(basename "$p")"; else echo "  FAIL apply $(basename "$p")"; ok=0; fi
  done

  if [ $ok = 1 ]; then
    od=$wt/$root
    cp "$here/leaf_gw_long.py" "$here/test_leaf_gw_long.py" "$od/opendbc/car/nissan/"
    out=$(cd "$od/opendbc/car/nissan" && python3 test_leaf_gw_long.py 2>&1) || ok=0
    echo "  $(tail -1 <<<"$out")   [test_leaf_gw_long.py]"
    tests=(opendbc/safety/tests/test_nissan.py)
    for d in opendbc/car/nissan/tests opendbc/sunnypilot/car/nissan; do [ -d "$od/$d" ] && tests+=("$d"); done
    # vendored trees (StarPilot) import cereal/openpilot.* from the repo root and build libsafety with scons
    pp=$od:$wt
    if [ -f "$od/opendbc/safety/tests/libsafety/SConscript" ]; then
      (cd "$od" && scons -Q opendbc/safety/tests/libsafety/libsafety.so >/dev/null) || { echo "  FAIL scons libsafety"; ok=0; }
    fi
    for t in "${tests[*]}" "opendbc/car/tests/test_car_interfaces.py -k nissan"; do
      out=$(cd "$od" && PYTHONPATH=$pp python3 -m pytest -q -p no:cacheprovider $t 2>&1) || ok=0
      echo "  $(tail -1 <<<"$out")   [$t]"
    done
  fi

  rm -rf "$wt" && git -C "$clone" worktree prune   # throwaway: holds only our applied patches
  if [ $ok = 1 ]; then echo "  PASS"; else echo "  FAIL"; fail=1; fi
done
exit $fail
