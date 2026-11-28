"""Power (SPEC.md "Power"): IGN -> PTC -> TVS -> reverse diode -> buck 5.3 V
-> diode-OR with USB VBUS -> LDO 3.3 V.

The buck sits at ~5.3 V, not 5.0, so that +5V_SYS after the OR diode stays
inside the TJA1042's 4.5-5.5 V VCC range; the relay coil (5 V, 150 % max, en-g6k.pdf
p.3) runs from +5V_IGN before the diode.
"""

from parts import nobom, part


def cap(key, net, gnd):
    c = part(key)
    c[1] += net
    c[2] += gnd


def build(n):
    f = part("F_PTC", ref="F1")
    f[1] += n.IGN
    f[2] += n.IGN_FUSED

    tvs = part("D_TVS33")  # after the PTC: reverse battery conducts it and trips the PTC
    tvs["K"] += n.IGN_FUSED
    tvs["A"] += n.GND

    rev = part("D_SS210")  # reverse-polarity series Schottky
    rev["A"] += n.IGN_FUSED
    rev["K"] += n.VIN_PROT

    # LMR16006Y buck (SNVSA24 fig. 9): Vout = 0.765 V * (1 + 28k / 4.7k) = 5.32 V
    # (VFB 0.747-0.782 V and 1 % resistors: 5.11-5.54 V; +5V_SYS is one Schottky drop lower)
    u = part("BUCK", ref="U7")
    u["VIN"] += n.VIN_PROT
    u["GND"] += n.GND
    u["SW"] += n.BUCK_SW
    u["CB"] += n.BUCK_CB
    u["FB"] += n.BUCK_FB
    u[4] += n.BUCK_SHDN
    r = part("R_100k")
    r[1] += n.VIN_PROT
    r[2] += n.BUCK_SHDN
    for key in ("C_2u2_50V", "C_2u2_50V", "C_100n_50V"):
        cap(key, n.VIN_PROT, n.GND)
    cb = part("C_100n_50V")
    cb[1] += n.BUCK_CB
    cb[2] += n.BUCK_SW
    catch = part("D_SS210")
    catch["K"] += n.BUCK_SW
    catch["A"] += n.GND
    ind = part("L_6u8", ref="L1")
    ind[1] += n.BUCK_SW
    ind[2] += n.P5V_IGN
    r1, r2 = part("R_28k"), part("R_4k7")
    r1[1] += n.P5V_IGN
    r1[2] += n.BUCK_FB
    r2[1] += n.BUCK_FB
    r2[2] += n.GND
    for key in ("C_22u", "C_22u", "C_100n"):
        cap(key, n.P5V_IGN, n.GND)

    # diode-OR: IGN-derived 5 V and USB VBUS feed the logic rail
    for src in (n.P5V_IGN, n.VBUS):
        d = part("D_B5819W")
        d["A"] += src
        d["K"] += n.P5V_SYS
    cap("C_4u7", n.P5V_SYS, n.GND)

    ldo = part("LDO", ref="U8")
    ldo["VI"] += n.P5V_SYS
    ldo["VO"] += n.P3V3
    ldo["GND"] += n.GND
    cap("C_1u", n.P5V_SYS, n.GND)
    cap("C_4u7", n.P3V3, n.GND)

    # power-good LED on the logic rail
    r = part("R_1k")
    r[1] += n.P3V3
    r[2] += n.PWR_LED_A
    led = part("LED_red", value="PWR")
    led["A"] += n.PWR_LED_A
    led["K"] += n.GND

    # ignition sense on PA1: 100k/22k (12 V -> 2.16 V, 3.3 V at 18.3 V), clamped to 3V3
    r1, r2 = part("R_100k"), part("R_22k")
    r1[1] += n.VIN_PROT
    r1[2] += n.IGN_SENSE
    r2[1] += n.IGN_SENSE
    r2[2] += n.GND
    cap("C_100n", n.IGN_SENSE, n.GND)
    clamp = part("D_1N4148W")
    clamp["A"] += n.IGN_SENSE
    clamp["K"] += n.P3V3

    # test pads by the buck (bare copper, no BOM line)
    for ref, name, net in (("TP7", "VIN", n.VIN_PROT), ("TP8", "5V_IGN", n.P5V_IGN),
                           ("TP9", "5V_SYS", n.P5V_SYS), ("TP10", "GND", n.GND)):
        tp = nobom("TP", name, ref=ref)
        tp[1] += net
