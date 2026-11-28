"""JLCPCB fab outputs from the routed PCB, deterministically.

    kicad-python fab.py [OUT_DIR]       # default ../out/fab

Writes:
  gerbers/   Gerber (Protel extensions, X2 off) for the 4 copper layers, masks,
             paste, silkscreen, outline; Excellon drill (mm, PTH and NPTH apart)
  leaf_gw-gerbers.zip    the gerbers/ directory, ready to upload
  leaf_gw-bom.csv        Comment, Designator, Footprint, LCSC  (JLC BOM)
  leaf_gw-cpl.csv        Designator, Mid X, Mid Y, Layer, Rotation  (JLC CPL)

KiCad stamps a creation date into every Gerber and drill file; those lines are
pinned so the same board gives byte-identical files (and zip).

CPL rotations: JLC places by the EasyEDA footprint of the LCSC part, whose zero
orientation is not always KiCad's. CORRECTIONS below adds, per KiCad footprint,
the turn (and any origin offset) that JLC needs, with where each number comes
from. Parts marked "verify" have no part-specific evidence: check them in JLC's
placement preview before paying (README "Ordering").
"""

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pcbnew as K

import board as B

# footprint name regex -> (degrees CCW added to KiCad's rotation, (dx, dy) mm in
# the footprint frame from KiCad's origin to JLC's package origin, source)
CORRECTIONS = [
    (r"^SOIC-8_", 270, (0, 0),
     "matthewlai/JLCKicadTools cpl_rotations_db.csv '^SOIC-' 270; kicad-jlcpcb-tools jlcfootprint README: "
     "SOIC-8 -BL needs 270 (JLC preview)"),
    (r"^LQFP-", 270, (0, 0), "matthewlai/JLCKicadTools cpl_rotations_db.csv '^LQFP-' 270; "
     "confirmed for U1 (C468260) in JLC's placement preview, 2026-11-27"),
    (r"^SOT-23-6", 180, (0, 0),
     "kicad-jlcpcb-tools jlcfootprint README / truth.csv: SOT-23 family 180 (JLC preview); "
     "confirmed for U7 (C87080) in JLC's placement preview, 2026-11-27; C7519 differs (PART_CORRECTIONS)"),
    (r"^SOT-23-5", 180, (0, 0), "kicad-jlcpcb-tools truth.csv: SOT-23-5 LMV321 at 0 -> 180 (JLC preview)"),
    (r"^SOT-23", 180, (0, 0), "kicad-jlcpcb-tools truth.csv: SOT-23 at 0 -> 180 (JLC preview)"),
    (r"^USB_C_Receptacle_HRO_TYPE-C-31-M-12", 0, (0, -1.571),
     "kicad-jlcpcb-tools truth.csv: C165948 at 0 -> 0, origin dy -1.571 mm (resolver on EasyEDA footprint)"),
    (r"^Relay_DPDT_Omron_G6K-2F-Y", 270, (0, 0), "matthewlai/JLCKicadTools cpl_rotations_db.csv 270; "
     "confirmed for K1 (C2982926) in JLC's placement preview, 2026-11-27"),
    (r"^Molex_iGrid_501645-1820", 0, (0, 0),
     "project footprint drawn from the EasyEDA footprint of C504976 in its own orientation; verify origin"),
    (r".", 0, (0, 0), "two-terminal or symmetric part, no correction; check polarity marks in the preview"),
]
# LCSC part -> the same, for parts whose JLC library footprint doesn't follow
# its package's rule above; checked first.
PART_CORRECTIONS = {
    "C7519": (270, (0, 0), "USBLC6-2SC6: JLC's library footprint is turned 90 degrees from the LMR16006's on the "
              "same SOT-23-6; at 180 JLC's preview showed its leads across our pad columns, pin 1 top-right "
              "(2026-11-27). 270 puts its pin 1 on our pad 1"),
}
SOURCES = {
    "matthewlai/JLCKicadTools": "github.com/matthewlai/JLCKicadTools @ 500a9ff",
    "kicad-jlcpcb-tools": "github.com/Bouni/kicad-jlcpcb-tools @ 6f44644 (flake input jlctools)",
}

LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Mask", "B.Mask", "F.Paste", "B.Paste",
          "F.SilkS", "B.SilkS", "Edge.Cuts"]
DATE_LINES = [
    (re.compile(r"^%TF\.CreationDate,.*\*%$", re.M), "%TF.CreationDate,2026-01-01T00:00:00+00:00*%"),
    (re.compile(r"^G04 Created by KiCad.*date.*$", re.M), "G04 Created by KiCad (leaf-gw fab.py)*"),
    (re.compile(r"^; DRILL file .*$", re.M), "; DRILL file (leaf-gw fab.py)"),
    (re.compile(r"^;\s*#@! TF\.CreationDate,.*$", re.M), ";#@! TF.CreationDate,2026-01-01T00:00:00+00:00"),
    (re.compile(r"^G04 #@! TF\.CreationDate,.*$", re.M), "G04 #@! TF.CreationDate,2026-01-01T00:00:00+00:00*"),
]


def correction(fp_name, lcsc=None):
    if lcsc in PART_CORRECTIONS:
        rot, off, src = PART_CORRECTIONS[lcsc]
        return rot % 360, off, src
    for pat, rot, off, src in CORRECTIONS:
        if re.search(pat, fp_name):
            return rot % 360, off, src
    raise AssertionError(fp_name)


def pin_dates(path):
    with open(path, encoding="latin-1") as fh:
        t = fh.read()
    for rx, rep in DATE_LINES:
        t = rx.sub(rep, t)
    with open(path, "w", encoding="latin-1") as fh:
        fh.write(t)


def gerbers(pcb, outdir):
    g = os.path.join(outdir, "gerbers")
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--no-x2", "--subtract-soldermask",
                    "-l", ",".join(LAYERS), "-o", g + "/", pcb], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
                    "--excellon-zeros-format", "decimal", "--excellon-oval-format", "alternate",
                    "--excellon-separate-th", "--drill-origin", "absolute", "-o", g + "/", pcb],
                   check=True, capture_output=True)
    for f in sorted(os.listdir(g)):
        if f.endswith(".gbrjob"):
            os.remove(os.path.join(g, f))   # job file: JSON with a date and tool version, JLC doesn't use it
            continue
        pin_dates(os.path.join(g, f))
    z = os.path.join(outdir, "leaf_gw-gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            zi = zipfile.ZipInfo(f, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(os.path.join(g, f), "rb") as fh:
                zf.writestr(zi, fh.read())
    return sorted(os.listdir(g))


def assembled(b):
    """Footprints JLC places: those with an LCSC number and not excluded."""
    out = []
    for fp in b.GetFootprints():
        if fp.GetAttributes() & (K.FP_EXCLUDE_FROM_BOM | K.FP_BOARD_ONLY):
            continue
        lcsc = fp.GetFieldText("LCSC") if fp.HasField("LCSC") else ""
        out.append((fp, lcsc))
    return out


def natural(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2)))


def bom_rows(b):
    groups = {}
    for fp, lcsc in assembled(b):
        if not lcsc:
            continue
        key = (fp.GetFieldText("MPN") if fp.HasField("MPN") else fp.GetValue(), str(fp.GetFPID().GetLibItemName()), lcsc)
        groups.setdefault(key, []).append(fp.GetReference())
    rows = [(c, ",".join(sorted(refs, key=natural)), f, l) for (c, f, l), refs in groups.items()]
    return sorted(rows, key=lambda r: natural(r[1].split(",")[0]))


def cpl_rows(b):
    rows = []
    for fp, lcsc in assembled(b):
        if not lcsc:
            continue
        name = str(fp.GetFPID().GetLibItemName())
        rot, (dx, dy), _ = correction(name, lcsc)
        # the Gerbers' frame: KiCad's absolute coordinates, Y up (Gerber), so
        # JLC finds each part on the board without an origin to guess
        x, y = K.ToMM(fp.GetPosition().x), K.ToMM(fp.GetPosition().y)
        a = fp.GetOrientationDegrees()
        import math
        t = math.radians(a)
        # footprint frame (y down, KiCad turns CCW on screen) -> board frame
        ox = dx * math.cos(t) + dy * math.sin(t)
        oy = -dx * math.sin(t) + dy * math.cos(t)
        rows.append((fp.GetReference(), f"{x + ox:.4f}mm", f"{-(y + oy):.4f}mm", "Top",
                     f"{(a + rot) % 360:.1f}"))
    return sorted(rows, key=lambda r: natural(r[0]))


def write_csv(path, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    with open(path, "w") as fh:
        fh.write(buf.getvalue())


def corrections_table(b):
    """(ref, footprint, rotation added, offset, source) for every placed part."""
    out = []
    for fp, lcsc in assembled(b):
        if lcsc:
            name = str(fp.GetFPID().GetLibItemName())
            rot, off, src = correction(name, lcsc)
            out.append((fp.GetReference(), name, rot, off, src))
    return sorted(out, key=lambda r: natural(r[0]))


def run(pcb, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = gerbers(pcb, outdir)
    b = K.LoadBoard(pcb)
    write_csv(os.path.join(outdir, "leaf_gw-bom.csv"), ["Comment", "Designator", "Footprint", "LCSC"], bom_rows(b))
    write_csv(os.path.join(outdir, "leaf_gw-cpl.csv"), ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"],
              cpl_rows(b))
    write_csv(os.path.join(outdir, "leaf_gw-cpl-corrections.csv"),
              ["Designator", "Footprint", "Rotation added", "Offset (dx dy mm)", "Source"],
              [(r, f, rot, f"{o[0]} {o[1]}", s) for r, f, rot, o, s in corrections_table(b)])
    return files


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B.OUT, "fab")
    print("\n".join(run(B.PCB, out)))
