"""Safety-net checks on the generated netlist (SPEC.md "Automated checks" 3).

The expectations here are written from SPEC.md and the part datasheets, not
imported from the schematic code, so a wrong schematic can't also bend the
check. Each check returns a list of failure strings; empty = pass.

    python3 safety.py leaf_gw.net
"""

import sys

from netlist import Netlist

# Datasheet pin numbers
TJA = {"TXD": "1", "GND": "2", "VCC": "3", "RXD": "4", "VIO": "5", "CANL": "6", "CANH": "7", "STB": "8"}  # NXP TJA1042 table 3
RELAY = {"COM_A": "11", "NC_A": "12", "NO_A": "14", "COM_B": "21", "NC_B": "22", "NO_B": "24", "COIL+": "A1", "COIL-": "A2"}  # KiCad numbering of Omron pins 3,2,4,6,7,5,1,8
AND = {"A": "1", "B": "2", "GND": "3", "Y": "4", "VCC": "5"}  # SN74LVC1G08 DBV
WDT = {"RESET": "1", "GND": "2", "MR": "3", "WDI": "4", "VDD": "5"}  # TPS3828 DBV
FET = {"G": "1", "S": "2", "D": "3"}  # AO3400A SOT-23
DIODE = {"K": "1", "A": "2"}  # KiCad Device:D*, footprint pad 1 = cathode

# STM32F413RG LQFP64 pin numbers (ST DS11581, table "STM32F413xG/H pin definition")
MCU = {"PC13": "2", "NRST": "7", "PC1": "9", "PA0": "14", "PA1": "15", "PB12": "33",
       "PC6": "37", "PA8": "41", "PA11": "44", "PA12": "45", "PA15": "50",
       "PB5": "57", "PB6": "58", "PB8": "61", "PB9": "62"}

PASS_ONLY = [3, 5, 13, 15, 4, 6, 10, 12]  # through, nothing else on board


def single(nl, prefix, fails, what):
    refs = nl.find(prefix)
    if len(refs) != 1:
        fails.append(f"expected one {what} ({prefix}*), found {refs}")
        return None
    return refs[0]


def unconnected(nl, ref, pin):
    return len(nl.nodes(ref, pin) - {(ref, pin)}) == 0


def conn_pins(nodes):
    return {(r, p) for r, p in nodes if r in ("J1", "J2")}


def check_passthrough(nl):
    """Every pass-through pin joins J1.n to J2.n and no other harness pin; the
    pure ones (loopbacks, V-CAN car side, 12VIN) touch nothing else at all."""
    f = []
    for ref in ("J1", "J2"):
        if ref not in nl.comps or not nl.comps[ref]["fields"].get("MPN", "").startswith("5016451820"):
            f.append(f"{ref} is not the Molex 501645-1820 header")
            return f
    for pin in PASS_ONLY:
        nodes = nl.nodes("J1", str(pin))
        if nodes != {("J1", str(pin)), ("J2", str(pin))}:
            f.append(f"pin {pin}: expected only J1.{pin}-J2.{pin}, got {sorted(nodes)}")
    groups = [(1, 17), (2, 14), (16,), (18,), (8,), (7,)]
    for g in groups:
        want = {(j, str(p)) for j in ("J1", "J2") for p in g}
        for j, p in want:
            got = conn_pins(nl.nodes(j, p))
            if got != want:
                f.append(f"pin {p} ({j}): harness pins on its net {sorted(got)}, expected {sorted(want)}")
    # IGN feeds the board through the fuse only
    for r, p in nl.nodes("J1", "2") - conn_pins(nl.nodes("J1", "2")):
        if not nl.comps[r]["footprint"].startswith("Fuse:"):
            f.append(f"IGN (pin 2/14) reaches {r}.{p} without the input fuse")
    return f


def check_box_side(nl):
    """Box-side 9/11 connect to nothing; cable-side 9/11 are not passed through."""
    f = []
    for pin in ("9", "11"):
        if not unconnected(nl, "J2", pin):
            f.append(f"J2.{pin} (box side CAN1 ADAS) is connected: {sorted(nl.nodes('J2', pin))}")
        if conn_pins(nl.nodes("J1", pin)) != {("J1", pin)}:
            f.append(f"J1.{pin} shares a net with other harness pins: {sorted(conn_pins(nl.nodes('J1', pin)))}")
    return f


def can_nets(nl):
    """The CAN pairs by role, found from the harness pins (SPEC.md table)."""
    return {
        "CAN1_ADAS": (nl.net_of("J1", "9"), nl.net_of("J1", "11")),
        "CAN1_CAR": (nl.net_of("J1", "8"), nl.net_of("J1", "7")),
        "VCAN_ADAS": (nl.net_of("J1", "16"), nl.net_of("J1", "18")),
    }


def check_relay(nl):
    """NC contacts join ADAS and car side, H to H on pole A, L to L on pole B;
    NO contacts open; COM on the ADAS side, NC on the car side."""
    f = []
    k = single(nl, "G6K-2F-Y", f, "fail-open relay")
    if not k:
        return f
    want = {
        "COM_A": ("J1", "9"), "NC_A": ("J1", "8"),
        "COM_B": ("J1", "11"), "NC_B": ("J1", "7"),
    }
    for contact, (j, p) in want.items():
        if nl.net_of(k, RELAY[contact]) is None or nl.net_of(k, RELAY[contact]) != nl.net_of(j, p):
            f.append(f"relay {contact} ({k}.{RELAY[contact]}) not on harness {j}.{p}")
    for contact in ("NO_A", "NO_B"):
        if not unconnected(nl, k, RELAY[contact]):
            f.append(f"relay {contact} ({k}.{RELAY[contact]}) is connected")
    if nl.net_of("J1", "9") == nl.net_of("J1", "8") or nl.net_of("J1", "11") == nl.net_of("J1", "7"):
        f.append("ADAS-side and car-side CAN1 are hard-wired together (bypasses the relay)")
    return f


def check_can_lines(nl):
    """Each CAN line holds exactly: its harness pins, one transceiver pin,
    one ESD line pin, one termination jumper, and the relay contact for CAN1;
    termination is jumper -> 60.4R -> mid -> 60.4R -> jumper, mid -> 4.7nF -> GND,
    jumper default open. Nothing else, so no other path to power or ground."""
    f = []
    k = (nl.find("G6K-2F-Y") or [None])[0]
    relay_pins = {"CAN1_ADAS": ("COM_A", "COM_B"), "CAN1_CAR": ("NC_A", "NC_B")}
    harness = {"CAN1_ADAS": (("9",), ("11",)), "CAN1_CAR": (("8",), ("7",)), "VCAN_ADAS": (("16",), ("18",))}
    gnd = nl.net_of("J1", "1")
    for role, (h, l) in can_nets(nl).items():
        if h is None or l is None or h == l:
            f.append(f"{role}: H/L nets missing or shorted")
            continue
        xcvr, esd, mids = set(), set(), []
        for side, net in (("H", h), ("L", l)):
            idx = 0 if side == "H" else 1
            want_conn = {("J1", p) for p in harness[role][idx]}
            if role != "CAN1_ADAS":
                want_conn |= {("J2", p) for p in harness[role][idx]}
            seen_x = seen_e = seen_j = 0
            for r, p in nl.nets[net]:
                fp = nl.comps[r]["footprint"]
                mpn = nl.comps[r]["fields"].get("MPN", "")
                if (r, p) in want_conn:
                    continue
                if r == k and role in relay_pins and p == RELAY[relay_pins[role][idx]]:
                    continue
                if mpn.startswith("TJA1042") and p == TJA["CANH" if side == "H" else "CANL"]:
                    xcvr.add(r)
                    seen_x += 1
                elif mpn.startswith("PESD2CAN") and p == ("1" if side == "H" else "2"):
                    esd.add(r)
                    seen_e += 1
                elif fp.startswith("Jumper:") and p in ("1", "2"):
                    seen_j += 1
                    mid = termination_leg(nl, r, p, net, gnd, f, f"{role}_{side}")
                    mids.append(mid)
                else:
                    f.append(f"{role}_{side} ({net}): unexpected {r}.{p} ({mpn or fp})")
            if conn_pins(nl.nets[net]) != want_conn:
                f.append(f"{role}_{side}: harness pins {sorted(conn_pins(nl.nets[net]))}, expected {sorted(want_conn)}")
            if (seen_x, seen_e, seen_j) != (1, 1, 1):
                f.append(f"{role}_{side}: {seen_x} transceiver, {seen_e} ESD, {seen_j} termination jumper pins (want 1 each)")
        if len(xcvr) != 1 or len(esd) != 1:
            f.append(f"{role}: H and L go to different transceivers {sorted(xcvr)} / ESD parts {sorted(esd)}")
        if len(mids) == 2 and (mids[0] is None or mids[0] != mids[1]):
            f.append(f"{role}: H and L termination legs don't meet at one split midpoint")
    if k:
        for contact in ("COM_A", "NC_A", "COM_B", "NC_B"):
            net = nl.net_of(k, RELAY[contact])
            if net not in {n for pair in can_nets(nl).values() for n in pair}:
                f.append(f"relay {contact} on non-CAN net {net}")
    return f


def other_pin(nl, ref, pin):
    pins = nl.pins_of(ref)
    others = [p for p in pins if p != pin]
    return (others[0], pins[others[0]]) if len(others) == 1 and len(pins) == 2 else (None, None)


def termination_leg(nl, jp, pin, can_net, gnd, f, label):
    """jumper -> resistor -> midpoint; returns the midpoint net (or None)."""
    if "Open" not in nl.comps[jp]["footprint"]:
        f.append(f"{label}: termination jumper {jp} is not a default-open solder jumper")
    _, sw = other_pin(nl, jp, pin)
    if sw is None:
        f.append(f"{label}: jumper {jp} is not a two-pin series element")
        return None
    rest = nl.nets[sw] - {(jp, "1"), (jp, "2")}
    if len(rest) != 1:
        f.append(f"{label}: jumper {jp} far side has {sorted(rest)}, want one resistor")
        return None
    (r, rp), = rest
    if not nl.comps[r]["footprint"].startswith("Resistor_SMD:") or nl.comps[r]["value"] != "60.4":
        f.append(f"{label}: termination element {r} is not a 60.4 ohm resistor")
    _, mid = other_pin(nl, r, rp)
    if mid is None:
        return None
    caps = [(x, xp) for x, xp in nl.nets[mid] if nl.comps[x]["footprint"].startswith("Capacitor_SMD:")]
    resistors = [x for x, _ in nl.nets[mid] if nl.comps[x]["footprint"].startswith("Resistor_SMD:")]
    if len(nl.nets[mid]) != 3 or len(caps) != 1 or len(resistors) != 2:
        f.append(f"{label}: split midpoint {mid} holds {sorted(nl.nets[mid])}, want 2 resistors + 1 cap")
        return None
    c, cp = caps[0]
    if other_pin(nl, c, cp)[1] != gnd or nl.comps[c]["value"] != "4.7nF 50V":
        f.append(f"{label}: split cap {c} is not 4.7 nF to GND")
    return mid


def check_coil_driver(nl):
    """Coil+ on the IGN-derived 5 V, coil- on the low-side FET drain with a
    flyback diode; the FET gate is driven only by the AND of PB12 and the
    watchdog RESET, with a pull-down; PB12 has a pull-down; the watchdog
    RESET is open drain and is also the MCU's NRST."""
    f = []
    k = single(nl, "G6K-2F-Y", f, "relay")
    q = single(nl, "AO3400A", f, "coil FET")
    g = single(nl, "SN74LVC1G08", f, "AND gate")
    w = single(nl, "TPS3828-33", f, "open-drain watchdog")
    u = single(nl, "STM32F413", f, "MCU")
    if None in (k, q, g, w, u):
        return f
    gnd, v33 = nl.net_of("J1", "1"), nl.net_of(u, "19")
    plus, minus = nl.net_of(k, RELAY["COIL+"]), nl.net_of(k, RELAY["COIL-"])
    diodes = {r for r, c in nl.comps.items() if c["footprint"].startswith("Diode_SMD:")}
    fly = [r for r in diodes if nl.net_of(r, DIODE["K"]) == plus and nl.net_of(r, DIODE["A"]) == minus]
    if not fly:
        f.append("relay coil has no flyback diode (K on coil+, A on coil-)")
    if minus is None or nl.nets[minus] - {(k, RELAY["COIL-"]), (q, FET["D"])} - {(d, DIODE["A"]) for d in fly}:
        f.append(f"coil- net holds more than coil, FET drain and flyback diode: {sorted(nl.nets.get(minus, []))}")
    if nl.net_of(q, FET["D"]) != minus or nl.net_of(q, FET["S"]) != gnd:
        f.append("coil FET is not low-side (drain on coil-, source on GND)")

    gate = nl.net_of(q, FET["G"])
    pulldowns = [r for r, p in nl.nets.get(gate, ()) if nl.comps[r]["footprint"].startswith("Resistor_SMD:")
                 and other_pin(nl, r, p)[1] == gnd]
    if gate is None or nl.nets[gate] - {(q, FET["G"]), (g, AND["Y"])} - {(r, p) for r, p in nl.nets[gate] if r in pulldowns}:
        f.append(f"FET gate net driven by more than the AND output and its pull-down: {sorted(nl.nets.get(gate, []))}")
    if (g, AND["Y"]) not in nl.nets.get(gate, ()):
        f.append("FET gate is not driven by the AND gate output")
    if len(pulldowns) != 1:
        f.append(f"FET gate has {len(pulldowns)} pull-downs to GND (want 1)")
    if nl.net_of(g, AND["VCC"]) != v33 or nl.net_of(g, AND["GND"]) != gnd:
        f.append("AND gate not powered from 3V3/GND")

    en = nl.net_of(g, AND["A"])
    en_pd = [r for r, p in nl.nets.get(en, ()) if nl.comps[r]["footprint"].startswith("Resistor_SMD:")
             and other_pin(nl, r, p)[1] == gnd]
    if en is None or (u, MCU["PB12"]) not in nl.nets[en] or len(en_pd) != 1 or \
            nl.nets[en] - {(g, AND["A"]), (u, MCU["PB12"])} - {(r, p) for r, p in nl.nets[en] if r in en_pd}:
        f.append(f"AND input A must be PB12 with one pull-down and nothing else: {sorted(nl.nets.get(en, []))}")

    rst = nl.net_of(g, AND["B"])
    if rst is None or nl.net_of(w, WDT["RESET"]) != rst:
        f.append("AND input B is not the watchdog RESET output")
    if nl.net_of(u, MCU["NRST"]) != rst:
        f.append("watchdog RESET does not reset the MCU (not on NRST)")
    kick = nl.net_of(w, WDT["WDI"])
    if kick is None or nl.nets[kick] != {(w, WDT["WDI"]), (u, MCU["PC6"])}:
        f.append(f"watchdog WDI must be driven by the MCU kick pin only: {sorted(nl.nets.get(kick, []))}")
    if nl.net_of(w, WDT["VDD"]) != v33 or nl.net_of(w, WDT["GND"]) != gnd:
        f.append("watchdog not powered from 3V3/GND")
    return f


def reach(nl, start):
    """Nets DC-reachable from `start` through resistors, inductors, fuses,
    jumpers, and diodes in their forward direction only."""
    seen, todo = {start}, [start]
    while todo:
        net = todo.pop()
        for r, p in nl.nets[net]:
            fp = nl.comps[r]["footprint"]
            if fp.startswith("Diode_SMD:"):
                if p != DIODE["A"]:
                    continue
            elif not fp.split(":")[0] in ("Resistor_SMD", "Inductor_SMD", "Fuse", "Jumper"):
                continue
            _, other = other_pin(nl, r, p)
            if other and other not in seen:
                seen.add(other)
                todo.append(other)
    return seen


def check_usb_isolation(nl):
    """USB VBUS can't power the relay coil: a board on USB alone stays in
    passthrough (SPEC.md "USB")."""
    f = []
    k = single(nl, "G6K-2F-Y", f, "relay")
    usb = single(nl, "TYPE-C-31-M-12", f, "USB-C receptacle")
    if not (k and usb):
        return f
    vbus = nl.net_of(usb, "A4")
    if nl.net_of(k, RELAY["COIL+"]) in reach(nl, vbus):
        f.append("relay coil supply is reachable from USB VBUS")
    if nl.net_of(k, RELAY["COIL+"]) not in reach(nl, nl.net_of("J1", "2")):
        f.append("relay coil supply is not derived from IGN")
    return f


def check_mcu_pins(nl):
    """MCU pins match SPEC.md's table (= the Ocelot gateway), by LQFP64 pin number."""
    f = []
    u = single(nl, "STM32F413", f, "MCU")
    if not u:
        return f
    xcvrs = {}
    for role, (h, _) in can_nets(nl).items():
        for r, p in nl.nets.get(h, ()):
            if nl.comps[r]["fields"].get("MPN", "").startswith("TJA1042") and p == TJA["CANH"]:
                xcvrs[role] = r
    if len(xcvrs) != 3:
        f.append(f"could not find one transceiver per CAN role: {xcvrs}")
        return f
    want = {
        "PB8": (xcvrs["CAN1_ADAS"], "RXD"), "PB9": (xcvrs["CAN1_ADAS"], "TXD"), "PC1": (xcvrs["CAN1_ADAS"], "STB"),
        "PB5": (xcvrs["CAN1_CAR"], "RXD"), "PB6": (xcvrs["CAN1_CAR"], "TXD"), "PC13": (xcvrs["CAN1_CAR"], "STB"),
        "PA8": (xcvrs["VCAN_ADAS"], "RXD"), "PA15": (xcvrs["VCAN_ADAS"], "TXD"), "PA0": (xcvrs["VCAN_ADAS"], "STB"),
    }
    for name, (x, fn) in want.items():
        net = nl.net_of(u, MCU[name])
        if net is None or (x, TJA[fn]) not in nl.nets[net]:
            f.append(f"{name} (pin {MCU[name]}) is not {x} {fn}")
    usb = (nl.find("TYPE-C-31-M-12") or [None])[0]
    for name, pins in (("PA11", ("A7", "B7")), ("PA12", ("A6", "B6"))):
        net = nl.net_of(u, MCU[name])
        if net is None or not {(usb, p) for p in pins} <= nl.nets[net]:
            f.append(f"{name} (pin {MCU[name]}) is not USB {'D-' if name == 'PA11' else 'D+'}")
    # PA1: ignition sense, a resistor from the IGN-derived side
    ign = reach(nl, nl.net_of("J1", "2")) - {nl.net_of("J1", "1")}
    sense = nl.net_of(u, MCU["PA1"])
    if not sense or not any(nl.comps[r]["footprint"].startswith("Resistor_SMD:") and other_pin(nl, r, p)[1] in ign
                            and other_pin(nl, r, p)[1] != sense for r, p in nl.nets[sense]):
        f.append("PA1 (pin 15) is not the IGN divider")
    # no two signal pins of the table share a net
    nets = {}
    for name, pin in MCU.items():
        net = nl.net_of(u, pin)
        if net and net in nets:
            f.append(f"{name} and {nets[net]} share net {net}")
        nets[net] = name
    return f


CHECKS = [check_passthrough, check_box_side, check_relay, check_can_lines,
          check_coil_driver, check_usb_isolation, check_mcu_pins]


def run(nl):
    return {c.__name__: c(nl) for c in CHECKS}


def main(path):
    nl = Netlist.load(path)
    bad = 0
    for name, fails in run(nl).items():
        print(("FAIL " if fails else "ok   ") + name)
        for msg in fails:
            print("     " + msg)
        bad += bool(fails)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
