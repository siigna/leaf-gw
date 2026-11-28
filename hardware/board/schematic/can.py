"""Three CAN ports (SPEC.md "CAN"): TJA1042T/3, ESD array, split termination.

Port 1 = Chassis CAN ADAS side (MCU CAN1), port 2 = Chassis CAN car side
(CAN2), port 3 = V-CAN tap on the ADAS-side V-CAN pair (CAN3).

Ports 1 and 2 reach their termination through a relay's NO contacts
(relay.py: K1 for the ADAS side, K2 for the car side), so an unpowered board
adds no termination to the joined bus even with the jumpers closed. Port 3 is
a parallel tap and keeps its jumpers straight on the line.
"""

from skidl import Net

from parts import nobom, part


def port(n, i, can_h, can_l, txd, rxd, stb, term_h=None, term_l=None):
    u = part("CAN_XCVR", ref=f"U{i + 1}")  # U2..U4: transceivers 1..3
    u["TXD"] += txd
    u["RXD"] += rxd
    u["STB"] += stb  # high = standby; STB and TXD have internal pull-ups to VIO (datasheet 7.2.3)
    u["VCC"] += n.P5V_SYS
    u["VIO"] += n.P3V3
    u["GND"] += n.GND
    u["CANH"] += can_h
    u["CANL"] += can_l
    for rail in (n.P5V_SYS, n.P3V3):
        c = part("C_100n")
        c[1] += rail
        c[2] += n.GND

    # ESD array on the bus pair (pin 1/2 lines, pin 3 common anode to GND)
    esd = part("ESD_CAN", ref=f"D{20 + i}")
    esd[1] += can_h
    esd[2] += can_l
    esd[3] += n.GND

    # split termination: H -JP- 60.4 -mid- 60.4 -JP- L, mid -4.7n- GND; jumpers default open.
    # term_h/term_l: where the jumpers start (a relay's NO contacts), else the bus itself
    th, tl, mid = Net(f"TERM{i}_H"), Net(f"TERM{i}_L"), Net(f"TERM{i}_MID")
    jh = nobom("JP_open", f"TERM{i} H", ref=f"JP{2 * i - 1}")
    jl = nobom("JP_open", f"TERM{i} L", ref=f"JP{2 * i}")
    jh[1] += term_h or can_h
    jh[2] += th
    jl[1] += term_l or can_l
    jl[2] += tl
    rh, rl = part("R_60R4"), part("R_60R4")
    rh[1] += th
    rh[2] += mid
    rl[1] += mid
    rl[2] += tl
    c = part("C_4n7")
    c[1] += mid
    c[2] += n.GND


def build(n):
    port(n, 1, n.CAN1_ADAS_H, n.CAN1_ADAS_L, n.CAN1_TX, n.CAN1_RX, n.CAN1_STB, n.K1_NO_A, n.K1_NO_B)
    port(n, 2, n.CAN1_CAR_H, n.CAN1_CAR_L, n.CAN2_TX, n.CAN2_RX, n.CAN2_STB, n.K2_NO_A, n.K2_NO_B)
    port(n, 3, n.CAN2_H, n.CAN2_L, n.CAN3_TX, n.CAN3_RX, n.CAN3_STB)
