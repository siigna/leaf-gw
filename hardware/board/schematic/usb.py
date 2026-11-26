"""USB-C, USB 2.0 only (SPEC.md "USB"): 5.1k CC pull-downs (sink), ESD on D+/D-.
VBUS joins +5V_SYS through the diode-OR in power.py."""

from nets import nc
from parts import part


def build(n):
    j = part("USB_C", ref="J3")
    for pin in ("A4", "A9", "B4", "B9"):
        j[pin] += n.VBUS
    for pin in ("A1", "A12", "B1", "B12", "SH"):
        j[pin] += n.GND
    j["A6"] += n.USB_DP
    j["B6"] += n.USB_DP
    j["A7"] += n.USB_DM
    j["B7"] += n.USB_DM
    j["A5"] += n.USB_CC1
    j["B5"] += n.USB_CC2
    nc(j["A8"], "SBU unused (USB 2.0 only)")
    nc(j["B8"], "SBU unused (USB 2.0 only)")
    for cc in (n.USB_CC1, n.USB_CC2):
        r = part("R_5k1")
        r[1] += cc
        r[2] += n.GND

    esd = part("ESD_USB", ref="U9")
    esd[1] += n.USB_DP
    esd[6] += n.USB_DP
    esd[3] += n.USB_DM
    esd[4] += n.USB_DM
    esd[2] += n.GND
    esd[5] += n.VBUS
