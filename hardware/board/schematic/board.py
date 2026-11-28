"""Build the leaf-gw board from its blocks, run SKiDL ERC, write the outputs.

    python3 board.py OUTDIR

writes OUTDIR/leaf_gw.net (KiCad netlist), bom_jlcpcb.csv, parts.csv and
no_connects.csv. Exits non-zero on any ERC error or warning.
"""

import builtins
import csv
import os
import re
import sys
from collections import defaultdict

from skidl import ERC, KICAD9, generate_netlist, set_default_tool
from skidl.logger import erc_logger

set_default_tool(KICAD9)

import can  # noqa: E402
import connectors  # noqa: E402
import mcu  # noqa: E402
import nets  # noqa: E402
import power  # noqa: E402
import relay  # noqa: E402
import usb  # noqa: E402
from parts import PARTS  # noqa: E402


def build():
    n = nets.make()
    connectors.build(n)
    mcu.build(n)
    can.build(n)
    relay.build(n)
    power.build(n)
    usb.build(n)
    return n


def natural(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def write_bom(out):
    groups = defaultdict(list)
    for p in builtins.default_circuit.parts:
        if "no_bom" not in p.fields:
            groups[(p.fields["MPN"], p.footprint, p.fields["LCSC"])].append(p)
    rows = []
    for (mpn, fp, lcsc), ps in groups.items():
        refs = sorted((p.ref for p in ps), key=natural)
        rows.append((mpn, ",".join(refs), fp.split(":")[-1], lcsc, ps[0], refs))
    rows.sort(key=lambda r: natural(r[5][0]))
    with open(os.path.join(out, "bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for r in rows:
            w.writerow(r[:4])
    with open(os.path.join(out, "parts.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Designator", "Qty", "Value", "Manufacturer", "MPN", "LCSC", "JLC", "Stock 2026-11-27", "Footprint"])
        by_lcsc = {d.lcsc: d for d in PARTS.values()}
        for mpn, refs, fp, lcsc, p, rl in rows:
            d = by_lcsc[lcsc]
            w.writerow([refs, len(rl), d.value, d.mfr, mpn, lcsc, d.jlc, d.stock, p.footprint])


def main(out):
    os.makedirs(out, exist_ok=True)
    build()
    ERC()
    errors, warnings = erc_logger.error.count, erc_logger.warning.count
    for p in builtins.default_circuit.parts:
        p.tag = p.ref  # deterministic timestamps in the netlist
    path = os.path.join(out, "leaf_gw.net")
    generate_netlist(file_=path)
    # drop what changes between runs/machines: date, SKiDL's source-line field
    with open(path) as fh:
        txt = fh.read()
    txt = re.sub(r'\n\s*\(date "[^"]*"\)', "", txt)
    txt = re.sub(r'\(source "[^"]*board\.py"\)', '(source "board.py")', txt)
    txt = re.sub(r'\n\s*\(field\s*\n\s*\(name "SKiDL Line"\) "[^"]*"\)', "", txt)
    with open(path, "w") as fh:
        fh.write(txt)
    write_bom(out)
    with open(os.path.join(out, "no_connects.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Ref", "Pin", "Name", "Reason"])
        for row in sorted(nets.NO_CONNECTS, key=lambda r: (natural(r[0]), len(r[1]), r[1])):
            w.writerow(row)
    if errors or warnings:
        print(f"ERC: {errors} errors, {warnings} warnings", file=sys.stderr)
        return 1
    print("ERC clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out"))
