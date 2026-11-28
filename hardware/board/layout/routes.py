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
    "ADAS_H_in": (2, 1.07),     # J1 -> transceiver 1
    "ADAS_L_out": (2, 0.44),    # transceiver 1 -> relay COM
    "CAR_H_in": (1, 1.17),      # relay -> transceiver 2
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
    return _spread(_lines, pad) + car_side(pad)


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
    yt, yb = 9.75, 16.75       # L high enough for the VIO cap C14 between it and pin 5
    xs = channel_x("D21", "U2")
    xd = 23.4                  # where the L line drops to COM_B
    k_com_b, k_com_a = pad("K1", "21"), pad("K1", "11")
    k_nc_b, k_nc_a = pad("K1", "22"), pad("K1", "12")
    xl_in, xl_out = k_nc_b[0] + 0.9, k_nc_a[0] - 0.9      # relay channel walls (pad inner edges)
    xr_out = k_nc_a[0] + 0.9 + 0.4
    y_gap_b = (k_com_b[1] + k_nc_b[1]) / 2               # between COM_B and NC_B
    y_gap_a = (k_com_a[1] + k_nc_a[1]) / 2               # between COM_A and NC_A
    L("CAN1_ADAS_L", w, ("J1", "11"), (3.6, 15.5), (5.6, 15.5), (7.9, 13.2), (7.9, yt + 0.9), (8.8, yt),
      *bumps((16.1, yt), (18.9, yt), TUNE["ADAS_L_out"], -1), (xd, yt), (xd, k_com_b[1]), ("K1", "21"))
    spur("CAN1_ADAS_L", xs, yt, pad("U2", "6")[1], ("D21", "2"), ("U2", "6"))
    L("CAN1_ADAS_H", w, ("J1", "9"), (3.6, 17.5), (5.6, 17.5), (6.35, yb),
      *bumps((6.6, yb), (9.4, yb), TUNE["ADAS_H_in"], +1), (xd - 0.2, yb),
      (xd + 0.05, y_gap_b), (xl_in, y_gap_b), (xl_out, k_com_a[1]), ("K1", "11"))
    spur("CAN1_ADAS_H", xs, yb, pad("U2", "7")[1], ("D21", "1"), ("U2", "7"))

    # --- CAN1 car side (J1/J2 pins 8 H even, 7 L odd): to the relay's NC contacts; the
    # rest, right of the relay, is in board mm (car_side)
    yc = 19.7                  # coupled centreline from J1 to the relay
    y_ab = (pad("K1", "22")[1] + pad("K1", "A2")[1]) / 2    # between NC_B and A2
    L("CAN1_CAR_L", w, ("J1", "7"), (3.6 - (yc - c - 19.5), yc - c), (22.2, yc - c), (22.2 + (yc - c - k_nc_b[1]), k_nc_b[1]),
      ("K1", "22"), (xl_in, k_nc_b[1]), (xl_out, y_gap_a))
    L("CAN1_CAR_H", w, ("J1", "8"), (4.6 + (20.5 - yc - c), yc + c), (xl_in - 1.8, yc + c), (xl_in, y_ab),
      (xl_out, k_nc_a[1]), ("K1", "12"))

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


def car_side(pad):
    """CAN1 car side right of the relay, in board mm (placement.CAR): from K1's
    NC contacts the pair runs coupled into the channel between K2's pad rows;
    the L line leaves up through K2's COM_B (21) and the H line down through
    COM_A (11), so the relay contacts sit on the lines with no stub. L then runs
    over the termination and transceiver 2, H under them, each with its spur
    into the ESD / transceiver channel, and both enter J2 like the other pairs."""
    w, c = B.CAN_W, D_CAN
    out = []

    def L(net, *pts):
        out.append((net, w, [pad(*p) if isinstance(p[0], str) else p for p in pts]))

    def spur(net, x, y_from, y_to, *pads):
        L(net, (x, y_from), (x, y_to))
        for p in pads:
            px, py = pad(*p)
            L(net, (x, py), (px, py))

    com_a, nc_a = pad("K1", "11"), pad("K1", "12")
    x0, y_gap = nc_a[0] - 0.9, (com_a[1] + nc_a[1]) / 2       # where the L line leaves K1
    k21, k11 = pad("K2", "21"), pad("K2", "11")
    yk = (k21[1] + k11[1]) / 2                                 # K2 channel centre line
    yt = k21[1] - 0.9 - 0.15 - w / 2 - 0.06                    # over K2's top pad row
    yb = k11[1] + 0.9 + 0.15 + w / 2 + 0.06                    # under its bottom row
    xj = nc_a[0] + 0.9 + 0.4                                   # clear of K1's pads
    xs = (pad("D22", "1")[0] + 1.475 / 2 + pad("U3", "6")[0] - 1.95 / 2) / 2
    j7, j8 = pad("J2", "7"), pad("J2", "8")
    xr = 64.1                                                  # L riser to J2, right of transceiver 2's escapes
    y8 = j7[1] + 1.0                                           # H into J2 between pins 7 and 5
    L("CAN1_CAR_L", (x0, y_gap), (xj, y_gap), (xj + (yk - c - y_gap), yk - c), (k21[0], yk - c), k21, (k21[0], yt),
      (xr, yt), (xr, j7[1] - 0.6), (xr + 0.6, j7[1]), ("J2", "7"))
    spur("CAN1_CAR_L", xs, yt, pad("U3", "6")[1], ("D22", "2"), ("U3", "6"))
    hin, hout = TUNE["CAR_H_in"], TUNE["CAR_H_out"]
    L("CAN1_CAR_H", ("K1", "12"), (xj, nc_a[1]), (xj + (nc_a[1] - yk - c), yk + c), (k11[0], yk + c), k11, (k11[0], yb),
      *bumps((48.3, yb), (53.2, yb), hin, -1), *bumps((61.3, yb), (65.5, yb), hout, -1),
      (66.0, yb), (66.0, y8 + 0.6), (66.6, y8), (j8[0] - 1.0, y8), ("J2", "8"))
    spur("CAN1_CAR_H", xs, yb, pad("U3", "7")[1], ("D22", "1"), ("U3", "7"))
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
    # SWCLK, from the MCU's top row across to the SWD pads in the corner: one fresh
    # build left it unrouted on all six freerouting attempts
    ("SWCLK", ("U1", "49"), ("TP2", "1")),
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
                 (15.4, 16.9, 22.1, 22.0, "length-matching bumps on the L line")],
    "USB": [(39.0, 27.0, 44.0, 35.0, "receptacle pad pitch"),
            (31.6, 24.0, 40.5, 28.5, "spread through the USBLC6 flow-through pins"),
            (26.8, 27.5, 28.9, 30.5, "MCU pin pitch (0.5 mm)")],
}
UNCOUPLED = {k: [(*B.spread(x0, y0), *B.spread(x1, y1), why) for x0, y0, x1, y1, why in v]
             for k, v in UNCOUPLED.items()}
# the car side right of the relay is drawn in board mm (car_side); only its run
# into K2's channel is coupled
UNCOUPLED["CAN1_CAR"] += [(23.0, 15.0, 34.45, 26.3, "relay NC contacts"),
                          (40.6, 15.0, B.W, 26.3, "K2 COM, split around ESD/transceiver 2, J2 pin field")]

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
# have no copper ring (PT_IN2_CLEAR) and 1.2 mm between holes fits
# 0.5 mm. IGN can't take an In2 hop (it carries the comma's supply), so its
# J2 side is an F.Cu lane in the board-edge strip from the fuse F1 to pins 14
# and 2; J1.2 reaches J2.2 under the headers. Top group (loop 15, IGN 14,
# loop 13) runs in the band spread() opened under the top parts, the bottom
# group (12 V 12 and 10, loops 5 and 3, IGN 2) in the band under CAN0. 12 V 12
# rides with the bottom group (pin order matches at both ends either way): in
# the top group its lane left the V-CAN cluster's supply only a 0.4 mm via
# window between the bundle and the CAN2 pair, which freerouting kept missing. All in
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
        # top group, B.Cu lanes at y 8.4 / 8.95 / 9.4 (outermost first)
        ("IGN", g, "B", [j1(14), (5.8, 17.5), (5.8, 8.4), (IGN_UP[0], 8.4)]),
        ("IGN", g, "F", [(IGN_UP[-1], 8.4), (71.7, 8.4), (71.7, 17.5), j2(14)]),
        ("IGN", g, "F", [(71.7, 17.5), (71.7, 29.5), j2(2)]),
        ("IGN", g, "F", [(F1_TAP[0], 8.4), (f1[0], 8.4)]),    # the fuse's tap
        ("BUS2_LOOP_15", s, "F", [j1(15), (3.6, 16.5), (6.6, 16.5)]),
        ("BUS2_LOOP_15", s, "B", [(6.6, 16.5), (6.6, 8.95), (66.6, 8.95), (66.6, 15.5), j2(15)]),
        ("BUS2_LOOP_13", s, "B", [j1(13), (3.6, 18.5), (7.2, 18.5), (7.2, 9.4), (66.1, 9.4), (66.1, 17.5), j2(13)]),
        # bottom group, B.Cu lanes at y 31.35 / 32.0 / 32.6 / 33.05 / 33.7 (outermost last)
        ("VIN12_12", v, "B", [j1(12), (9.7, 19.5), (9.7, 31.35), (65.4, 31.35), (65.4, 18.5), (67.2, 18.5)]),
        ("VIN12_12", v, "In2", [(66.35, 18.5), (67.2, 18.5), (69.4, 18.5), j2(12)]),
        ("VIN12_10", v, "B", [j1(10), (9.0, 21.5), (9.0, 32.0), (66.1, 32.0), (66.1, 20.5), (67.2, 20.5)]),
        ("VIN12_10", v, "In2", [(66.35, 20.5), (67.2, 20.5), (69.4, 20.5), j2(10)]),
        ("BUS0_LOOP_5", s, "B", [j1(5), (3.6, 26.5), (6.25, 26.5), (6.25, 32.6), (66.75, 32.6), (66.75, 25.5), j2(5)]),
        ("BUS0_LOOP_3", s, "B", [j1(3), (3.6, 28.5), (5.8, 28.5), (5.8, 33.05), (67.2, 33.05), (67.2, 27.5), j2(3)]),
        ("IGN", g, "B", [j1(2), (j1(2)[0], 33.7), (j2(2)[0], 33.7), j2(2)]),
        # K2's coil low side is boxed in by K1's pads, the car pair and the NO_A link:
        # it drops to B.Cu on two vias right beside its pad (placement.CAR)
        ("RELAY_COIL_LO", B.POWER_W, "F", [pad("K2", "A2"), K2_COIL_VIAS[0], K2_COIL_VIAS[1]]),
        ("RELAY_COIL_LO", B.POWER_W, "B", [K2_COIL_VIAS[0], K2_COIL_VIAS[1]]),
    ]
    V = [("IGN", (x, 8.4)) for x in IGN_UP + F1_TAP] + [("BUS2_LOOP_15", (6.6, 16.5)),
         ("VIN12_12", (67.2, 18.5)), ("VIN12_10", (67.2, 20.5)),
         ("VIN12_12", (66.35, 18.5)), ("VIN12_10", (66.35, 20.5))]    # two vias on each hop
    V += [("RELAY_COIL_LO", q) for q in K2_COIL_VIAS]
    return T, V


# IGN's layer changes carry the comma's supply (J1.14 -> J2.14), so each is
# several vias in a row, 0.85 mm apart (hole to hole 0.55 mm): up to the F.Cu
# edge lane, and the fuse's own tap off the B.Cu lane right of F1.
IGN_UP = (71.7, 70.85, 70.0)
K2_COIL_VIAS = ((34.3, 17.5), (34.3, 18.4))
F1_TAP = (63.25, 62.4)


# J2 pads that lose their inner-layer rings, so the In2 hops pass between holes
PT_IN2_CLEAR = ("J2", [str(n) for n in range(1, 19) if n not in (10, 12)])


# Short links drawn straight on F.Cu (pad to adjacent pad, nothing between):
# left to the routers, these sometimes came out unjoined in crowded clusters.
# Each transceiver's VCC to its decoupling cap, each termination jumper to its
# resistor, and each split termination's midpoint resistor to its cap.
LOCAL_LINKS = [
    ("U2", "3", "C13", "1"), ("U3", "3", "C16", "1"), ("U4", "3", "C19", "1"),
    ("U2", "5", "C14", "1"), ("U3", "5", "C17", "1"), ("U4", "5", "C20", "1"),     # VIO caps
    ("U5", "5", "C22", "1"), ("U6", "5", "C23", "1"),
    # ADAS-side termination along K1's top, car side beside K2
    ("JP2", "2", "R6", "2"), ("R6", "1", "C15", "1"), ("C15", "1", "R5", "2"), ("R5", "1", "JP1", "2"),
    ("K2", "24", "JP4", "1"), ("K2", "14", "JP3", "1"), ("JP4", "2", "R8", "2"), ("R8", "1", "R7", "2"),
    ("C18", "1", "R7", "2"), ("R7", "1", "JP3", "2"),
    ("JP6", "2", "R10", "2"),
    ("K1", "A1", "K2", "A1"),    # the coils in parallel: +5V_IGN
]


# Short F.Cu paths in board mm, (net, width, [points]); a point may be a pad.
# K1's NO contacts to the ADAS-side jumpers above the relay, and the buck's
# own copper (placement.POWER): the SW node, the hot loop's VIN and GND, the
# bootstrap and feedback nodes, the output and the input protection.
POWER_LINKS = [
    ("K1_NO_B", 0.25, [("JP2", "1"), (25.25, 16.9), ("K1", "24")]),
    ("K1_NO_A", 0.25, [("JP1", "1"), (37.785, 15.95), (33.4, 15.95), (32.7, 16.65), ("K1", "14")]),
    ("BUCK_SW", 0.8, [("U7", "6"), ("D8", "1")]),
    ("BUCK_SW", 0.8, [("L1", "1"), ("C27", "2"), ("D8", "1")]),
    ("BUCK_CB", 0.3, [("C27", "1"), ("U7", "1")]),
    ("VIN_PROT", 0.5, [("U7", "5"), (41.3, 6.16), (41.8, 6.6), (44.4, 6.6), ("C25", "1"), ("C24", "1"), ("D7", "1")]),
    ("VIN_PROT", 0.5, [("C26", "1"), (41.3, 6.16)]),
    ("VIN_PROT", 0.5, [("R13", "1"), (41.225, 7.2), (41.8, 6.6)]),
    ("BUCK_SHDN", 0.25, [("U7", "4"), ("R13", "2")]),
    ("GND", 0.6, [("C26", "2"), ("D8", "2")]),
    ("GND", 0.6, [("C25", "2"), (45.05, 3.0)]),
    ("GND", 0.6, [("C24", "2"), ("C25", "2")]),
    ("BUCK_FB", 0.25, [("R14", "2"), ("R15", "1"), ("U7", "3")]),
    ("+5V_IGN", 0.6, [("L1", "2"), ("C28", "1"), ("C29", "1")]),
    ("+5V_IGN", 0.4, [("C29", "1"), ("C30", "1")]),
    ("+5V_IGN", 0.25, [("C28", "1"), ("R14", "1")]),    # feedback sense, at the output cap
    # the output leaves the group between C29 and C28 to TP8 and the OR diode
    ("+5V_IGN", 0.3, [(31.615, 5.21), (31.615, 9.3), ("TP8", "1")]),
    ("+5V_IGN", 0.4, [("TP8", "1"), (33.0, 9.6), ("D9", "2")]),
    ("IGN_FUSED", 0.67, [("D7", "2"), ("F1", "2")]),
    ("IGN_FUSED", 0.67, [("D6", "1"), (56.9, 4.5), ("F1", "2")]),
]


def local_links(pad, net_of):
    """[(net, width, "F", [points])]; net_of(ref, pad) names the pad's net."""
    out = []
    for u, a, c, k in LOCAL_LINKS:
        net = net_of(u, a)
        assert net == net_of(c, k), f"{u}.{a} and {c}.{k} are on different nets"
        out.append((net, B.POWER_W if net.startswith("+") else 0.25, "F", [pad(u, a), pad(c, k)]))
    for net, w, pts in POWER_LINKS:
        for p in pts:
            assert not isinstance(p[0], str) or net_of(*p) == net, f"{p[0]}.{p[1]} is not on {net}"
        out.append((net, w, "F", [pad(*p) if isinstance(p[0], str) else p for p in pts]))
    return out
