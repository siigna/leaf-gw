#!/usr/bin/env bash
# leaf-gw board, PCB-level checks (SPEC.md phase 3). Run inside
# `nix develop .#hardware`; `nix flake check` runs it as `board-layout`.
#
#   ./check_layout.sh             check the committed layout and fab outputs
#   ./check_layout.sh --update    rebuild layout/leaf_gw.kicad_pcb (freerouting,
#                                 about 40 minutes), fab outputs and renders first
#   ./check_layout.sh --rebuild   also rebuild from scratch into a temp dir and
#                                 require the rebuilt board to pass DRC and every
#                                 layout check (freerouting isn't deterministic, so
#                                 the files differ byte for byte; validity is what
#                                 has to reproduce). Keeps it at /tmp/lgw/rebuilt/
#                                 (or $LGW_REBUILT)
#
# No `set -e`: every stage runs and reports, the exit code says if any failed.
cd "$(dirname "$0")" || exit 1
here=$PWD
export PYTHONDONTWRITEBYTECODE=1
for t in kicad-python kicad-cli; do
  command -v $t >/dev/null || { echo "$t missing: run inside 'nix develop .#hardware'" >&2; exit 1; }
done
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0
stage() { echo "== $1"; }
pcb=layout/leaf_gw.kicad_pcb

if [ "${1:-}" = "--update" ]; then
  stage "rebuild layout (placement, critical routes, freerouting, zones)"
  (cd layout && kicad-python build.py) || fail=1
  stage "fab outputs and renders"
  (cd layout && kicad-python fab.py && ./render.sh) || fail=1
fi

stage "impedance and logo self-checks"
(cd layout && kicad-python impedance.py && kicad-python logo.py) || fail=1

stage "project and rules files match the generator"
(cd layout && LGW_PCB="$tmp/gen/leaf_gw.kicad_pcb" kicad-python -c '
import os, build, board as B
os.makedirs(os.path.dirname(B.PCB), exist_ok=True)
d = os.path.dirname(B.PCB)
build.write_project(os.path.join(d, "leaf_gw.kicad_pro"))
build.write_rules(os.path.join(d, "leaf_gw.kicad_dru"))') || fail=1
for f in leaf_gw.kicad_pro leaf_gw.kicad_dru; do
  cmp -s "layout/$f" "$tmp/gen/$f" || { echo "layout/$f is stale: ./check_layout.sh --update"; fail=1; }
done

stage "DRC (kicad-cli, JLC rules): errors, warnings and unconnected items"
cp layout/leaf_gw.kicad_pcb layout/leaf_gw.kicad_pro layout/leaf_gw.kicad_dru "$tmp/"
kicad-cli pcb drc --severity-all --format json -o "$tmp/drc.json" "$tmp/leaf_gw.kicad_pcb" >/dev/null || fail=1
python3 - "$tmp/drc.json" <<'EOF' || fail=1
import json, sys
r = json.load(open(sys.argv[1]))
v, u = r.get("violations", []), r.get("unconnected_items", [])
for x in (v + u)[:30]:
    print(f"  {x.get('severity')}: {x.get('type')}: {x.get('description')}", [i.get("description") for i in x.get("items", [])][:2])
print(f"  {len(v)} violations, {len(u)} unconnected")
sys.exit(1 if v or u else 0)
EOF

stage "layout checks: parity, top side, pairs, mismatch, reference plane, 12 V, keepouts, copper safety, silkscreen"
(cd checks && kicad-python layout.py "$here/$pcb") || fail=1

stage "mutation tests (the layout checks bite)"
(cd checks && LGW_TEST_PCB="$here/$pcb" kicad-python test_layout_mutations.py 2>&1 | tail -4; exit "${PIPESTATUS[0]}") || fail=1

stage "fab outputs match the board"
(cd layout && kicad-python fab.py "$tmp/fab" >/dev/null) || fail=1
diff -r out/fab "$tmp/fab" >/dev/null || { diff -rq out/fab "$tmp/fab" | head; echo "out/fab is stale: ./check_layout.sh --update"; fail=1; }

stage "fab BOM = schematic BOM, every line with an LCSC number, CPL = BOM parts"
python3 - out/fab/leaf_gw-bom.csv out/bom_jlcpcb.csv out/fab/leaf_gw-cpl.csv <<'EOF' || fail=1
import csv, sys
fab, sch, cpl = (list(csv.DictReader(open(p))) for p in sys.argv[1:])
def by_ref(rows):
    return {r: (row["LCSC"], row["Footprint"], row["Comment"]) for row in rows for r in row["Designator"].split(",")}
f, s = by_ref(fab), by_ref(sch)
bad = [r for r in sorted(set(f) | set(s)) if f.get(r) != s.get(r)]
for r in bad[:10]:
    print(f"  {r}: fab {f.get(r)} vs schematic {s.get(r)}")
empty = [row["Designator"] for row in fab if not row["LCSC"].startswith("C")]
print(f"  {len(fab)} BOM lines, {len(f)} parts; {len(cpl)} CPL rows")
if empty:
    print("  no LCSC number:", empty)
if {r["Designator"] for r in cpl} != set(f):
    print("  CPL and BOM list different parts")
    bad.append("cpl")
sys.exit(1 if bad or empty else 0)
EOF

stage "CPL in the Gerbers' frame: positions = KiCad's own position export, every part on the board"
kicad-cli pcb export pos --format csv --units mm --side front -o "$tmp/pos.csv" "$pcb" >/dev/null || fail=1
python3 - out/fab/leaf_gw-cpl.csv "$tmp/pos.csv" out/fab/leaf_gw-cpl-corrections.csv <<'EOF' || fail=1
import csv, sys
cpl = {r["Designator"]: (float(r["Mid X"][:-2]), float(r["Mid Y"][:-2])) for r in csv.DictReader(open(sys.argv[1]))}
pos = {r["Ref"]: (float(r["PosX"]), float(r["PosY"])) for r in csv.DictReader(open(sys.argv[2]))}
off = {r["Designator"]: r["Offset (dx dy mm)"] != "0 0" for r in csv.DictReader(open(sys.argv[3]))}
bad = []
for ref, (x, y) in cpl.items():
    px, py = pos[ref]
    d = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
    if d > (3.0 if off[ref] else 0.001):   # a package-origin correction moves a part by that offset only
        bad.append(f"{ref}: CPL ({x}, {y}) vs KiCad ({px}, {py})")
    if not (100.0 <= x <= 175.0 and -150.0 <= y <= -100.0):   # the outline in the Gerbers (board.ORIGIN, W, H)
        bad.append(f"{ref}: ({x}, {y}) is off the board in the Gerbers' frame")
for b in bad[:10]:
    print("  " + b)
print(f"  {len(cpl)} CPL rows checked against KiCad's position export")
sys.exit(1 if bad else 0)
EOF

if [ "${1:-}" = "--rebuild" ]; then
  stage "reproducible: a fresh build passes the same checks"
  re=${LGW_REBUILT:-/tmp/lgw/rebuilt}   # set it to run several rebuilds side by side
  rm -rf "$re" && mkdir -p "$re"
  (cd layout && LGW_PCB="$re/leaf_gw.kicad_pcb" LGW_WORK="$re/work" kicad-python build.py > "$re/build.log" 2>&1) || { tail -5 "$re/build.log"; fail=1; }
  cp layout/leaf_gw.kicad_pro layout/leaf_gw.kicad_dru "$re/"
  kicad-cli pcb drc --severity-all --format json -o "$re/drc.json" "$re/leaf_gw.kicad_pcb" >/dev/null || fail=1
  python3 - "$re/drc.json" <<'EOF2' || fail=1
import json, sys
r = json.load(open(sys.argv[1]))
v, u = r.get("violations", []), r.get("unconnected_items", [])
print(f"  rebuilt board: {len(v)} violations, {len(u)} unconnected")
sys.exit(1 if v or u else 0)
EOF2
  (cd checks && kicad-python layout.py "$re/leaf_gw.kicad_pcb") || fail=1
fi

[ $fail -eq 0 ] && echo "board-layout: all checks passed" || echo "board-layout: FAILED"
exit $fail
