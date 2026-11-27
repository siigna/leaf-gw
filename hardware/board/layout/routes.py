"""Critical routes, drawn by script: the four CAN pairs and the USB pair.

freerouting has no differential-pair support, so these are laid down here and
handed to it as fixed wiring. All of them are on F.Cu over the solid GND plane
on In1.Cu, with no vias (the two USB plug-flip links at the receptacle are the
only exception, see usb()).

Topology (placement.py has the parts):
  - each pair leaves its header pins (odd-row pins squeeze between the even-row
    pads), runs coupled at the impedance.py geometry, and splits around its
    tap cluster: the L line over the top, the H line underneath. Short spurs
    drop from each line to the ESD array and the transceiver pins, which face
    each other across the spur channel.
  - CAN1: the relay sits on all four CAN1 lines. ADAS L lands on COM_B from the
    left, ADAS H passes between COM_B and NC_B to COM_A from inside; car L
    lands on NC_B and crosses inside to leave between COM_A and NC_A; car H
    passes under NC_B to NC_A from inside. No crossings, so no vias.

Every line is a list of points (board mm); a point may be a pad, given as
(ref, pad). Pair offsets come from board.CAN_W/CAN_GAP and USB_W/USB_GAP.
"""

from shapely.geometry import LineString

import board as B
import placement

D_CAN = (B.CAN_W + B.CAN_GAP) / 2   # centreline to line centre, coupled
D_USB = (B.USB_W + B.USB_GAP) / 2


def offset_pair(centre, d):
    """(upper, lower) lines at +-d from a centreline, mitred, as point lists.
    'upper' is the one with the smaller y at the start."""
    cl = LineString(centre)
    a = list(cl.offset_curve(d, join_style="mitre").coords)
    b = list(cl.offset_curve(-d, join_style="mitre").coords)
    a, b = [tuple(round(v, 4) for v in p) for p in a], [tuple(round(v, 4) for v in p) for p in b]
    return (a, b) if a[0][1] < b[0][1] else (b, a)


# Extra length per line, as (bump count, bump height): rectangular bumps on one
# straight run, set from checks/layout.py's mismatch report.
TUNE = {
    "CAN2_L_in": (1, 0.8),      # J1 -> transceiver 3
    "CAN2_L_out": (1, 0.55),    # transceiver 3 -> J2
    "ADAS_H_in": (1, 1.43),     # J1 -> transceiver 1
    "ADAS_L_out": (2, 0.44),    # transceiver 1 -> relay COM
    "CAR_H_in": (1, 2.0),       # relay -> transceiver 2
    "CAR_H_out": (1, 1.84),     # transceiver 2 -> J2
    "USB_DM": (1, 0.55),        # protector -> MCU
}


def bumps(a, c, tune, side):
    """Points of a horizontal run a->c with n rectangular bumps of height h
    toward +y (side > 0) or -y, each adding 2h of length."""
    n, h = tune
    if n == 0:
        return []
    (x0, y), (x1, _) = a, c
    pitch = (x1 - x0) / (2 * n + 1)     # negative when the run goes right to left
    pts = []
    for i in range(n):
        xa = round(x0 + pitch * (2 * i + 1), 4)
        xb = round(xa + pitch, 4)
        yy = round(y + (h if side > 0 else -h), 4)
        pts += [(xa, y), (xa, yy), (xb, yy), (xb, y)]
    return pts


def lines(pad):
    return _spread(_lines, pad)


def _spread(f, pad):
    """Run a route function on the compact drawing (board.spread) and map its points to the board."""
    old = lambda *p: B.unspread(*pad(*p))   # noqa: E731
    out = f(old)
    for net, w, pts in out:
        for a, c in zip(pts, pts[1:]):
            (dxa, dya), (dxc, dyc) = B.shift(*a), B.shift(*c)
            cross = (c[0] - a[0]) * (dyc - dya) - (c[1] - a[1]) * (dxc - dxa)
            assert abs(cross) < 1e-6, f"{net}: segment {a}-{c} crosses a spread() cut at an angle"
    return [(net, w, [B.spread(*q) for q in pts]) for net, w, pts in out]


def _lines(pad):
    """All critical copper as (net, width, [points]); pad(ref, num) -> (x, y)."""
    out = []

    def L(net, w, *pts):
        out.append((net, w, [pad(*p) if isinstance(p[0], str) else p for p in pts]))

    def spur(net, x, y_from, y_to, *pads):
        """Vertical spur at x from the bus line down/up to the farthest pad, with a
        horizontal stub to each pad at its own height."""
        L(net, B.CAN_W, (x, y_from), (x, y_to))
        for p in pads:
            px, py = pad(*p)
            L(net, B.CAN_W, (x, py), (px, py))

    def channel_x(esd, u):
        """x midway between the ESD array's right pad edge and the transceiver's left pad edge."""
        e_right = pad(esd, "1")[0] + 1.475 / 2
        u_left = pad(u, "6")[0] - 1.95 / 2
        return (e_right + u_left) / 2

    w = B.CAN_W
    c = D_CAN

    # --- CAN2 (V-CAN, J1/J2 pins 16 H, 18 L): over the top-left cluster, then across.
    # The pair climbs coupled to the cluster's centre line and splits evenly
    # around it; on the way out the H line doubles back up to the centre line
    # so both lines come down to the cross-board run together.
    ym = pad("U4", "6")[1] / 2 + pad("U4", "7")[1] / 2     # cluster centre line
    yt = 0.9                                                # clear of the edge by the plane margin
    yb = ym + (ym - yt)                                     # L over, H under, symmetric
    y2 = 9.1                                                # cross-board run
    xs = channel_x("D23", "U4")
    xsplit, xjoin = 8.6, 27.2
    L("CAN2_L", w, ("J1", "18"), (5.9, 10.5), (5.9, ym - c), (xsplit, ym - c), (xsplit, yt + 0.8),
      (xsplit + 0.8, yt), *bumps((9.5, yt), (11.6, yt), TUNE["CAN2_L_in"], +1),
      *bumps((16.0, yt), (19.2, yt), TUNE["CAN2_L_out"], +1), (xjoin + 0.2, yt), (28.0 + c, yt + 0.8 - 0.2), (28.0 + c, y2 - c),
      (49.6, y2 - c), (49.6 + (9.5 - (y2 - c)), 9.5), (53.4, 9.5), ("J2", "18"))
    spur("CAN2_L", xs, yt, pad("U4", "6")[1], ("D23", "2"), ("U4", "6"))
    L("CAN2_H", w, ("J1", "16"), (5.9 + 2 * c, 12.5), (5.9 + 2 * c, ym + c), (xsplit, ym + c), (xsplit, yb - 0.8),
      (xsplit + 0.8, yb), (xjoin, yb), (xjoin, ym + c), (28.0 - c, ym + c),
      (28.0 - c, y2 + c), (49.0, y2 + c), (49.0 + (11.5 - (y2 + c)), 11.5), (53.4, 11.5), ("J2", "16"))
    spur("CAN2_H", xs, yb, pad("U4", "7")[1], ("D23", "1"), ("U4", "7"))

    # --- CAN1 ADAS side (J1 pins 9 H, 11 L; both odd row): to transceiver 1 and relay COM
    yt, yb = 10.45, 16.75
    xs = channel_x("D21", "U2")
    xd = 23.4                  # where the L line drops to COM_B
    k_com_b, k_com_a = pad("K1", "21"), pad("K1", "11")
    k_nc_b, k_nc_a = pad("K1", "22"), pad("K1", "12")
    xl_in, xl_out = k_nc_b[0] + 0.9, k_nc_a[0] - 0.9      # relay channel walls (pad inner edges)
    xr_out = k_nc_a[0] + 0.9 + 0.4
    y_gap_b = (k_com_b[1] + k_nc_b[1]) / 2               # between COM_B and NC_B
    y_gap_a = (k_com_a[1] + k_nc_a[1]) / 2               # between COM_A and NC_A
    L("CAN1_ADAS_L", w, ("J1", "11"), (3.6, 15.5), (5.6, 15.5), (7.9, 13.2), (7.9, yt + 0.9), (8.8, yt),
      *bumps((16.1, yt), (18.9, yt), TUNE["ADAS_L_out"], +1), (xd, yt), (xd, k_com_b[1]), ("K1", "21"))
    spur("CAN1_ADAS_L", xs, yt, pad("U2", "6")[1], ("D21", "2"), ("U2", "6"))
    L("CAN1_ADAS_H", w, ("J1", "9"), (3.6, 17.5), (5.6, 17.5), (6.35, yb),
      *bumps((6.6, yb), (9.4, yb), TUNE["ADAS_H_in"], +1), (xd - 0.2, yb),
      (xd + 0.05, y_gap_b), (xl_in, y_gap_b), (xl_out, k_com_a[1]), ("K1", "11"))
    spur("CAN1_ADAS_H", xs, yb, pad("U2", "7")[1], ("D21", "1"), ("U2", "7"))

    # --- CAN1 car side (J1/J2 pins 8 H even, 7 L odd): through the relay, around cluster 2
    yc = 19.7                  # coupled centreline from J1 to the relay
    yt, yb = 13.85, 20.15      # over / under transceiver 2
    xs = channel_x("D22", "U3")
    xv = 33.4                  # where the lines turn up / down after the relay
    y_ab = (pad("K1", "22")[1] + pad("K1", "A2")[1]) / 2    # between NC_B and A2
    L("CAN1_CAR_L", w, ("J1", "7"), (3.6 - (yc - c - 19.5), yc - c), (22.2, yc - c), (22.2 + (yc - c - k_nc_b[1]), k_nc_b[1]),
      ("K1", "22"), (xl_in, k_nc_b[1]), (xl_out, y_gap_a), (xv, y_gap_a), (xv, yt), (48.3, yt), (48.3, 20.5), ("J2", "7"))
    spur("CAN1_CAR_L", xs, yt, pad("U3", "6")[1], ("D22", "2"), ("U3", "6"))
    L("CAN1_CAR_H", w, ("J1", "8"), (4.6 + (20.5 - yc - c), yc + c), (xl_in - 1.8, yc + c), (xl_in, y_ab),
      (xl_out, k_nc_a[1]), ("K1", "12"), (xv - 0.5, k_nc_a[1]), (xv, k_nc_a[1] + 0.5), (xv, yb),
      *bumps((xv, yb), (34.5, yb), TUNE["CAR_H_in"], +1), *bumps((43.3, yb), (46.9, yb), TUNE["CAR_H_out"], +1),
      (47.0, yb),
      (47.0 + (21.5 - yb), 21.5), (53.4, 21.5), ("J2", "8"))
    spur("CAN1_CAR_H", xs, yb, pad("U3", "7")[1], ("D22", "1"), ("U3", "7"))

    # --- CAN0 (J1/J2 pins 4 H, 6 L; pass-through only)
    y0 = 23.8
    L("CAN0_L", w, ("J1", "6"), (4.6 + (y0 - c - 22.5), y0 - c), (49.9, y0 - c), (50.0, 23.5), (53.4, 23.5), ("J2", "6"))
    L("CAN0_H", w, ("J1", "4"), (4.6 + (24.5 - y0 - c), y0 + c), (49.0, y0 + c), (49.0 + (25.5 - y0 - c), 25.5),
      (53.4, 25.5), ("J2", "4"))

    usb(L, pad)
    # CC1 sits between the receptacle's VBUS pad and the D- line: straight to its pull-down
    a5 = pad("J3", "A5")
    L("USB_CC1", 0.2, ("J3", "A5"), (a5[0], a5[1] - 1.45 / 2 - 0.3), ("R19", "1"))

    for pin, pts in sorted(MCU_ESCAPES.items()):
        px, py = pad("U1", pin)
        tip = py + 1.55 / 2 + 0.35
        L(NET_OF_MCU[pin], 0.2, ("U1", pin), (px, tip), *pts)
    # crystal: PH0/PH1 straight out to the HSE crystal beside the MCU, HSE_IN
    # over the top, HSE_OUT underneath (the load caps are freerouted)
    m5, m6 = pad("U1", "5"), pad("U1", "6")
    y1, y2 = pad("Y1", "1"), pad("Y1", "2")
    tip = m5[0] - 1.55 / 2
    yi, yo = 28.5, 29.05      # between C2 above and C12 below
    L("HSE_IN", 0.17, ("U1", "5"), (15.25, m5[1]), (15.25, yi), (13.4, yi), (13.4, y1[1] + 0.6), (y1[0] + 0.8, y1[1]), ("Y1", "1"))
    L("HSE_OUT", 0.17, ("U1", "6"), (14.9, m6[1]), (14.9, yo), (13.0, yo), (y2[0] + 0.8, y2[1] - 0.3), ("Y1", "2"))
    m46 = pad("U1", "46")
    L("SWDIO", 0.17, ("U1", "46"), (SWDIO_VIA[0] - 0.03, m46[1]), (SWDIO_VIA[0] - 0.03, SWDIO_VIA[1] + 0.3), SWDIO_VIA)

    # MCU supply pins boxed in by their neighbours: straight to the decoupling
    # cap set right under / beside them (whose via reaches the +3V3 plane)
    for pin, cap in (("19", "C4"), ("32", "C5"), ("13", "C3")):
        L("+3V3", 0.3, ("U1", pin), (cap, "1"))
    return out


def usb(L, pad):
    """USB D+/D-: receptacle B6/B7 -> up, left through the USBLC6 (rot 0,
    flow-through: D+ over pins 1-6, D- over 3-4) -> MCU PA12/PA11. The lines
    spread to the protector's pin rows and close up again either side of it;
    its middle pins (GND, VBUS) take vias in the space between them.

    The receptacle repeats D+/D- for the flipped plug: A6 (D+) joins B6 behind
    the pad row, A7 (D-) joins B7 by a link under the receptacle body, in front
    of the pads. Both links stay on F.Cu; they are stubs of under 2 mm.
    """
    w = B.USB_W
    d = D_USB
    jb7, jb6, ja6, ja7 = pad("J3", "B7"), pad("J3", "B6"), pad("J3", "A6"), pad("J3", "A7")
    rear = jb7[1] - 1.45 / 2 - 0.35        # behind the pad row
    m44, m45 = pad("U1", "44"), pad("U1", "45")
    ym = (m44[1] + m45[1]) / 2
    xm = m44[0] + 1.55 / 2                 # MCU pad tips
    u1, u6, u3, u4 = pad("U9", "1"), pad("U9", "6"), pad("U9", "3"), pad("U9", "4")
    yc = (u1[1] + u3[1]) / 2               # run through the protector
    xc = (jb7[0] + jb6[0]) / 2             # vertical run from the receptacle
    sp = (u3[1] - u1[1]) / 2 - d           # how far each line moves out to the pin rows
    xr = u6[0] + 1.475 / 2 + 1.15          # spread done right of the protector
    xl = u1[0] - 1.475 / 2 - 1.15          # and left of it
    # centre: up from the receptacle, left through the protector, diagonal down to the MCU
    xd = xl - sp - 0.7                     # diagonal down to the MCU starts here
    hb = TUNE["USB_DM"][1]                 # D- bump below its row, left of the protector
    # steep diagonal, then a straight 1.75 mm into the pins, leaving SWDIO (the pin
    # above D+) room to climb out between the pair and the package
    dp, dm = offset_pair([(xc, rear - 0.8), (xc, yc), (xd, yc), (xm + 1.75, ym), (xm, ym)], d)
    # dp/dm: upper/lower at the start (x order there); after the left turn D- is below
    dm_l, dp_l = (dp, dm) if dp[0][0] < dm[0][0] else (dm, dp)   # D- is the left one going up
    # the turn corner is the 2nd point; the horizontal run is points 1..2
    (x1m, ym1), (x2m, _) = dm_l[1], dm_l[2]
    (x1p, yp1), (x2p, _) = dp_l[1], dp_l[2]
    L("USB_DM", w, ("J3", "B7"), (jb7[0], rear - 0.25), (dm_l[0][0], rear - 0.8), (x1m, ym1),
      (xr + sp, ym1), (xr, u4[1]), ("U9", "4"), ("U9", "3"), (xl, u3[1]),
      (xl, u3[1] + hb), (xl - 0.35, u3[1] + hb), (xl - 0.35, u3[1]), (xl - 0.35 - sp, ym1),
      *dm_l[2:], ("U1", "44"))
    L("USB_DP", w, ("J3", "B6"), (jb6[0], rear - 0.25), (dp_l[0][0], rear - 0.8), (x1p, yp1),
      (xr + sp, yp1), (xr, u6[1]), ("U9", "6"), ("U9", "1"), (xl, u1[1]), (xl - sp, yp1),
      *dp_l[2:], ("U1", "45"))
    lw = 0.2
    L("USB_DP", lw, ("J3", "A6"), (ja6[0], rear), (jb6[0], rear))
    front = ja7[1] + 1.45 / 2 + 0.4
    L("USB_DM", lw, ("J3", "A7"), (ja7[0], front), (jb7[0], front), ("J3", "B7"))


# Signal pins that the CAN lines (or the USB pair) close in on F.Cu: each gets
# its own via beside the pad, placed by build.fanout() with the same rule as the
# plane vias (clear of the pairs' reference plane), and freerouting takes it
# from there on B.Cu.
FANOUT_SIGNALS = {(u, pin) for u in ("U2", "U3", "U4") for pin in ("1", "3", "4", "8")} | {
    ("C13", "1"), ("C16", "1"), ("C19", "1"),   # transceiver VCC decoupling (+5V_SYS)
}
# the MCU's GND pin among them leaves inward on a fixed dog-leg to its via
# The MCU's top-row pins sit between the package and CAN0: each leaves inward
# under the body on a fixed fan to its own via (centres >= 0.85 mm apart, 0.2 mm
# tracks), then repair.preroute() takes it from there. Points after the pad tip.
MCU_ESCAPES = {
    "63": [(17.9, 27.1)],                      # GND
    "62": [(19.25, 27.45), (18.95, 27.75)],    # CAN1_TX
    "61": [(19.75, 28.6)],                     # CAN1_RX
    "60": [(20.25, 27.45), (20.6, 27.75)],     # BOOT0
    "58": [(21.25, 28.6)],                     # CAN2_TX
    "57": [(21.75, 27.4), (22.1, 27.75)],      # CAN2_RX
}
SWDIO_VIA = (28.75, 26.6)    # SWDIO (PA13) sits right above USB D+ at the MCU: up, then down to B.Cu


# Connections routed by repair.preroute() before freerouting: the MCU's top-row
# pins sit between its package and CAN0, so their way out is planned while the
# board is still open.
PREROUTE = [
    # (the header pass-throughs are scripted: passthrough() below)
    ("VIN_PROT", ("C26", "1"), ("R17", "1")),
    # the transceivers' STB lines from the MCU's left side, the longest runs
    # (after the MCU's top row they found no way through)
    ("CAN2_STB", ("U1", "2"), ("U3", "8")),
    ("CAN3_STB", ("U1", "14"), ("U4", "8")),
    ("CAN1_STB", ("U1", "9"), ("U2", "8")),
    # the MCU's top row, from its fixed fan
    ("CAN1_RX", ("U1", "61"), ("U2", "4")),
    ("CAN1_TX", ("U1", "62"), ("U2", "1")),
    ("BOOT0", ("U1", "60"), ("R2", "1")),
    ("CAN2_TX", ("U1", "58"), ("U3", "1")),
    ("CAN2_RX", ("U1", "57"), ("U3", "4")),
    ("CAN3_TX", ("U1", "50"), ("U4", "1")),
    ("CAN3_RX", ("U1", "41"), ("U4", "4")),
]


def vias(pad):
    return [(net, B.spread(*q)) for net, q in _vias(lambda *p: B.unspread(*pad(*p)))]


def _vias(pad):
    """Fixed vias: (net, (x, y)). The USBLC6's VBUS pin sits between the USB
    lines, which close around it on F.Cu, so it drops to B.Cu right beside its
    pad (freerouting keeps its own vias off the pairs)."""
    u5 = pad("U9", "5")
    out = [("VBUS", (round(u5[0] + 1.475 / 2 + 0.3 + 0.2, 4), u5[1])), ("SWDIO", SWDIO_VIA)]
    out += [(NET_OF_MCU[pin], pts[-1]) for pin, pts in sorted(MCU_ESCAPES.items())]
    return out


NET_OF_MCU = {"63": "GND", "62": "CAN1_TX", "61": "CAN1_RX", "60": "BOOT0", "58": "CAN2_TX", "57": "CAN2_RX"}


# Where a pair may run uncoupled (x0, y0, x1, y1, why), board mm. Everywhere
# else on a pair, each line must sit at exactly width + gap from its partner.
# These are the header pin fields (odd-row pins squeeze between even-row pads),
# the splits around the tap clusters and through the relay, and the USB
# protector / receptacle / MCU pin pitch.
UNCOUPLED = {
    "CAN0": [(0, 0, 7.0, B.H0, "J1 pin field"), (48.9, 0, B.W0, B.H0, "J2 pin field")],
    "CAN2": [(0, 0, 28.4, 13.0, "J1 pin field, split around ESD/transceiver 3/termination"),
             (48.9, 0, B.W0, 13.0, "J2 pin field")],
    "CAN1_ADAS": [(0, 9.0, 33.0, 21.0, "J1 pin field, split around ESD/transceiver 1, relay COM contacts")],
    "CAN1_CAR": [(0, 18.0, 6.5, 22.0, "J1 pin field"),
                 (15.4, 16.9, 22.1, 22.0, "length-matching bumps on the L line"),
                 (22.1, 12.0, 48.9, 23.0, "relay NC contacts, split around ESD/transceiver 2"),
                 (48.9, 12.0, B.W0, 22.0, "J2 pin field")],
    "USB": [(39.0, 27.0, 44.0, 35.0, "receptacle pad pitch"),
            (31.6, 24.0, 40.5, 28.5, "spread through the USBLC6 flow-through pins"),
            (26.8, 27.5, 28.9, 30.5, "MCU pin pitch (0.5 mm)")],
}
UNCOUPLED = {k: [(*B.spread(x0, y0), *B.spread(x1, y1), why) for x0, y0, x1, y1, why in v]
             for k, v in UNCOUPLED.items()}

# No vias in the strip between J2's edge-side pin row and the board edge: their
# In2 antipads pinch the +3V3 plane there under board.IN2_NECK_MIN (check_in2).
# (x0, y0, x1, y1), board mm; build.dsn_prepare and repair.Grid honour it.
_J2 = placement.P["J2"]
VIA_KEEPOUT = [(_J2[0] + 1.0 + 0.75, _J2[1] - 10.0, B.W, _J2[1] + 10.0)]


# --- the header pass-throughs, scripted -------------------------------------
# J1 and J2 sit in the same orientation, so a pass-through pin is on the
# board-side row of one header and on the edge-side row of the other. Odd pins
# (the bus loops 3, 5, 13, 15) leave J1's edge-side row by squeezing between
# J1's board-side pads, which a thin track does. Even pins (IGN 2/14, 12 V
# 10/12) are 0.5 mm tracks and can't pass between J2's 1.5 mm pads on 2 mm
# pitch, which used to force every route around J2's ends and made them cross.
# Here every non-CAN pass-through runs on B.Cu in pin order, so none crosses
# another, and the wide ones enter J2's pin field on In2, where J2's other pads
# have no copper ring (build.passthrough_pads) and 1.2 mm between holes fits
# 0.5 mm. IGN can't take an In2 hop (it carries the comma's supply), so its
# J2 side is an F.Cu lane in the board-edge strip from the fuse F1 to pins 14
# and 2; J1.2 reaches J2.2 under the headers. Top group (loop 15, IGN 14,
# loop 13, 12 V 12) runs in the band spread() opened under the top parts, the
# bottom group (12 V 10, loops 5 and 3, IGN 2) in the band under CAN0. All in
# board mm; numbers checked against pads 1.5 mm, holes 0.8 mm, locators
# 1.4 mm at (7.7, 30.7) / (73.5, 30.7), 0.15 mm clearance.
PT_SIG_W = B.SIGNAL_CLASS_W
PT_IGN_W = 0.6


def passthrough(pad):
    """([(net, width, layer, [points])], [(net, (x, y))]); layer is "F", "B" or "In2"."""
    j1 = lambda n: pad("J1", str(n))   # noqa: E731
    j2 = lambda n: pad("J2", str(n))   # noqa: E731
    f1 = pad("F1", "1")
    s, v, g = PT_SIG_W, B.V12_W, PT_IGN_W
    T = [
        # top group, B.Cu lanes at y 8.4 / 8.95 / 9.4 / 9.95 (outermost first)
        ("IGN", g, "B", [j1(14), (5.8, 17.5), (5.8, 8.4), (f1[0], 8.4)]),
        ("IGN", g, "F", [(f1[0], 8.4), f1]),
        ("IGN", g, "F", [(f1[0], 8.4), (71.7, 8.4), (71.7, 17.5), j2(14)]),
        ("IGN", g, "F", [(71.7, 17.5), (71.7, 29.5), j2(2)]),
        ("BUS2_LOOP_15", s, "F", [j1(15), (3.6, 16.5), (6.6, 16.5)]),
        ("BUS2_LOOP_15", s, "B", [(6.6, 16.5), (6.6, 8.95), (66.6, 8.95), (66.6, 15.5), j2(15)]),
        ("BUS2_LOOP_13", s, "B", [j1(13), (3.6, 18.5), (7.2, 18.5), (7.2, 9.4), (66.1, 9.4), (66.1, 17.5), j2(13)]),
        ("VIN12_12", v, "B", [j1(12), (7.8, 19.5), (7.8, 9.95), (65.5, 9.95), (65.5, 18.5), (67.2, 18.5)]),
        ("VIN12_12", v, "In2", [(67.2, 18.5), (69.4, 18.5), j2(12)]),
        # bottom group, B.Cu lanes at y 32.0 / 32.6 / 33.05 / 33.7 (outermost last)
        ("VIN12_10", v, "B", [j1(10), (9.0, 21.5), (9.0, 32.0), (66.1, 32.0), (66.1, 20.5), (67.2, 20.5)]),
        ("VIN12_10", v, "In2", [(67.2, 20.5), (69.4, 20.5), j2(10)]),
        ("BUS0_LOOP_5", s, "B", [j1(5), (3.6, 26.5), (6.25, 26.5), (6.25, 32.6), (66.75, 32.6), (66.75, 25.5), j2(5)]),
        ("BUS0_LOOP_3", s, "B", [j1(3), (3.6, 28.5), (5.8, 28.5), (5.8, 33.05), (67.2, 33.05), (67.2, 27.5), j2(3)]),
        ("IGN", g, "B", [j1(2), (j1(2)[0], 33.7), (j2(2)[0], 33.7), j2(2)]),
    ]
    V = [("IGN", (f1[0], 8.4)), ("BUS2_LOOP_15", (6.6, 16.5)),
         ("VIN12_12", (67.2, 18.5)), ("VIN12_10", (67.2, 20.5))]
    return T, V


# J2 pads that lose their inner-layer rings, so the In2 hops pass between holes
PT_IN2_CLEAR = ("J2", [str(n) for n in range(1, 19) if n not in (10, 12)])


# Short links drawn straight on F.Cu (pad to adjacent pad, nothing between):
# left to the routers, these sometimes came out unjoined in crowded clusters.
# Each transceiver's VCC to its decoupling cap, each termination jumper to its
# resistor, and each split termination's midpoint resistor to its cap.
LOCAL_LINKS = [
    ("U2", "3", "C13", "1"), ("U3", "3", "C16", "1"), ("U4", "3", "C19", "1"),
    ("JP1", "2", "R5", "1"), ("JP2", "2", "R6", "2"), ("R6", "1", "C15", "1"),
    ("JP3", "2", "R7", "1"), ("R7", "2", "C18", "1"), ("JP4", "2", "R8", "2"),
    ("JP6", "2", "R10", "2"),
]


def local_links(pad, net_of):
    """[(net, width, "F", [a, b])]; net_of(ref, pad) names the pad's net."""
    out = []
    for u, a, c, k in LOCAL_LINKS:
        net = net_of(u, a)
        assert net == net_of(c, k), f"{u}.{a} and {c}.{k} are on different nets"
        out.append((net, B.POWER_W if net.startswith("+") else 0.25, "F", [pad(u, a), pad(c, k)]))
    return out
