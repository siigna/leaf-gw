"""Microstrip impedance for the JLC04161H-7628 stack-up (L1 over L2 GND).

Single line: Hammerstad & Jensen (1980, "Accurate models for microstrip
computer-aided design"), with their finite-thickness width correction.
Coupled pair: Garg & Bahl (1979, "Characteristics of coupled microstriplines",
IEEE MTT-27) even/odd-mode capacitances. Static (no dispersion: CAN at 500 kbit/s
and USB full speed are far below where it matters), no solder mask (mask lowers
the impedance a few percent; JLC's own calculator is the cross-check).

    python3 impedance.py        # prints the chosen geometries and self-checks
"""

import math

E0 = 8.854187817e-12
C0 = 299792458.0
ETA0 = 376.730313

# JLC04161H-7628 (jlcpcb.com/impedance, checked 2026-11-26): L1 1 oz outer
# 0.035 mm, 7628 prepreg 0.2104 mm, er 4.4, then L2 (0.0152 mm inner copper).
H = 0.2104
T = 0.035
ER = 4.4


def _z0_air(u):
    f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
    return ETA0 / (2 * math.pi) * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))


def _er_eff(u, er):
    a = 1 + math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)


def microstrip(w, h=H, t=T, er=ER):
    """(Z0, eps_eff) of a single microstrip, Hammerstad-Jensen with thickness."""
    u = w / h
    if t > 0:
        du1 = t / h / math.pi * math.log(1 + 4 * math.e / (t / h * (1 / math.tanh(math.sqrt(6.517 * u))) ** 2))
        dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
        u1, ur = u + du1, u + dur
    else:
        u1 = ur = u
    z_air1, z_airr = _z0_air(u1), _z0_air(ur)
    ee = _er_eff(ur, er) * (z_air1 / z_airr) ** 2
    return z_airr / math.sqrt(_er_eff(ur, er)), ee


def _cap_k(k):
    """K(k')/K(k) (Hilberg's approximation), for the odd-mode air gap capacitance."""
    kp = math.sqrt(1 - k * k)
    if k * k <= 0.5:
        return math.log(2 * (1 + math.sqrt(kp)) / (1 - math.sqrt(kp))) / math.pi
    return math.pi / math.log(2 * (1 + math.sqrt(k)) / (1 - math.sqrt(k)))


def _caps(w, s, h, t, er):
    z0, ee = microstrip(w, h, t, er)
    cp = E0 * er * w / h
    cf = 0.5 * (math.sqrt(ee) / (C0 * z0) - cp)
    a = math.exp(-0.1 * math.exp(2.33 - 2.53 * w / h))
    cf2 = cf / (1 + a * (h / s) * math.tanh(8 * s / h)) * math.sqrt(er / ee)
    k = (s / h) / (s / h + 2 * w / h)
    cga = E0 * _cap_k(k)  # K(k')/K(k)
    cgd = E0 * er / math.pi * math.log(1 / math.tanh(math.pi * s / (4 * h))) + 0.65 * cf * (0.02 * math.sqrt(er) / (s / h) + 1 - er ** -2)
    return cp + cf + cf2, cp + cf + cga + cgd


def coupled(w, s, h=H, t=T, er=ER):
    """(Zdiff, Zodd, Zeven) of an edge-coupled microstrip pair, Garg-Bahl."""
    ce, co = _caps(w, s, h, t, er)
    ce1, co1 = _caps(w, s, h, t, 1.0)
    ze = 1 / (C0 * math.sqrt(ce * ce1))
    zo = 1 / (C0 * math.sqrt(co * co1))
    return 2 * zo, zo, ze


def ipc2141(w, s, h=H, t=T, er=ER):
    """IPC-2141A closed form, the coarse cross-check."""
    z0 = 87 / math.sqrt(er + 1.41) * math.log(5.98 * h / (0.8 * w + t))
    return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))


# The geometries the layout uses (mm), from coupled(); the self-check below
# holds them within 3 % of target. Gap 0.2 mm rather than JLC's 0.127 mm
# minimum, so the gap's etch tolerance moves the impedance less.
CAN = {"w": 0.19, "s": 0.20, "target": 120}
USB = {"w": 0.35, "s": 0.20, "target": 90}


def table():
    rows = []
    for name, g in (("CAN", CAN), ("USB", USB)):
        zd, zo, ze = coupled(g["w"], g["s"])
        rows.append((name, g["target"], g["w"], g["s"], zd, ze, ipc2141(g["w"], g["s"])))
    return rows


if __name__ == "__main__":
    # sanity: the single-line model puts 50 ohm at ~0.36 mm on 0.21 mm of 7628,
    # the usual figure for this stack-up; confirm in JLC's calculator before ordering
    z50 = microstrip(0.36)[0]
    assert 49 < z50 < 52, z50
    for name, tgt, w, s, zd, ze, zipc in table():
        print(f"{name}: w {w} mm, gap {s} mm -> Zdiff {zd:.1f} ohm (target {tgt}), Zeven {ze:.1f}, IPC-2141A {zipc:.1f}")
        assert abs(zd - tgt) / tgt < 0.03, (name, zd)
        assert w >= 0.127 and s >= 0.127
    print(f"single 0.36 mm: {z50:.1f} ohm")
