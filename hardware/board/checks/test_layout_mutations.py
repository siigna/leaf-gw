"""Prove the PCB checks bite: each mutation of the real board (in memory, or a
temporary copy for the DRC) must make its check fail for the intended reason,
and the unmutated board must pass everything.

    kicad-python test_layout_mutations.py [board.kicad_pcb]
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import pcbnew as K

import layout as L

PCB = os.environ.get("LGW_TEST_PCB") or L.B.PCB


def mm(v):
    return K.FromMM(v)


def pt(x, y):
    return K.VECTOR2I(mm(L.B.ORIGIN[0] + x), mm(L.B.ORIGIN[1] + y))


def longest(bd, net):
    return max(bd.tracks(net), key=lambda t: t.GetLength())


KEEP = []   # SWIG would free items (and boards) still owned by Python once they drop out of scope


def add_track(bd, net, a, c, w=0.2, layer=K.F_Cu):
    t = K.PCB_TRACK(bd.pcb)
    KEEP.append(t)
    t.thisown = False
    t.SetStart(a)
    t.SetEnd(c)
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(bd.pcb.FindNet(net))
    bd.pcb.Add(t)
    return t


class Mutations(unittest.TestCase):
    nl = None

    def board(self):
        bd = L.Board(K.LoadBoard(PCB), self.nl or L.Netlist.load(L.B.NETLIST))
        KEEP.append(bd)
        Mutations.nl = bd.nl
        return bd

    def bites(self, check, mutate, expect):
        bd = self.board()
        mutate(bd)
        fails = check(bd)
        self.assertTrue(fails, f"{check.__name__} passed a board with: {self._testMethodName}")
        self.assertTrue(any(expect in x for x in fails), f"{check.__name__} failed for another reason: {fails[:3]}")

    def test_baseline_passes(self):
        bd = self.board()
        for name, fails in L.run(bd).items():
            self.assertEqual(fails, [], name)

    # parity
    def test_pad_net_swapped(self):
        def m(bd):
            a, b = bd.pad("U2", "1"), bd.pad("U2", "4")
            na, nb = a.GetNet(), b.GetNet()
            a.SetNet(nb)
            b.SetNet(na)
        self.bites(L.check_parity, m, "netlist")

    def test_footprint_missing(self):
        # (items are moved or emptied rather than removed: pcbnew's SWIG layer
        # corrupts later LoadBoard calls after BOARD.Remove from Python)
        def m(bd):
            bd.fps["R12"].SetReference("R12X")
            bd.fps["R12X"] = bd.fps.pop("R12")
        self.bites(L.check_parity, m, "R12: in the netlist, not on the board")

    def test_extra_footprint(self):
        def m(bd):
            fp = K.FOOTPRINT(bd.pcb)
            KEEP.append(fp)
            fp.thisown = False
            fp.SetReference("R99")
            bd.pcb.Add(fp)
            bd.fps["R99"] = fp
        self.bites(L.check_parity, m, "not in the netlist")

    # top side
    def test_part_on_bottom(self):
        def m(bd):
            fp = bd.fps["C22"]
            fp.Flip(fp.GetPosition(), K.FLIP_DIRECTION_TOP_BOTTOM)
        self.bites(L.check_top_side, m, "C22 is on the bottom")

    # pairs
    def test_pair_coupling_broken(self):
        def m(bd):
            t = longest(bd, "CAN0_L")
            t.Move(K.VECTOR2I(0, mm(-0.3)))
        self.bites(L.check_pairs, m, "uncoupled")

    def test_via_in_pair(self):
        def m(bd):
            t = longest(bd, "CAN0_H")
            v = K.PCB_VIA(bd.pcb)
            KEEP.append(v)
            v.thisown = False
            v.SetPosition(t.GetCenter())
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(t.GetNet())
            bd.pcb.Add(v)
        self.bites(L.check_pairs, m, "via on CAN0_H")

    def test_pair_on_bottom_layer(self):
        self.bites(L.check_pairs, lambda bd: longest(bd, "CAN2_L").SetLayer(K.B_Cu), "track on B.Cu")

    def test_pair_wrong_width(self):
        self.bites(L.check_pairs, lambda bd: longest(bd, "USB_DP").SetWidth(mm(0.2)), "wide (pair width")

    def test_pair_length_mismatch(self):
        def m(bd):
            # a 1.2 mm detour bump in the middle of CAN0_H's long run
            t = longest(bd, "CAN0_H")
            c = K.VECTOR2I(t.GetEnd().x, t.GetEnd().y)   # a copy: GetEnd() aliases the track's own end
            mid = K.VECTOR2I(t.GetCenter().x, t.GetCenter().y)
            p1 = K.VECTOR2I(mid.x - mm(0.3), mid.y)
            p2 = K.VECTOR2I(mid.x + mm(0.3), mid.y)
            up1 = K.VECTOR2I(p1.x, p1.y + mm(0.6))
            up2 = K.VECTOR2I(p2.x, p2.y + mm(0.6))
            t.SetEnd(p1)
            for s, e in ((p1, up1), (up1, up2), (up2, p2), (p2, c)):
                add_track(bd, "CAN0_H", s, e, 0.19)
        self.bites(L.check_mismatch, m, "CAN0: to J2.4/J2.6")

    def test_plane_split_under_pair(self):
        def m(bd):
            # cut a 1 mm slot across the In1 GND fill under the CAN0 run
            z = next(z for z in bd.pcb.Zones() if z.GetNetname() == "GND" and z.IsOnLayer(K.In1_Cu))
            fill = z.GetFilledPolysList(K.In1_Cu)
            cut = K.SHAPE_POLY_SET()
            cut.NewOutline()
            c = longest(bd, "CAN0_H").GetCenter()   # the middle of the CAN0 run, both lines within 1 mm
            x, y0, y1 = c.x, c.y - mm(1), c.y + mm(1)
            for px, py in ((x, y0), (x + mm(1), y0), (x + mm(1), y1), (x, y1)):
                cut.Append(px, py)
            fill.BooleanSubtract(cut)
            z.SetFilledPolysList(K.In1_Cu, fill)
        self.bites(L.check_reference_plane, m, "CAN0")

    def test_plane_zone_deleted(self):
        def m(bd):
            z = next(z for z in bd.pcb.Zones() if z.GetNetname() == "GND" and z.IsOnLayer(K.In1_Cu))
            z.SetFilledPolysList(K.In1_Cu, K.SHAPE_POLY_SET())
        self.bites(L.check_reference_plane, m, "leaves the In1 GND plane")

    # In2 (+3V3 plane)
    def _in2_cut(self, bd, bridge):
        """Slot the In2 +3V3 fill across the whole board at x = 37.5, leaving a
        bridge of this width (mm) at mid-height (0: a clean split)."""
        z = next(z for z in bd.pcb.Zones() if z.GetNetname() == "+3V3" and z.IsOnLayer(K.In2_Cu))
        fill = z.GetFilledPolysList(K.In2_Cu)
        x0, x1, h = 37.25, 37.75, L.B.H
        for y0, y1 in ((-1, h / 2 - bridge / 2), (h / 2 + bridge / 2, h + 1)):
            cut = K.SHAPE_POLY_SET()
            cut.NewOutline()
            for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                cut.Append(pt(px, py).x, pt(px, py).y)
            fill.BooleanSubtract(cut)
        z.SetFilledPolysList(K.In2_Cu, fill)

    def test_in2_split(self):
        self.bites(L.check_in2, lambda bd: self._in2_cut(bd, 0), "+3V3 plane on In2")

    def test_in2_neck(self):
        self.bites(L.check_in2, lambda bd: self._in2_cut(bd, 0.6), "neck under 1.0 mm")

    def test_in2_long_track(self):
        self.bites(L.check_in2, lambda bd: add_track(bd, "SWDIO", pt(30, 40), pt(40, 40), 0.2, K.In2_Cu),
                   "SWDIO runs 10.0 mm on In2")

    # 12 V
    def test_12v_track_narrow(self):
        self.bites(L.check_12v_width, lambda bd: longest(bd, "IGN").SetWidth(mm(0.3)), "IGN: 0.300")

    # keepouts
    def test_part_on_header_face(self):
        def m(bd):
            x, y = L.xy(bd.fps["J1"].GetPosition())
            bd.fps["R12"].SetPosition(pt(x + 3.0, y))
        self.bites(L.check_keepouts, m, "R12 intrudes on J1")

    def test_usb_off_edge(self):
        self.bites(L.check_keepouts, lambda bd: bd.fps["J3"].Move(K.VECTOR2I(0, mm(-2))), "J3 front")

    def test_part_in_usb_plug_zone(self):
        def m(bd):
            x, _ = L.xy(bd.fps["J3"].GetPosition())
            bd.fps["R19"].SetPosition(pt(x - 5.5, L.B.H - 0.8))
        self.bites(L.check_keepouts, m, "R19 is in the USB plug zone")

    # safety net on copper
    def test_short_across_relay(self):
        def m(bd):
            add_track(bd, "CAN1_ADAS_H", bd.pad("K1", "11").GetPosition(), bd.pad("K1", "12").GetPosition())
        self.bites(L.check_copper_safety, m, "copper short")

    def test_relay_com_cut(self):
        def m(bd):
            for t in bd.tracks("CAN1_ADAS_L"):
                if t.HitTest(bd.pad("K1", "21").GetPosition()):
                    t.Move(K.VECTOR2I(mm(200), 0))   # off the board: cut
        self.bites(L.check_copper_safety, m, "CAN1_ADAS_L is not connected")

    def test_box_pin_9_copper(self):
        def m(bd):
            p = bd.pad("J2", "9").GetPosition()
            add_track(bd, "", p, K.VECTOR2I(p.x - mm(1.2), p.y), 0.2, K.B_Cu)
        self.bites(L.check_copper_safety, m, "J2.9 touched")

    def test_box_pin_9_barrel_on_in2(self):
        # J2's pads have no In2 ring: a track reaching the plated barrel there still connects
        def m(bd):
            p = bd.pad("J2", "9").GetPosition()
            add_track(bd, "", p, K.VECTOR2I(p.x - mm(1.2), p.y), 0.2, K.In2_Cu)
        self.bites(L.check_copper_safety, m, "J2.9 touched")

    def test_pass_through_cut(self):
        def m(bd):
            for t in bd.tracks("BUS0_LOOP_3"):
                t.Move(K.VECTOR2I(mm(200), 0))
        self.bites(L.check_copper_safety, m, "BUS0_LOOP_3 is not connected")

    # silkscreen
    def test_silk_on_pad(self):
        def m(bd):
            t = next(d for d in bd.pcb.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() == K.F_SilkS)
            t.SetPosition(bd.pad("U1", "1").GetPosition())
        self.bites(L.check_silk, m, "solder-mask opening")

    def _logo_pad(self, bd):
        return next(iter(bd.fps["LOGO"].Pads()))

    def test_logo_thin_line(self):
        def m(bd):
            pad = self._logo_pad(bd)
            ps = K.SHAPE_POLY_SET()   # a 0.1 mm sliver of copper off the leaf, in pad coordinates
            ps.NewOutline()
            for px, py in ((-6, 6), (-2, 6), (-2, 6.1), (-6, 6.1)):
                ps.Append(mm(px), mm(py))
            pad.AddPrimitivePoly(K.F_Cu, ps, 0, True)
        self.bites(L.check_silk, m, "lines under 0.15")

    def test_logo_on_a_net(self):
        self.bites(L.check_silk, lambda bd: self._logo_pad(bd).SetNet(bd.pcb.FindNet("GND")), "logo copper is on net GND")

    def test_pin_label_off_row(self):
        def m(bd):
            for _, it in L.silk_items(bd, K.B_SilkS):
                if it.GetClass() == "PCB_TEXT" and it.GetText().startswith("5 bus0 loop / 6 CAN0 L "):
                    it.Move(K.VECTOR2I(0, mm(1.0)))   # a pin pitch down: beside the wrong row
        self.bites(L.check_pin_labels, m, "J2 label '5 bus0 loop / 6 CAN0 L'")

    # the DRC itself
    def test_drc_catches_clearance(self):
        bd = self.board()
        a, c = longest(bd, "CAN0_H"), longest(bd, "CAN0_L")
        add_track(bd, "CAN0_H", a.GetCenter(), K.VECTOR2I(a.GetCenter().x, c.GetCenter().y + mm(0.1)), 0.19)
        d = tempfile.mkdtemp()
        try:
            for ext in ("kicad_pro", "kicad_dru"):
                shutil.copy(os.path.splitext(PCB)[0] + "." + ext, os.path.join(d, "leaf_gw." + ext))
            path = os.path.join(d, "leaf_gw.kicad_pcb")
            K.SaveBoard(path, bd.pcb)
            n = drc_violations(path)
            self.assertGreater(n, 0, "DRC passed a short between CAN0_H and CAN0_L")
        finally:
            shutil.rmtree(d)


def drc_violations(path):
    """Errors + warnings + unconnected items from kicad-cli pcb drc."""
    import json
    out = path + ".drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json", "-o", out, path],
                   check=True, capture_output=True)
    with open(out) as fh:
        r = json.load(fh)
    return len(r.get("violations", [])) + len(r.get("unconnected_items", [])) + len(r.get("schematic_parity", []))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        PCB = sys.argv.pop(1)
    unittest.main(verbosity=1)
