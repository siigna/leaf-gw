"""The two 18-pin harness connectors (SPEC.md "The 18-pin connector").

J1 takes comma's car-harness cable (Molex 501646-1800 receptacle); J2 goes to
the stock harness box over a 1:1 18-way 501646-1800 jumper cable (README).
Pin numbers are Molex's, as on comma's open_pinout.pdf.
"""

from nets import nc
from parts import part


def build(n):
    j1 = part("HDR18", ref="J1", value="harness cable")
    j2 = part("HDR18", ref="J2", value="harness box")

    # pass-through: same net on both sides
    through = {
        1: n.GND, 17: n.GND,          # board ground
        2: n.IGN, 14: n.IGN,          # board power input
        3: n.BUS0_LOOP_3, 5: n.BUS0_LOOP_5,      # box's bus-0 termination loopback
        13: n.BUS2_LOOP_13, 15: n.BUS2_LOOP_15,  # bus-2 loopback
        4: n.CAN0_H, 6: n.CAN0_L,     # V-CAN car side
        16: n.CAN2_H, 18: n.CAN2_L,   # V-CAN ADAS side, tapped by transceiver 3
        8: n.CAN1_CAR_H, 7: n.CAN1_CAR_L,  # Chassis CAN car side, also to the box
        10: n.VIN12_10, 12: n.VIN12_12,    # 12VIN, not wired on Nissan A
    }
    for pin, net in through.items():
        net += j1[pin], j2[pin]

    # Chassis CAN ADAS side ends on this board (transceiver 1 + relay common)
    n.CAN1_ADAS_H += j1[9]
    n.CAN1_ADAS_L += j1[11]
    reason = "box side CAN1 ADAS pair: joining it would short around the gateway (SPEC.md)"
    nc(j2[9], reason)
    nc(j2[11], reason)
    return j1, j2
