"""Shared layout constants: board size, stack-up, JLCPCB rules, net classes.

Imported by the build scripts and by the checks, so the checks and the board
are held to the same numbers. Everything is in millimetres.
"""

import os

import impedance

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_DIR = os.path.dirname(HERE)
OUT = os.path.join(BOARD_DIR, "out")
PCB = os.environ.get("LGW_PCB") or os.path.join(HERE, "leaf_gw.kicad_pcb")
NETLIST = os.path.join(OUT, "leaf_gw.net")

REVISION = "A"

# Board outline: W x H, corner radius. SPEC: about 70 x 45 mm, at most 75 x 50.
W, H, CORNER = 75.0, 50.0, 1.0

# placement.py and routes.py are drawn on the first, 59 x 39.5 mm board, where
# freerouting left 1-3 connections open. spread() opens that drawing up into
# the bigger outline by shifting whole blocks rigidly, so every scripted route
# keeps its shape: x shifts at vertical cuts (only horizontal fixed copper
# crosses them), y shifts below a top band and below the CAN0 run (risers at
# the header columns, so the headers move in one piece). A part moves with the
# block its centre is in; routes._spread() asserts no fixed segment is bent.
W0, H0 = 59.0, 39.5
X_CUTS = ((9.5, 4.0), (33.6, 7.0), (48.6, 5.0))   # (x0 cut, added mm): J1 field | clusters, MCU | relay .. car side | J2 field
Y_TOP = (8.0, 3.0)                                # below the top band (CAN2 cluster, power entry)
Y_LOW = (24.3, 28.0, 7.0, 48.9, 7.5)              # below CAN0 between the header columns (x 7..48.9), below the headers outside
assert abs(W0 + sum(d for _, d in X_CUTS) - W) < 1e-9 and abs(H0 + Y_TOP[1] + Y_LOW[4] - H) < 1e-9


def shift(x, y):
    """Displacement of a point at (x, y) on the compact drawing."""
    dx = sum(d for c, d in X_CUTS if x > c)
    y_low, y_out, x0, x1, d_low = Y_LOW
    dy = (Y_TOP[1] if y > Y_TOP[0] else 0.0) + (d_low if y > (y_low if x0 < x < x1 else y_out) else 0.0)
    return dx, dy


def spread(x, y):
    dx, dy = shift(x, y)
    return (round(x + dx, 4), round(y + dy, 4))


def unspread(x, y):
    """The compact-drawing point that spread() takes to (x, y)."""
    for dx in sorted({sum(d for c, d in X_CUTS[:k]) for k in range(len(X_CUTS) + 1)}):
        for dy in (0.0, Y_TOP[1], Y_LOW[4], Y_TOP[1] + Y_LOW[4]):
            p = (round(x - dx, 4), round(y - dy, 4))
            if shift(*p) == (dx, dy):
                return p
    raise ValueError(f"({x}, {y}) is in a gap spread() opened")
ORIGIN = (100.0, 100.0)  # where board (0, 0) sits on the KiCad sheet

# JLCPCB rigid PCB capabilities, multilayer, 1 oz outer (jlcpcb.com/capabilities/pcb-capabilities,
# read 2026-11-26). We hold to SPEC's "standard" 0.127 mm rather than JLC's 0.09 mm minimum.
JLC = {
    "track_min": 0.127,        # SPEC (JLC min 0.09)
    "clearance_min": 0.127,    # SPEC (JLC min 0.09)
    "via_drill": 0.3,          # SPEC; JLC min 0.15, preferred min 0.2
    "via_diameter": 0.6,       # JLC: diameter >= hole + 0.1 (0.15 preferred) -> 0.15 mm ring
    "via_ring_min": 0.15,      # JLC PTH annular ring, absolute minimum 0.15 (1 oz multilayer)
    "hole_min": 0.3,
    "hole_to_hole": 0.5,       # JLC: via hole-to-hole 0.2, pad hole-to-hole 0.45
    "copper_edge": 0.25,       # JLC: >= 0.2 from a routed edge
    "hole_clearance": 0.25,    # JLC: via hole to track 0.2, PTH to track 0.28 (pads keep 0.25 from their own ring)
    "silk_width_min": 0.15,    # JLC silkscreen min line width
    "silk_text_min": 1.0,      # JLC min text height
    "silk_to_pad": 0.15,       # JLC: min distance between pad and silkscreen
    "mask_dam_min": 0.10,      # JLC solder mask bridge, green, 1 oz
}

# JLC04161H-7628 (jlcpcb.com/impedance, read 2026-11-26), top to bottom.
STACKUP = [
    ("F.SilkS", "Top Silk Screen", None, None),
    ("F.Paste", "Top Solder Paste", None, None),
    ("F.Mask", "Top Solder Mask", 0.01, 3.8),
    ("F.Cu", "copper", 0.035, None),
    ("dielectric 1", "prepreg", 0.2104, 4.4),   # 7628 x1
    ("In1.Cu", "copper", 0.0152, None),
    ("dielectric 2", "core", 1.065, 4.6),
    ("In2.Cu", "copper", 0.0152, None),
    ("dielectric 3", "prepreg", 0.2104, 4.4),   # 7628 x1
    ("B.Cu", "copper", 0.035, None),
    ("B.Mask", "Bottom Solder Mask", 0.01, 3.8),
    ("B.Paste", "Bottom Solder Paste", None, None),
    ("B.SilkS", "Bottom Silk Screen", None, None),
]
LAYER_ROLES = {"F.Cu": "signal", "In1.Cu": "GND", "In2.Cu": "+3V3", "B.Cu": "signal"}

# Differential pairs: geometry from impedance.coupled() (Garg-Bahl) on L1 over L2.
CAN_W, CAN_GAP = impedance.CAN["w"], impedance.CAN["s"]
USB_W, USB_GAP = impedance.USB["w"], impedance.USB["s"]

PAIRS = {  # name: (P net, N net, class)
    "CAN0": ("CAN0_H", "CAN0_L", "CAN"),
    "CAN1_ADAS": ("CAN1_ADAS_H", "CAN1_ADAS_L", "CAN"),
    "CAN1_CAR": ("CAN1_CAR_H", "CAN1_CAR_L", "CAN"),
    "CAN2": ("CAN2_H", "CAN2_L", "CAN"),
    "USB": ("USB_DP", "USB_DM", "USB"),
}

V12_W = 0.5      # SPEC: 12 V input tracks at least 0.5 mm
POWER_W = 0.4
SIGNAL_W = 0.15
# freerouting necks a track down to 3/4 of its class width where it must pass
# between pads; the class widths below keep a necked track at or above the
# minimum (0.17 -> 0.1275 >= 0.127, 0.67 -> 0.5025 >= 0.5).
NECK = 0.75
SIGNAL_CLASS_W = 0.17
V12_CLASS_W = 0.67

# Net classes: name -> (track width, clearance, nets). Unlisted nets are Default.
NET_CLASSES = {
    "Default": (SIGNAL_CLASS_W, 0.15, []),
    "CAN": (CAN_W, 0.15, [n for p in PAIRS.values() if p[2] == "CAN" for n in p[:2]]),
    "USB": (USB_W, 0.15, ["USB_DP", "USB_DM"]),
    "12V": (V12_CLASS_W, 0.15, ["IGN", "IGN_FUSED", "VIN_PROT", "VIN12_10", "VIN12_12"]),
    "Power": (POWER_W, 0.15, ["GND", "+3V3", "+5V_SYS", "+5V_IGN", "VBUS", "BUCK_SW", "RELAY_COIL_LO"]),
}


def net_class(net):
    for name, (_, _, nets) in NET_CLASSES.items():
        if net in nets:
            return name
    return "Default"

# Footprints on the PCB that are not in the netlist (no pads with nets).
BOARD_ONLY = {"H1", "H2", "LOGO"}

# Pair terminals, (P pad, N pad) per device; the first is the reference end.
# The length mismatch check runs from it to each of the others.
PAIR_TERMINALS = {
    # bus ends and transceivers; the ESD arrays, termination jumpers and relay NC
    # pads hang off the lines by mirrored spurs and are not separate ends
    "CAN0": [(("J1", "4"), ("J1", "6")), (("J2", "4"), ("J2", "6"))],
    "CAN2": [(("J1", "16"), ("J1", "18")), (("J2", "16"), ("J2", "18")), (("U4", "7"), ("U4", "6"))],
    "CAN1_ADAS": [(("J1", "9"), ("J1", "11")), (("U2", "7"), ("U2", "6")), (("K1", "11"), ("K1", "21"))],
    "CAN1_CAR": [(("J1", "8"), ("J1", "7")), (("J2", "8"), ("J2", "7")), (("U3", "7"), ("U3", "6"))],
    "USB": [(("J3", "B6"), ("J3", "B7")), (("U1", "45"), ("U1", "44"))],
}
MISMATCH_MAX = 1.0      # mm, SPEC
# Pair tracks narrower than the pair width are allowed only as these stubs:
# the USB receptacle's plug-flip links (A6-B6, A7-B7), within this radius of J3's pads.
NARROW_STUBS = {"USB_DP": ("J3", 2.5), "USB_DM": ("J3", 2.5)}
# Reference plane: a disc this much wider than the track must lie on In1 GND
# fill. One prepreg height beyond the track edge; two left freerouting too few
# via spots to finish on two signal layers (README "Known limits").
H_PREPREG = 0.2104
REF_MARGIN = 1 * H_PREPREG
# In2 (the +3V3 plane) carries only the VIN12 hops into J2 (routes.passthrough) and, at
# most, repair hops of this length; its +3V3 fill must keep a neck at least
# IN2_NECK_MIN wide everywhere it joins (checked by eroding the fill).
IN2_NETS = ()   # the VIN12 hops into J2 are ~3.6 mm, inside IN2_HOP_MAX
IN2_HOP_MAX = 5.0
IN2_NECK_MIN = 1.0
V3V3_LOAD = 0.150   # A, SPEC "Power": about 150 mA board total, an upper bound for 3V3
INNER_CU = 0.0152   # mm, JLC04161H-7628 inner copper

# Connector mating keepout: no other courtyard within the header body grown by this.
HEADER_KEEPOUT = 0.5
# USB-C: receptacle front within this of the bottom edge; plug overmold zone
# (USB Type-C spec max overmold width 12.35 mm) free of courtyards near the edge.
USB_EDGE_TOL = (-0.1, 0.6)
USB_PLUG_HALF_W = 12.35 / 2
USB_PLUG_DEPTH = 1.0
