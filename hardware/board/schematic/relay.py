"""Fail-open relay and its gating (SPEC.md "Fail-open relay").

K1 de-energized: each pole's NC contact joins the ADAS-side and car-side
Chassis CAN line (pole A = H, pole B = L), so the car runs stock. The coil is
energized only while RELAY_EN (PB12) is high AND the watchdog's RESET output
(on NRST) is high. Omron G6K-2F-Y terminals (en-g6k.pdf p.6): 1 coil+, 8 coil-,
3/6 COM, 2/7 NC, 4/5 NO; KiCad's symbol/footprint call them A1, A2, 11/21,
12/22, 14/24.
"""

from nets import nc
from parts import part


def build(n):
    k = part("RELAY", ref="K1")
    k["11"] += n.CAN1_ADAS_H  # pole A COM (datasheet pin 3)
    k["12"] += n.CAN1_CAR_H   # pole A NC  (pin 2)
    k["21"] += n.CAN1_ADAS_L  # pole B COM (pin 6)
    k["22"] += n.CAN1_CAR_L   # pole B NC  (pin 7)
    nc(k["14"], "relay NO, pole A: energized = bypass open, nothing to connect")
    nc(k["24"], "relay NO, pole B: energized = bypass open, nothing to connect")
    k["A1"] += n.P5V_IGN       # coil+ only from IGN, so USB power alone stays in passthrough
    k["A2"] += n.RELAY_COIL_LO

    flyback = part("D_1N4148W")
    flyback["K"] += n.P5V_IGN
    flyback["A"] += n.RELAY_COIL_LO

    q = part("NMOS", ref="Q1")
    q["D"] += n.RELAY_COIL_LO
    q["S"] += n.GND
    q["G"] += n.RELAY_GATE
    r = part("R_100k")  # gate pull-down: off while the AND gate is unpowered
    r[1] += n.RELAY_GATE
    r[2] += n.GND

    gate = part("AND", ref="U5")
    gate[1] += n.RELAY_EN   # A: MCU relay enable
    gate[2] += n.NRST       # B: watchdog RESET (open drain, shared with MCU NRST)
    gate[4] += n.RELAY_GATE
    gate["VCC"] += n.P3V3
    gate["GND"] += n.GND
    c = part("C_100n")
    c[1] += n.P3V3
    c[2] += n.GND
    r = part("R_100k")  # RELAY_EN pull-down: PB12 floats in reset / unprogrammed
    r[1] += n.RELAY_EN
    r[2] += n.GND

    # Watchdog: RESET goes low for ~200 ms if WDI has no edge for 0.9-2.5 s
    # (SLVS165O 6.8). Open drain on NRST, so the MCU's own resets also drop
    # the relay. WDI has no pull on purpose: floating (MCU in reset, ROM DFU,
    # SWD reset-halt) disables the timer (SLVS165O 7.3.4), so the board can be
    # flashed; PB12's pull-down keeps the relay off in those states.
    wdt = part("WDT", ref="U6")
    wdt[1] += n.NRST
    wdt["GND"] += n.GND
    wdt[3] += n.P3V3        # MR unused: tie to VDD (pin table)
    wdt["WDI"] += n.WDT_KICK
    wdt[5] += n.P3V3
    c = part("C_100n")
    c[1] += n.P3V3
    c[2] += n.GND
