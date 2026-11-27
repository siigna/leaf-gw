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
U4C = (17.5, 4.1)      # CAN2 (V-CAN tap), top left
U2C = (17.5, 13.6)     # CAN1 ADAS side
RELAY = (28.2, 17.5)   # rotation 180: pole B (L) left column, pole A (H) right
U3C = (41.7, 17.0)     # CAN1 car side
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
    "C19": (21.8, 3.1, 90),      # VCC
    "C20": (21.8, 5.1, 90),      # VIO
    "JP6": (23.6, 1.45, 270),     # hangs off the L line
    "R10": (23.85, 4.1, 0),
    "C21": (26.2, 5.8, 90),
    "JP5": (23.6, 6.75, 90),     # stands on the H line
    "R9": (26.2, 2.6, 90),

    # --- CAN1 ADAS side
    "D21": esd_at(U2C),
    "U2": (U2C[0], U2C[1], 180),
    "C13": (21.8, 12.2, 90),
    "C14": (22.3, 14.0, 0),
    "JP2": (11.0, 9.8, 90),      # stands on the L line
    "R6": (13.85, 9.15, 0),
    "C15": (16.9, 9.15, 0),
    "JP1": (11.0, 17.4, 270),    # hangs off the H line
    "R5": (13.85, 18.05, 0),

    "K1": (RELAY[0], RELAY[1], 180),

    # --- CAN1 car side
    "D22": esd_at(U3C),
    "U3": (U3C[0], U3C[1], 180),
    "C16": (46.4, 15.6, 90),
    "C17": (46.6, 17.6, 0),
    "JP4": (35.8, 13.2, 90),
    "R8": (38.65, 12.55, 0),
    "JP3": (35.8, 20.8, 270),
    "R7": (38.65, 21.45, 0),
    "C18": (41.7, 21.45, 0),

    # --- power entry and buck (top edge, right; IGN comes in at J2 pin 14)
    "D6": (57.3, 4.1, 90),       # TVS
    "F1": (52.6, 6.6, 0),
    "D7": (51.1, 2.1, 0),        # reverse-polarity diode
    "C26": (49.5, 6.0, 90),
    "R13": (47.9, 6.0, 90),
    "C24": (45.9, 2.1, 90),
    "C25": (43.8, 2.1, 90),
    "U7": (44.4, 6.2, 180),
    "C27": (40.6, 6.35, 90),
    "L1": (38.6, 2.5, 0),
    "R14": (38.6, 6.4, 90),
    "R15": (36.9, 6.4, 90),
    "D8": (33.8, 3.9, 90),
    "C28": (30.9, 2.1, 90),
    "C29": (30.9, 5.8, 90),
    "C30": (28.9, 2.0, 90),

    # --- MCU
    "U1": (MCU[0], MCU[1], 0),
    "C2": (14.7, 27.3, 90),      # VBAT pin 1
    "C7": (14.7, 25.1, 90),       # VDD pin 64
    "C3": (14.7, 32.77, 90),      # VDDA pin 13
    "C9": (13.4, 34.0, 90),      # VDDA bulk
    "C4": (19.73, 38.6, 0),       # VDD pin 19
    "C1": (22.3, 38.6, 0),       # VCAP pin 30
    "C5": (26.23, 38.6, 0),       # VDD pin 32
    "C6": (29.3, 25.3, 90),      # VDD pin 48
    "C8": (32.4, 38.7, 0),      # 3V3 bulk
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

    # --- 5 V OR-ing, LDO, power LED
    "D9": (31.0, 10.7, 0),
    "U8": (44.2, 11.4, 0),
    "C31": (47.4, 11.4, 90),
    "C32": (35.0, 10.7, 0),
    "C33": (41.4, 11.4, 90),
    "R16": (23.3, 9.3, 0),
    "D11": (20.0, 9.3, 0),

    # --- relay driver and watchdog
    "U5": (31.4, 31.6, 0),
    "C22": (34.4, 31.6, 90),
    "U6": (31.4, 35.3, 0),
    "C23": (34.4, 35.3, 90),
    "Q1": (14.6, 21.75, 0),
    "R11": (11.1, 21.8, 0),
    "R12": (29.0, 38.7, 0),
    "D5": (19.6, 21.8, 0),

    # --- ignition sense
    "R17": (1.8, 37.0, 90),
    "R18": (4.1, 37.0, 90),
    "C34": (6.3, 37.2, 90),
    "D12": (8.6, 36.4, 90),
}

# Silkscreen (SPEC "Silkscreen branding" and "PCB"). Text: (x, y, height,
# width, rotation, justification); x, y is the text anchor. Everything sits in
# the few strips clear of pads and part bodies; checks/layout.py verifies pad
# clearance and the logo's line and gap widths.
LOGO = (37.95, 22.5)          # top-left corner of the ~12 mm logo (logo.py)
SILK_TEXT = {
    "\u00a9 2026 Stephen Bouche \u00b7 MIT": (21.9, 23.5, 1.0, 0.65, 0, "left"),
    "leaf-gw rev {rev}": (49.1, 21.9, 1.0, 0.8, 90, "left"),
    "bench / test car only": (0.6, 7.35, 1.0, 0.8, 0, "left"),
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
LOGO = B.spread(*LOGO)
SILK_TEXT = {t: (*B.spread(x, y), *rest) for t, (x, y, *rest) in SILK_TEXT.items()}
BACK_TEXT = {t: (*B.spread(x, y), *rest) for t, (x, y, *rest) in BACK_TEXT.items()}
# a row label sits at its header row's height and its header's distance (from
# the compact drawing), not moved by the block its anchor falls in
_dx = {9.6: P["J1"][0] - J1X, 49.4: P["J2"][0] - J2X}
BACK_TEXT.update({t: (x + _dx[x], B.spread(J1X, y)[1], *rest) for t, (x, y, *rest) in BACK_ROWS.items()})
