"""Board-wide nets, named as in SPEC.md, and the no-connect log."""

import builtins
from types import SimpleNamespace

from skidl import POWER, Net

NO_CONNECTS = []  # (ref, pin number, pin name, reason)


def nc(pin, reason):
    """Mark a pin unconnected on purpose; every one carries its reason."""
    assert reason, "a no-connect needs a reason"
    pin += builtins.NC  # SKiDL installs NC as a builtin
    NO_CONNECTS.append((pin.part.ref, pin.num, pin.name, reason))


def make():
    n = SimpleNamespace()
    names = [
        # 18-pin harness signals (SPEC.md "The 18-pin connector")
        "GND", "IGN", "CAN0_H", "CAN0_L", "CAN2_H", "CAN2_L",
        "CAN1_ADAS_H", "CAN1_ADAS_L", "CAN1_CAR_H", "CAN1_CAR_L",
        "BUS0_LOOP_3", "BUS0_LOOP_5", "BUS2_LOOP_13", "BUS2_LOOP_15",
        "VIN12_10", "VIN12_12",
        # power
        "IGN_FUSED", "VIN_PROT", "+5V_IGN", "+5V_SYS", "+3V3", "VBUS",
        "BUCK_SW", "BUCK_CB", "BUCK_FB", "BUCK_SHDN", "IGN_SENSE", "PWR_LED_A",
        # MCU
        "NRST", "BOOT0", "BOOT1", "HSE_IN", "HSE_OUT", "SWDIO", "SWCLK",
        "CAN1_RX", "CAN1_TX", "CAN2_RX", "CAN2_TX", "CAN3_RX", "CAN3_TX",
        "CAN1_STB", "CAN2_STB", "CAN3_STB", "WDT_KICK", "LED_STATUS", "LED_STATUS_A",
        # relay + gating
        "RELAY_EN", "RELAY_GATE", "RELAY_COIL_LO",
        # USB
        "USB_DP", "USB_DM", "USB_CC1", "USB_CC2",
    ]
    for name in names:
        setattr(n, name.replace("+", "P").replace("-", "_"), Net(name))
    # nets fed from outside (harness, USB) or through passives (inductor, diodes)
    for net in (n.GND, n.IGN, n.VBUS, n.VIN_PROT, n.P5V_IGN, n.P5V_SYS):
        net.drive = POWER
    return n
