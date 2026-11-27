"""Each check in checks.py must fail on a case broken on purpose.

    kicad-python test_mutations.py

A mutation either changes a case.py parameter (the one build() reads; the
derived Z levels are set directly) or edits the built solids, rebuilds, and
runs one check, which must report a finding containing the expected text.
The unmutated case must pass every check.
"""

import sys

import case as C
import checks as K

T = C.T
PLUG = None


def tilted(name, m, _orig=C.printed):
    return _orig(name, m.rotate([8, 0, 0]) if name == "tray" else m)


def unflipped(name, m, _orig=C.printed):
    return _orig("tray", m)   # "tray" = no flip


def no_standoff(p):
    x, y, _ = C.B3.hole("H2")
    p["tray"] -= C.cyl(x, y, 6, -0.6, 0.01)
    return p


def short_boss(p):
    x, y, _ = C.B3.hole("H1")
    p["lid"] -= C.cyl(x, y, 6, T - 0.01, T + 0.5)
    return p


def usb_moved(_orig=C.usb):
    x, z, front = _orig()
    return x + 1.5, z, front


MUTATIONS = [
    # (description, case attributes, function: built parts -> parts, check, expected text)
    ("floor 1 mm under the board", {"Z_FLOOR": -(1.0 + C.FLOOR)}, None, K.clearance, "hits J1 tails"),
    ("lid top below the screw heads (empty lid)", {"Z_TOP": C.Z_TOP - 6.5}, None, K.valid, "lid"),
    ("roof dropped onto the relay", {"Z_TOP": C.Z_TOP - 4.5}, None, K.clearance, "hits K1"),
    ("board edge 0.1 mm from the wall", {"CLEAR_EDGE": 0.1}, None, K.clearance, "board edge"),
    ("header window 0.1 mm clear", {"WINDOW_CLEAR": 0.1}, None, K.clearance, "from J1"),
    ("header window 2 mm clear", {"WINDOW_CLEAR": 2.0}, None, K.openings, "snug"),
    ("H2 standoff cut down", {}, no_standoff, K.seated, "H2 standoff under the board"),
    ("H1 lid boss short", {}, short_boss, K.seated, "H1 lid boss on the board"),
    ("pilot hole 1.2 mm", {"PILOT_D": 1.2}, None, K.seated, "screw path in the tray"),
    ("pilot hole 2.3 mm", {"PILOT_D": 2.3}, None, K.seated, "thread in the tray"),
    ("screw head 7 mm up (short thread)", {"HEAD_SEAT": 7.0}, None, K.seated, "mm of thread"),
    ("wall 1.4 mm (0.55 mm lip)", {"WALL": 1.4}, None, K.walls, "mm thick"),
    ("USB-C slot 1.5 mm off the receptacle", {"usb": usb_moved}, None, K.openings, "USB-C overmold"),
    ("USB-C slot 0.05 mm clear", {"USB_CLEAR": 0.05}, None, K.openings, "USB-C overmold"),
    ("LED hole 1 mm", {"LED_D": 1.0}, None, K.openings, "D11 light path"),
    ("DFU pinhole 0.6 mm", {"PIN_D": 0.6}, None, K.openings, "DFU paperclip path"),
    ("lid 1 mm above the headers", {"Z_TOP": C.HEADER_TOP + 1.0}, None, K.openings, "above the header tops"),
    ("lid printed roof up", {"printed": unflipped}, None, K.printed, "flat overhang"),
    ("tray tilted 8 deg on the bed", {"printed": tilted}, None, K.printed, "on the bed"),
    ("zip-tie ears 60 mm long", {"EAR_L": 60.0}, None, K.printed, "does not fit"),
    ("6 mm counterbore (boss floats in it)", {"CBORE_D": 6.0, "BOSS_TOP_D": 8.4}, None, K.printed, "floats over air"),
    ("5.5 mm counterbore over a 6 mm boss (wide bridge)", {"CBORE_D": 5.5, "BOSS_D": 6.0, "BOSS_TOP_D": 8.4}, None, K.printed, "flat overhang 5.5 mm"),
    ("lid 1 mm above the headers (plugs)", {"Z_TOP": C.HEADER_TOP + 1.0}, None, "plugs", "finger and wire room"),
    ("lid 0.2 mm above the headers, window 0.1 mm (plugs)", {"Z_TOP": C.HEADER_TOP + 0.2, "WINDOW_CLEAR": 0.1}, None, "plugs", "J1 plug"),
]


def run(attrs, edit, check):
    old = {k: getattr(C, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(C, k, v)
        parts = C.build()
        if edit:
            parts = edit(parts)
        if "usb" in attrs:   # the slot moved, not the receptacle: check against the real one
            C.usb = old["usb"]
        if check == "plugs":
            return K.plugs(parts, PLUG)
        return check(parts)
    finally:
        for k, v in old.items():
            setattr(C, k, v)


def main():
    global PLUG
    import os
    PLUG = K.plug_mesh() if os.path.exists(K.PLUG_STEP) and K.shutil.which("gmsh") else None
    fails = 0
    base = C.build()
    for title, fn in K.CHECKS:
        r = K.plugs(base, PLUG) if fn is K.plugs and PLUG is not None else (None if fn is K.plugs else fn(base))
        if r:
            print(f"FAIL unmutated case fails {title}: {r[:3]}")
            fails += 1
    for title, attrs, edit, check, want in MUTATIONS:
        if check == "plugs" and PLUG is None:
            print(f"skip {title}: no plug STEP or no gmsh")
            continue
        r = run(attrs, edit, check)
        hit = [f for f in r if want in f]
        print(f"{'ok  ' if hit else 'FAIL'} {title}: {hit[0] if hit else r[:3] or 'no finding'}")
        fails += not hit
    print(f"{len(MUTATIONS)} mutations, {fails} failed")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
