"""BOM and footprint checks.

    python3 bom.py leaf_gw.net bom_jlcpcb.csv

BOM: every assembled part has an LCSC number, designators are unique, and the
JLCPCB CSV lists exactly the netlist's assembled parts. Parts left off the BOM
must be bare copper (test pads, solder jumpers) and say why.
Footprints: every footprint exists (KiCad library or ../footprints) and has a
pad for every pin the netlist connects.
"""

import csv
import os
import re
import sys
from collections import Counter

from netlist import Netlist

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_LIBS = {"leaf_gw": os.path.join(HERE, "..", "footprints", "leaf_gw.pretty")}
BARE_COPPER = ("TestPoint:", "Jumper:")


def read_bom(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def check_bom(nl, rows):
    f = []
    dup = [r for r, n in Counter(nl.refs).items() if n > 1]
    if dup:
        f.append(f"duplicated designators in netlist: {dup}")
    for ref, c in nl.comps.items():
        fields = c["fields"]
        if "no_bom" in fields:
            if not fields["no_bom"] or not c["footprint"].startswith(BARE_COPPER):
                f.append(f"{ref}: off the BOM but not a bare-copper footprint with a reason")
        elif not re.fullmatch(r"C\d+", fields.get("LCSC", "")):
            f.append(f"{ref}: no LCSC part number")
        elif fields.get("JLC") not in ("basic", "preferred", "extended"):
            f.append(f"{ref}: JLC library type missing")
    if not rows or rows[0] != ["Comment", "Designator", "Footprint", "LCSC"]:
        f.append("BOM header is not Comment,Designator,Footprint,LCSC")
        return f
    listed = []
    for row in rows[1:]:
        comment, refs, fp, lcsc = row
        if not re.fullmatch(r"C\d+", lcsc) or not comment or not fp:
            f.append(f"BOM line {row}: missing comment/footprint/LCSC")
        for ref in refs.split(","):
            listed.append(ref)
            c = nl.comps.get(ref)
            if c and c["fields"].get("LCSC") != lcsc:
                f.append(f"BOM {ref}: LCSC {lcsc} differs from netlist {c['fields'].get('LCSC')}")
    dup = [r for r, n in Counter(listed).items() if n > 1]
    if dup:
        f.append(f"duplicated designators in BOM: {dup}")
    want = {r for r, c in nl.comps.items() if "no_bom" not in c["fields"]}
    if set(listed) != want:
        f.append(f"BOM vs netlist: missing {sorted(want - set(listed))}, extra {sorted(set(listed) - want)}")
    return f


def footprint_file(fp):
    lib, name = fp.split(":", 1)
    base = PROJECT_LIBS.get(lib) or os.path.join(os.environ.get("KICAD9_FOOTPRINT_DIR", ""), lib + ".pretty")
    return os.path.join(base, name + ".kicad_mod")


def check_footprints(nl):
    f = []
    for ref, c in sorted(nl.comps.items()):
        path = footprint_file(c["footprint"])
        if not os.path.exists(path):
            f.append(f"{ref}: footprint {c['footprint']} not found")
            continue
        with open(path) as fh:
            pads = set(re.findall(r'\(pad\s+"([^"]*)"', fh.read()))
        missing = set(nl.pins_of(ref)) - pads
        if missing:
            f.append(f"{ref}: pins {sorted(missing)} have no pad in {c['footprint']}")
    return f


def main(net, bom):
    nl = Netlist.load(net)
    bad = 0
    for name, fails in (("check_bom", check_bom(nl, read_bom(bom))), ("check_footprints", check_footprints(nl))):
        print(("FAIL " if fails else "ok   ") + name)
        for msg in fails:
            print("     " + msg)
        bad += bool(fails)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
