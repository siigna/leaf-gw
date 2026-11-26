#!/usr/bin/env bash
# leaf-gw board, schematic-level checks (SPEC.md phase 2). Run inside
# `nix develop .#hardware`; `nix flake check` runs it as `board-schematic`.
#
#   ./check.sh            build + check; fails if out/ is stale
#   ./check.sh --update   rebuild and rewrite out/ first
#
# No `set -e`: every stage runs and reports, the exit code says if any failed.
cd "$(dirname "$0")" || exit 1
here=$PWD
export PYTHONDONTWRITEBYTECODE=1
if [ -z "${KICAD9_SYMBOL_DIR:-}" ] || [ -z "${KICAD9_FOOTPRINT_DIR:-}" ]; then
  echo "KICAD9_SYMBOL_DIR/KICAD9_FOOTPRINT_DIR unset: run inside 'nix develop .#hardware'" >&2
  exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
stage() { echo "== $1"; }

stage "schematic build + SKiDL ERC"
# SKiDL drops .erc/.log/_sklib.py in its cwd: keep them out of the tree
(cd "$tmp" && python3 "$here/schematic/board.py" "$tmp/out" 2>"$tmp/skidl.log") || { cat "$tmp/skidl.log"; fail=1; }
grep -E "^ERC (WARNING|ERROR)" "$tmp/skidl.log"

if [ "${1:-}" = "--update" ]; then
  mkdir -p out && cp "$tmp"/out/* out/
fi

stage "committed out/ matches the schematic"
diff -r out "$tmp/out" >/dev/null || { diff -ru out "$tmp/out" | head -40; echo "out/ is stale: ./check.sh --update"; fail=1; }

stage "safety-net checks"
python3 checks/safety.py out/leaf_gw.net || fail=1

stage "BOM + footprint checks"
python3 checks/bom.py out/leaf_gw.net out/bom_jlcpcb.csv || fail=1

stage "mutation tests (the checks bite)"
python3 checks/test_mutations.py 2>&1 | tail -3
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

[ $fail -eq 0 ] && echo "board-schematic: all checks passed" || echo "board-schematic: FAILED"
exit $fail
