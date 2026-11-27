#!/usr/bin/env bash
# leaf-gw enclosure checks (SPEC.md phase 6). Run inside `nix develop .#enclosure`
# (all stages) or `.#hardware` (no slicer, no plug: those stages skip);
# `nix flake check` runs it as `enclosure`.
#
#   ./check.sh            check the committed case outputs
#   ./check.sh --update   regenerate out/ (part hulls when the 3D models are
#                         there, STLs, 3MFs when orca-slicer is, renders), then check
#
# No `set -e`: every stage runs and reports; a missing tool skips and says so,
# a finding fails; the exit code says if any stage failed.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
command -v kicad-python >/dev/null || { echo "kicad-python missing: run inside 'nix develop .#enclosure'" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
stage() { echo "== $1"; }
have_models() { [ -n "${KICAD10_3DMODEL_DIR:-}" ] && [ -d "$KICAD10_3DMODEL_DIR" ] && command -v kicad-cli >/dev/null; }
have_slicer() { command -v orca-slicer >/dev/null; }

if [ "${1:-}" = "--update" ]; then
  stage "regenerate out/"
  if have_models; then kicad-python board3d.py || fail=1; else echo "SKIP part hulls: no KiCad 3D models (KICAD10_3DMODEL_DIR)"; fi
  kicad-python case.py >/dev/null || fail=1
  if have_slicer; then kicad-python slicer.py build >/dev/null || fail=1; else echo "SKIP 3MF: no orca-slicer"; fi
  kicad-python render.py || fail=1
fi

stage "part hulls match the board's 3D models"
if have_models; then
  kicad-python board3d.py "$tmp/board_parts.json" >/dev/null || fail=1
  cmp -s out/board_parts.json "$tmp/board_parts.json" || { echo "out/board_parts.json is stale: ./check.sh --update"; fail=1; }
else
  echo "SKIP: no KiCad 3D models (KICAD10_3DMODEL_DIR); using the committed out/board_parts.json"
fi

stage "STLs match case.py"
kicad-python case.py "$tmp/stl" >/dev/null || fail=1
for p in tray lid; do
  cmp -s "out/$p.stl" "$tmp/stl/$p.stl" || { echo "out/$p.stl is stale: ./check.sh --update"; fail=1; }
done

stage "geometry checks: clearance, seating, walls, openings, printability, plugs"
kicad-python checks.py || fail=1

stage "mutation tests (the geometry checks bite)"
kicad-python test_mutations.py 2>&1 | grep -E "^(FAIL|skip)|mutations,"; [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

stage "3MFs: supports off, the right filament, the current STLs, and they slice (OrcaSlicer CLI)"
if have_slicer; then
  kicad-python slicer.py check || fail=1
  stage "slicer check bites: a 3MF with supports on and one with stale objects must fail"
  kicad-python slicer.py selftest || fail=1
else
  echo "SKIP: no orca-slicer (nix develop .#enclosure)"
fi

[ $fail -eq 0 ] && echo "enclosure: all checks passed" || echo "enclosure: FAILED"
exit $fail
