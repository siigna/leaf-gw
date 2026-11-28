"""Where every part goes: ref -> (x, y, rotation), board mm, top side.

The numbers below are on the compact 59 x 39.5 mm drawing; the end of this
file opens them up with board.spread() (see board.py).

Board (0, 0) is the top-left corner; x right, y down. The two harness headers
sit on the short edges in the same orientation (rotation 90: pin 1 at the
bottom, even row toward +x), so pin n of J1 and J2 is at the same height and
the pass-through nets run straight across.

Blocks:
  - power entry (PTC, TVS, reverse diode) and the buck along the top edge, left
  - CAN2 (V-CAN tap, transceiver 3) cluster along the top edge, right
  - CAN1 ADAS-side cluster (transceiver 1) next to J1, then the relay, then the
    CAN1 car-side cluster (transceiver 2): the relay sits on the CAN1 lines
    between the two halves
  - CAN0 passes straight through under them
  - MCU, crystal, decoupling, USB-C (bottom edge), SWD pads, DFU button below

Rotations of two-pin parts: 0 = pin 1 left, 90 = pin 1 down, 180 = pin 1
right, 270 = pin 1 up.
"""

import board as B

# Header geometry (footprint frame): pins at x = -8..8 step 2, odd row y = -1,
# even row y = +1. At rotation 90 a footprint point (x, y) lands at (cx + y, cy - x).
J1X, JY = 3.6, 18.5
J2X = B.W0 - 5.6


def header_pin(jx, n):
    """Board position of pin n on a header centred at (jx, JY)."""
    col = (n - 1) // 2
    return (jx + (-1 if n % 2 else 1), JY + 8 - 2 * col)


# CAN clusters. Transceivers sit at rotation 180 so CANL (pin 6) is above
# CANH (pin 7) on the left-hand pin column, facing the bus; the ESD array sits
# just left of them at rotation 180 (pads 1/2 on its right, facing the
# transceiver). routes.py runs the bus lines around each cluster.
U4C = (17.5, 4.85)     # CAN2 (V-CAN tap), top left; low enough for C20 between pin 5 and the L line
U2C = (17.5, 13.6)     # CAN1 ADAS side
RELAY = (28.2, 18.0)   # rotation 180: pole B (L) left column, pole A (H) right
MCU = (22.0, 31.0)
USB = (40.6, 36.0)


def esd_at(u):
    return (u[0] - 5.9, u[1], 180)


P = {
    "J1": (J1X, JY, 90),
    "J2": (J2X, JY, 90),
    "H1": (2.9, 4.0, 0),
    "H2": (51.0, 37.0, 0),

    # --- CAN2 (V-CAN tap), top left
    "D23": esd_at(U4C),
    "U4": (U4C[0], U4C[1], 180),
    "C19": (21.8, 3.85, 90),     # VCC
    "C20": (15.5, 1.58, 0),      # VIO, between pin 5 and the L line
    "JP6": (23.6, 1.45, 270),    # hangs off the L line
    "R10": (23.85, 4.1, 180),    # pin 2 (L) under JP6, pin 1 (MID) toward R9/C21
    "C21": (26.2, 6.2, 90),
    "JP5": (23.6, 8.25, 90),     # stands on the H line
    "R9": (26.2, 2.6, 90),

    # --- CAN1 ADAS side
    "D21": esd_at(U2C),
    "U2": (U2C[0], U2C[1], 180),
    "C13": (21.8, 12.2, 90),
    "C14": (15.5, 10.33, 0),     # VIO, between pin 5 and the L line

    "K1": (RELAY[0], RELAY[1], 180),

    # --- MCU
    "U1": (MCU[0], MCU[1], 0),
    "C2": (14.7, 27.3, 90),      # VBAT pin 1
    "C7": (14.7, 25.1, 90),       # VDD pin 64
    "C3": (14.7, 32.77, 90),      # VDDA pin 13
    "C9": (13.4, 34.0, 90),      # VDDA bulk
    "C4": (19.73, 38.6, 0),       # VDD pin 19
    "C1": (24.525, 38.6, 180),   # VCAP pin 30, pad 1 right under the pin
    "C5": (27.0, 38.6, 0),       # VDD pin 32
    "C6": (29.3, 25.3, 90),      # VDD pin 48
    "C8": (32.6, 38.7, 0),      # 3V3 bulk
    "C12": (14.2, 30.3, 90),     # NRST
    "Y1": (11.5, 28.6, 270),
    "C10": (11.8, 24.8, 0),
    "C11": (11.8, 32.4, 0),
    "R1": (6.6, 33.6, 90),      # NRST pull-up
    "R3": (16.6, 38.6, 0),       # BOOT1 pull-down
    "SW1": (56.3, 33.6, 90),     # DFU
    "TP6": (51.4, 30.6, 0),      # BOOT0
    "R2": (51.4, 33.0, 0),       # BOOT0 pull-down
    "TP1": (1.6, 30.7, 0),       # SWDIO
    "TP2": (4.3, 30.7, 0),       # SWCLK
    "TP3": (7.0, 30.7, 0),       # NRST
    "TP4": (1.6, 33.4, 0),       # 3V3
    "TP5": (4.3, 33.4, 0),       # GND
    "D1": (11.6, 37.6, 90),       # status LED
    "R4": (13.4, 37.6, 90),

    # --- USB
    "J3": (USB[0], USB[1], 0),
    "U9": (35.9, 26.3, 0),
    "R19": (36.3, 29.3, 180),
    "R20": (47.4, 36.4, 90),
    "D10": (47.4, 31.6, 90),

    # --- relay driver and watchdog
    "U5": (31.4, 31.6, 0),
    "U6": (31.4, 35.3, 0),
    "Q1": (14.6, 21.75, 0),
    "R11": (11.1, 21.8, 0),
    "R12": (29.5, 38.7, 0),
    "D5": (19.6, 21.8, 0),

    # --- ignition sense (the divider's top, R17, sits at the 12 V source: POWER below)
    "R18": (4.1, 37.0, 90),
    "C34": (6.3, 37.2, 90),
    "D12": (8.6, 36.4, 90),
}

# Silkscreen (SPEC "Silkscreen branding" and "PCB"). Text: (x, y, height,
# width, rotation, justification); x, y is the text anchor. Everything sits in
# the few strips clear of pads and part bodies; checks/layout.py verifies pad
# clearance and the logo's line and gap widths.
SILK_TEXT = {
    "\u00a9 2026 Stephen Bouche \u00b7 MIT": (21.9, 24.0, 1.0, 0.65, 0, "left"),
    "leaf-gw rev {rev}": (49.1, 21.9, 1.0, 0.8, 90, "left"),
    "bench / test car only": (1.2, 7.75, 1.0, 0.8, 0, "left"),
}
# Back side (no parts there): what each header pin carries, which header goes
# where, and the warning again, large. Bottom text reads mirrored from the top.
PIN_NAMES = {1: "GND", 2: "IGN", 3: "bus0 loop", 4: "CAN0 H", 5: "bus0 loop", 6: "CAN0 L",
             7: "CAN1 L car", 8: "CAN1 H car", 9: "CAN1 H ADAS", 10: "12V", 11: "CAN1 L ADAS",
             12: "12V", 13: "bus2 loop", 14: "IGN", 15: "bus2 loop", 16: "CAN2 H", 17: "GND", 18: "CAN2 L"}
BACK_ROWS = {}   # one per header row, at that row's height
for _col in range(9):
    _odd, _even = 2 * _col + 1, 2 * _col + 2
    _y = header_pin(J1X, _odd)[1]
    # justification is as seen from the top; mirrored text on the back runs the other way
    BACK_ROWS[f"{_odd} {PIN_NAMES[_odd]} / {_even} {PIN_NAMES[_even]}"] = (9.6, _y, 1.0, 0.6, 0, "right")
    _right = {9: "n/c", 11: "n/c"}
    BACK_ROWS[f"{_odd} {_right.get(_odd, PIN_NAMES[_odd])} / {_even} {PIN_NAMES[_even]} "] = (49.4, _y, 1.0, 0.6, 0, "left")
# Drawn as knockout text (a filled silkscreen box with the letters left bare),
# so the warning and the two header names stand out.
KNOCKOUT = {"bench / test car only", "CAR HARNESS", "TO BOX (9/11 open)", "BENCH / TEST CAR ONLY"}
# The ESD paw mark (logo.esd_paw) on the back, board mm of its top-left corner
# as seen from the top (it is mirrored onto the back).
ESD_PAW = (57.0, 36.5)
# QR code to the repository (logo.qr) on the back, board mm of its top-left
# corner as seen from the top; the URL is written under it.
QR = (30.1, 13.0)
# Functional labels, placed by build.labels() next to their part:
# (text, part, side, text height mm).
LABELS = [   # the most crowded first: each label placed blocks spots for the next
    ("PWR", "D11", "top", 1.0),
    ("V-CAN TERM", "JP5", "top", 1.0),   # JP6, the same port right above it, is boxed in
    ("ADAS TERM", "JP1", "top", 1.0),    # the row JP2 .. JP1 along K1's top
    ("CAR TERM", "JP3", "top", 1.0),     # JP3/JP4 beside K2, the car-side termination relay
    ("VIN", "TP7", "top", 1.0), ("5V IGN", "TP8", "top", 1.0), ("5V SYS", "TP9", "top", 1.0),
    ("GND", "TP10", "top", 1.0),
    ("DIO", "TP1", "top", 1.0), ("CLK", "TP2", "top", 1.0), ("RST", "TP3", "top", 1.0),
    # SWD's lower row is boxed in (TP1/TP2 above, R1/R17/R18 around, the edge):
    # named on a line above the upper row's labels instead
    ("lower: 3V3 GND", "TP1", "top", 1.0),
    ("BOOT0", "TP6", "top", 1.0), ("DFU", "SW1", "top", 1.0),
    ("STAT", "D1", "top", 1.0),
    ("USB (bench)", "J3", "top", 1.0),
    ("CAR HARNESS", "J1", "top", 1.0), ("TO BOX", "J2", "top", 1.0),
]
BACK_TEXT = {
    "CAR HARNESS": (7.6, 2.5, 1.2, 1.0, 0, "right"),
    "TO BOX (9/11 open)": (51.4, 2.5, 1.2, 1.0, 0, "left"),
    "BENCH / TEST CAR ONLY": (22.0, 31.0, 1.5, 1.2, 0, "center"),
    "leaf-gw rev {rev}": (25.0, 34.0, 1.2, 1.0, 0, "center"),
    "\u00a9 2026 Stephen Bouche \u00b7 MIT": (25.0, 36.2, 1.0, 0.7, 0, "center"),
}


# Open the drawing up to the real outline (board.spread); the mounting holes go
# to two opposite corners of the real board.
P = {r: (*B.spread(x, y), rot) for r, (x, y, rot) in P.items()}
P["H1"] = (3.0, 3.0, 0)
P["H2"] = (B.W - 3.0, B.H - 3.0, 0)
P["SW1"] = (P["SW1"][0], P["SW1"][1] - 3.6, 90)   # up out of H2's corner
# Top-left corner of the ~10.5 mm copper leaf (logo.py, build.logo_footprint), in
# board mm: the one spot on the top side about 11 mm square that no fixed
# copper (CAN, USB pairs), pad or courtyard crosses; the routers go around it.
LOGO = (52.75, 27.75)
SILK_TEXT = {t: (*B.spread(x, y), *rest) for t, (x, y, *rest) in SILK_TEXT.items()}
BACK_TEXT = {t: (*B.spread(x, y), *rest) for t, (x, y, *rest) in BACK_TEXT.items()}
# a row label sits at its header row's height and its header's distance (from
# the compact drawing), not moved by the block its anchor falls in
_dx = {9.6: P["J1"][0] - J1X, 49.4: P["J2"][0] - J2X}
BACK_TEXT.update({t: (x + _dx[x], B.spread(J1X, y)[1], *rest) for t, (x, y, *rest) in BACK_ROWS.items()})

# --- placed in board mm, after the spread -------------------------------------
# These groups sit in room spread() opened (or straddle one of its cuts), so
# they are placed on the real board, and so are their scripted routes
# (routes.car_side, routes.POWER_LINKS): nothing here moves with a cut.

# CAN1 car side, right of the relay. K2 (rotation 90: pad rows top/bottom) takes
# the car pair through the channel between its rows; the L line leaves up
# through COM_B (21), the H line down through COM_A (11). Its NO pads (24 top
# right, 14 bottom right) feed the car-side termination beside it, then the
# ESD array and transceiver 2 between the two lines, as on the other ports.
U3C = (57.5, 21.0)
CAR = {
    "K2": (39.25, 21.0, 90),
    "JP4": (46.29, 17.5, 0),     # K2_NO_B (L leg)
    "JP3": (46.29, 24.5, 0),     # K2_NO_A (H leg)
    "C18": (46.29, 21.0, 180),
    "R8": (48.81, 17.8, 90),
    "R7": (48.81, 20.9, 90),
    "D22": (U3C[0] - 5.9, U3C[1], 180),
    "U3": (U3C[0], U3C[1], 180),
    "C17": (55.5, 17.73, 0),     # VIO, between pin 5 and the L line
    "C16": (62.2, 19.6, 90),     # VCC
}
# ADAS-side termination, off K1's NO pads (24, 14) along the top of the relay
ADAS_TERM = {
    "JP2": (25.9, 14.2, 0),      # K1_NO_B (L leg)
    "R6": (29.165, 14.2, 180),
    "C15": (31.515, 14.15, 270),
    "R5": (33.865, 14.2, 180),
    "JP1": (37.135, 14.2, 180),  # K1_NO_A (H leg)
}
# Power, top band. Input protection on the right (IGN taps the B.Cu IGN lane at
# F1), the buck as one tight group left of it: D8 right above U7's SW pin, the
# input caps (C26 first) right of VIN with their GND pads under D8's anode,
# L1 beside D8 sharing the SW node with the bootstrap cap C27, the output caps
# under L1's output with the feedback divider between them and U7's FB pin.
# The LDO and power LED go to the strip under the V-CAN cluster.
POWER = {
    "D8": (42.0, 2.6, 0),
    "U7": (38.863, 6.16, 0),
    "C27": (37.655, 2.87, 90),
    "L1": (34.515, 2.1, 180),
    "C26": (42.483, 5.21, 0),
    "C25": (45.05, 6.16, 90),
    "C24": (47.12, 6.16, 90),
    "R13": (40.4, 8.75, 180),
    "R14": (35.22, 5.55, 0),
    "R15": (35.22, 7.11, 180),
    "C28": (32.65, 6.16, 270),
    "C29": (30.58, 6.16, 270),
    "C30": (30.6, 3.4, 90),
    "D7": (52.5, 7.1, 0),        # reverse-polarity diode
    "D6": (54.5, 2.9, 180),      # TVS
    "F1": (59.06, 7.2, 180),     # pad 1 (IGN) right, at the lane tap
    "R17": (50.5, 9.7, 0),       # IGN divider top, at the 12 V source
    "TP7": (47.1, 9.9, 0),       # VIN_PROT
    "TP10": (49.5, 2.6, 0),      # GND, by the buck
    "TP8": (31.95, 9.9, 0),      # +5V_IGN
    "D9": (35.7, 9.6, 180),      # 5 V OR-ing
    "TP9": (40.4, 10.87, 0),     # +5V_SYS
    "U8": (13.9, 10.75, 0),
    "C33": (10.8, 11.0, 90),
    "C31": (16.8, 10.75, 90),
    "C32": (18.6, 10.75, 90),
    "D11": (66.4, 3.0, 0),       # power LED, by the input
    "R16": (66.4, 5.0, 0),
    # MCU-side decoupling at the supply pin (U5 VCC, U6 VDD: pin 5)
    "C22": (35.02, 41.6, 270),
    "C23": (35.02, 45.3, 270),
}
P.update(CAR)
P.update(ADAS_TERM)
P.update(POWER)
