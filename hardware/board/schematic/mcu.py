"""STM32F413RGT6 (SPEC.md "MCU"), pins as the Ocelot gateway
(RetroPilot firmware/boards/gateway.h): CAN1 PB8/PB9, CAN2 PB5/PB6,
CAN3 PA8/PA15, standby PC1/PC13/PA0, IGN PA1, relay PB12. Our picks:
watchdog kick PC6, status LED PC7.
"""

from skidl import Net

from nets import nc
from parts import nobom, part

SIGNALS = {
    "PB8": "CAN1_RX", "PB9": "CAN1_TX",
    "PB5": "CAN2_RX", "PB6": "CAN2_TX",
    "PA8": "CAN3_RX", "PA15": "CAN3_TX",
    "PC1": "CAN1_STB", "PC13": "CAN2_STB", "PA0": "CAN3_STB",
    "PA1": "IGN_SENSE", "PB12": "RELAY_EN",
    "PC6": "WDT_KICK", "PC7": "LED_STATUS",
    "PA11": "USB_DM", "PA12": "USB_DP",
    "PA13": "SWDIO", "PA14": "SWCLK",
    "PH0": "HSE_IN", "PH1": "HSE_OUT",
    "PB2": "BOOT1",
}


def cap(key, net, gnd):
    c = part(key)
    c[1] += net
    c[2] += gnd


def build(n):
    u = part("MCU", ref="U1")
    for pin, net in SIGNALS.items():
        u[pin] += getattr(n, net)
    for pin in u.pins:
        if pin.name in ("VDD", "VBAT", "VDDA"):
            pin += n.P3V3
        elif pin.name in ("VSS", "VSSA"):
            pin += n.GND
    vcap = Net("VCAP_1")
    u["VCAP_1"] += vcap
    cap("C_4u7", vcap, n.GND)  # VCAP_1: 4.7 uF low-ESR (STM32F413 datasheet, VCAP_1 note)
    u["NRST"] += n.NRST
    u["BOOT0"] += n.BOOT0

    # decoupling: 100 nF per VDD pin (4) + VBAT + VDDA, bulk 4.7 uF, VDDA 1 uF
    for _ in range(6):
        cap("C_100n", n.P3V3, n.GND)
    cap("C_4u7", n.P3V3, n.GND)
    cap("C_1u", n.P3V3, n.GND)

    # HSE 8 MHz, CL 20 pF: 2 x (20 - ~5 pF stray) = 30 pF
    y = part("Y_8M", ref="Y1")
    y[1] += n.HSE_IN
    y[2] += n.HSE_OUT
    cap("C_30p", n.HSE_IN, n.GND)
    cap("C_30p", n.HSE_OUT, n.GND)

    # reset: 10k pull-up (the watchdog output is open drain), 100 nF
    r = part("R_10k")
    r[1] += n.P3V3
    r[2] += n.NRST
    cap("C_100n", n.NRST, n.GND)

    # boot: BOOT0 pulled down, button to 3V3 for ROM DFU; BOOT1 (PB2) low
    for net in (n.BOOT0, n.BOOT1):
        r = part("R_10k")
        r[1] += net
        r[2] += n.GND
    sw = part("SW_push", ref="SW1", value="DFU")
    sw[1] += n.P3V3
    sw[2] += n.BOOT0

    # status LED
    r = part("R_1k")
    r[1] += n.LED_STATUS
    r[2] += n.LED_STATUS_A
    led = part("LED_red", value="STATUS")
    led["A"] += n.LED_STATUS_A
    led["K"] += n.GND

    # SWD + boot test pads
    for name, net in (("SWDIO", n.SWDIO), ("SWCLK", n.SWCLK), ("NRST", n.NRST),
                      ("3V3", n.P3V3), ("GND", n.GND), ("BOOT0", n.BOOT0)):
        tp = nobom("TP", name)
        tp[1] += net

    used = set(SIGNALS)
    for pin in u.pins:
        if pin.name.startswith("P") and pin.name not in used:
            nc(pin, "spare GPIO")

