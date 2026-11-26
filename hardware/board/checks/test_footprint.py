"""The iGrid header footprint holds Molex SD-501645-001's numbers (the drawing
itself is proprietary and not in the repo): 0.80 mm pin holes in 1.5 mm pads at
2.00 mm pitch in both directions, pin 1 at the column end, the 1.4 mm locator
1.2 mm outside the pin 1/2 column and 3.1 mm from the lock-side row, body 20 x 8.2.

    python3 test_footprint.py
"""

import os
import re
import unittest

from netlist import sexpr, kids

FP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "footprints", "leaf_gw.pretty",
                  "Molex_iGrid_501645-1820_2x09_P2.00mm_Vertical.kicad_mod")


def pads():
    with open(FP) as fh:
        root = sexpr(fh.read())
    out = []
    for p in kids(root, "pad"):
        at = kids(p, "at")[0]
        size = kids(p, "size")[0]
        drill = kids(p, "drill")[0]
        out.append({"num": p[1], "kind": p[2], "x": float(at[1]), "y": float(at[2]),
                    "size": (float(size[1]), float(size[2])), "drill": float(drill[1])})
    return out, root


class Header(unittest.TestCase):
    def setUp(self):
        self.pads, self.root = pads()
        self.pins = {p["num"]: p for p in self.pads if p["kind"] == "thru_hole"}
        self.locator = [p for p in self.pads if p["kind"] == "np_thru_hole"]

    def test_pins(self):
        self.assertEqual(sorted(self.pins, key=int), [str(n) for n in range(1, 19)])
        for n, p in self.pins.items():
            n = int(n)
            self.assertAlmostEqual(p["drill"], 0.80, places=3, msg=f"pin {n} hole")
            self.assertEqual(p["size"], (1.5, 1.5), f"pin {n} pad")
            self.assertAlmostEqual(p["x"], -8 + 2 * ((n - 1) // 2), places=3, msg=f"pin {n} x (2.00 pitch)")
            self.assertAlmostEqual(p["y"], -1.0 if n % 2 else 1.0, places=3, msg=f"pin {n} row (2.00 pitch)")

    def test_locator(self):
        self.assertEqual(len(self.locator), 1)
        loc = self.locator[0]
        self.assertAlmostEqual(loc["drill"], 1.4, places=3)          # 1.3 +0.1/-0
        self.assertAlmostEqual(loc["x"], -8 - 1.2, places=3)         # 1.2 outside the pin 1/2 column
        self.assertAlmostEqual(loc["y"], 1.0 + 3.1, places=3)        # 3.1 from the lock-side (even) row

    def test_body(self):
        rects = [r for r in kids(self.root, "fp_rect") if kids(r, "layer")[0][1] == "F.Fab"]
        (_, x0, y0), (_, x1, y1) = kids(rects[0], "start")[0], kids(rects[0], "end")[0]
        self.assertAlmostEqual(float(x1) - float(x0), 20.0, places=3)
        self.assertAlmostEqual(float(y1) - float(y0), 8.2, places=3)

    def test_descr_cites_drawing(self):
        with open(FP) as fh:
            self.assertTrue(re.search(r"SD-501645-001", fh.read()))


if __name__ == "__main__":
    unittest.main(verbosity=1)
