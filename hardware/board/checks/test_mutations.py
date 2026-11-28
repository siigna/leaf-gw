"""Prove the checks bite: each mutation of the real netlist must make its
check fail, and the unmutated netlist must pass everything.

    python3 test_mutations.py [leaf_gw.net bom_jlcpcb.csv]
"""

import os
import sys
import unittest

import bom
import safety
from netlist import Netlist

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "..", "out", "leaf_gw.net")
BOM = os.path.join(HERE, "..", "out", "bom_jlcpcb.csv")


def ref(nl, mpn):
    return nl.find(mpn)[0]


def pulldown(nl, net):
    gnd = nl.net_of("J1", "1")
    return next(r for r, p in nl.nets[net] if nl.comps[r]["footprint"].startswith("Resistor_SMD:")
                and safety.other_pin(nl, r, p)[1] == gnd)


class Mutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Netlist.load(NET)
        cls.rows = bom.read_bom(BOM)

    def bites(self, check, mutate):
        nl = self.base.copy()
        mutate(nl)
        self.assertTrue(check(nl), f"{check.__name__} did not catch the mutation")

    def test_baseline_passes(self):
        for name, fails in safety.run(self.base).items():
            self.assertEqual(fails, [], name)
        self.assertEqual(bom.check_bom(self.base, self.rows), [])
        self.assertEqual(bom.check_footprints(self.base), [])

    # pass-through
    def test_passthrough_broken(self):
        self.bites(safety.check_passthrough, lambda nl: nl.move("J2", "4", "CUT"))

    def test_loopbacks_joined_on_board(self):
        self.bites(safety.check_passthrough, lambda nl: nl.move("J1", "5", nl.net_of("J1", "3")))

    def test_passthrough_tapped(self):
        self.bites(safety.check_passthrough, lambda nl: nl.move(ref(nl, "TJA1042"), "7", nl.net_of("J1", "4")))

    def test_ign_bypasses_fuse(self):
        self.bites(safety.check_passthrough, lambda nl: nl.move(ref(nl, "LMR16006"), "5", nl.net_of("J1", "2")))

    # box side 9/11
    def test_box_9_connected(self):
        self.bites(safety.check_box_side, lambda nl: nl.move("J2", "9", nl.net_of("J1", "9")))

    def test_box_11_connected(self):
        self.bites(safety.check_box_side, lambda nl: nl.move("J2", "11", nl.net_of("J1", "11")))

    # relay contacts
    def test_relay_nc_no_swapped(self):
        def m(nl):
            k = ref(nl, "G6K")
            car = nl.net_of(k, "12")
            nl.move(k, "12", None)
            nl.move(k, "14", car)
        self.bites(safety.check_relay, m)

    def test_relay_poles_crossed(self):
        def m(nl):
            k = ref(nl, "G6K")
            h, l = nl.net_of(k, "12"), nl.net_of(k, "22")
            nl.move(k, "12", l)
            nl.move(k, "22", h)
        self.bites(safety.check_relay, m)

    def test_relay_com_nc_swapped(self):
        def m(nl):
            k = ref(nl, "G6K")
            com, nc = nl.net_of(k, "11"), nl.net_of(k, "12")
            nl.move(k, "11", nc)
            nl.move(k, "12", com)
        self.bites(safety.check_relay, m)

    def test_can1_halves_hardwired(self):
        self.bites(safety.check_relay, lambda nl: nl.move("J1", "9", nl.net_of("J1", "8")))

    # CAN lines and termination
    def test_can_line_resistor_to_gnd(self):
        self.bites(safety.check_can_lines, lambda nl: nl.add_part(
            "R99", "Resistor_SMD:R_0603_1608Metric", "X", {"1": nl.net_of("J1", "8"), "2": nl.net_of("J1", "1")}))

    def test_can_line_to_power(self):
        self.bites(safety.check_can_lines, lambda nl: nl.add_part(
            "R99", "Resistor_SMD:R_0603_1608Metric", "X", {"1": nl.net_of("J1", "16"), "2": "+5V_SYS"}))

    def test_termination_jumper_closed(self):
        def m(nl):
            jp = next(r for r, _ in nl.nodes("J1", "16") if nl.comps[r]["footprint"].startswith("Jumper:"))
            nl.comps[jp]["footprint"] = "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm"
        self.bites(safety.check_can_lines, m)

    def test_switched_termination_jumper_closed(self):
        def m(nl):
            jp = next(r for r, _ in nl.nets["K1_NO_A"] if nl.comps[r]["footprint"].startswith("Jumper:"))
            nl.comps[jp]["footprint"] = "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm"
        self.bites(safety.check_relay, m)

    def test_termination_cap_to_power(self):
        def m(nl):
            c = next(r for r, _ in nl.nets["TERM3_MID"] if r.startswith("C"))
            nl.move(c, "2", "+3V3")
        self.bites(safety.check_can_lines, m)

    def test_switched_termination_cap_to_power(self):
        def m(nl):
            c = next(r for r, _ in nl.nets["TERM2_MID"] if r.startswith("C"))
            nl.move(c, "2", "+3V3")
        self.bites(safety.check_relay, m)

    def test_termination_missing_jumper(self):
        def m(nl):
            jp = next(r for r, _ in nl.nets["K2_NO_B"] if nl.comps[r]["footprint"].startswith("Jumper:"))
            nl.move(jp, "1", None)
            nl.move(jp, "2", None)
            nl.move(next(r for r, _ in nl.nets["TERM2_L"] if r.startswith("R")), "2", "K2_NO_B")
        self.bites(safety.check_relay, m)

    # fail-safe termination: relay-switched, nothing on the bus when de-energized
    def test_adas_termination_unswitched(self):
        def m(nl):
            jp = next(r for r, p in nl.nets["K1_NO_A"] if r.startswith("JP"))
            nl.move(jp, "1", nl.net_of("J1", "9"))
        self.bites(safety.check_failsafe_termination, m)
        self.bites(safety.check_can_lines, m)

    def test_car_termination_unswitched(self):
        def m(nl):
            jp = next(r for r, p in nl.nets["K2_NO_B"] if r.startswith("JP"))
            nl.move(jp, "1", nl.net_of("J1", "7"))
        self.bites(safety.check_failsafe_termination, m)

    def test_adas_termination_on_k1_nc(self):
        def m(nl):  # K1 pole A NC and NO swapped: termination on the bus when unpowered
            nc, no = nl.net_of("K1", "12"), nl.net_of("K1", "14")
            nl.move("K1", "12", no)
            nl.move("K1", "14", nc)
        self.bites(safety.check_failsafe_termination, m)

    def test_car_termination_on_k2_nc(self):
        def m(nl):
            no = nl.net_of("K2", "24")
            nl.move("K2", "24", None)
            nl.move("K2", "22", no)
        self.bites(safety.check_failsafe_termination, m)
        self.bites(safety.check_relay, m)

    def test_car_termination_not_switched_in(self):
        self.bites(safety.check_failsafe_termination, lambda nl: nl.move("K2", "14", None))

    def test_k1_no_extra_load(self):
        self.bites(safety.check_relay, lambda nl: nl.add_part(
            "R99", "Resistor_SMD:R_0603_1608Metric", "X", {"1": "K1_NO_A", "2": nl.net_of("J1", "1")}))

    def test_termination_relay_missing(self):
        def m(nl):
            for p in list(nl.pins_of("K2")):
                nl.move("K2", p, None)
            del nl.comps["K2"]
        self.bites(safety.check_relay, m)

    def test_k2_coil_not_parallel(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move("K2", "A2", "K2_COIL_LO"))

    def test_k2_coil_on_usb_rail(self):
        self.bites(safety.check_usb_isolation, lambda nl: nl.move("K2", "A1", "+5V_SYS"))

    def test_transceiver_on_wrong_pair(self):
        def m(nl):
            x = next(r for r, p in nl.nodes("J1", "8") if p == "7" and r.startswith("U"))
            nl.move(x, "7", nl.net_of("J1", "16"))
        self.bites(safety.check_can_lines, m)

    def test_esd_missing(self):
        self.bites(safety.check_can_lines, lambda nl: nl.move(ref(nl, "PESD2CAN"), "1", None))

    # coil driver
    def test_gate_pulldown_dropped(self):
        def m(nl):
            gate = nl.net_of(ref(nl, "AO3400A"), "1")
            nl.move(pulldown(nl, gate), "1", None)
        self.bites(safety.check_coil_driver, m)

    def test_gate_driven_by_pb12_directly(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move(ref(nl, "AO3400A"), "1", nl.net_of("U1", "33")))

    def test_gate_driven_by_watchdog_only(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move(ref(nl, "AO3400A"), "1", nl.net_of("U1", "7")))

    def test_and_input_from_other_pin(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move("U1", "33", None) or nl.move("U1", "34", nl.net_of(ref(nl, "SN74LVC1G08"), "1")))

    def test_pb12_pulldown_dropped(self):
        def m(nl):
            en = nl.net_of(ref(nl, "SN74LVC1G08"), "1")
            nl.move(pulldown(nl, en), "1", None)
        self.bites(safety.check_coil_driver, m)

    def test_watchdog_not_resetting_mcu(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move("U1", "7", "NRST_ALONE"))

    def test_watchdog_not_gating(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.move(ref(nl, "SN74LVC1G08"), "2", "+3V3"))

    def test_watchdog_push_pull(self):
        def m(nl):
            w = ref(nl, "TPS3828")
            nl.comps[w]["fields"]["MPN"] = "TPS3823-33DBVR"
        self.bites(safety.check_coil_driver, m)

    def test_watchdog_kick_pulled(self):
        self.bites(safety.check_coil_driver, lambda nl: nl.add_part(
            "R99", "Resistor_SMD:R_0603_1608Metric", "X", {"1": nl.net_of(ref(nl, "TPS3828"), "4"), "2": nl.net_of("J1", "1")}))

    def test_no_flyback(self):
        def m(nl):
            k = ref(nl, "G6K")
            d = next(r for r, p in nl.nodes(k, "A2") if r.startswith("D"))
            nl.move(d, "2", None)
        self.bites(safety.check_coil_driver, m)

    def test_high_side_fet(self):
        def m(nl):
            q = ref(nl, "AO3400A")
            nl.move(q, "2", "+5V_IGN")
        self.bites(safety.check_coil_driver, m)

    # USB isolation
    def test_coil_on_usb_rail(self):
        self.bites(safety.check_usb_isolation, lambda nl: nl.move(ref(nl, "G6K"), "A1", "+5V_SYS"))

    def test_or_diode_reversed(self):
        def m(nl):
            d = next(r for r, p in nl.nets["+5V_IGN"] if p == "2" and nl.comps[r]["fields"].get("MPN", "").startswith("B5819W"))
            nl.move(d, "2", "+5V_SYS")
            nl.move(d, "1", "+5V_IGN")
        self.bites(safety.check_usb_isolation, m)

    # MCU pins
    def test_can1_on_wrong_pins(self):
        def m(nl):
            a, b = nl.net_of("U1", "61"), nl.net_of("U1", "62")
            c, d = nl.net_of("U1", "57"), nl.net_of("U1", "58")
            nl.move("U1", "61", c)
            nl.move("U1", "62", d)
            nl.move("U1", "57", a)
            nl.move("U1", "58", b)
        self.bites(safety.check_mcu_pins, m)

    def test_can_rx_tx_swapped(self):
        def m(nl):
            a, b = nl.net_of("U1", "41"), nl.net_of("U1", "50")
            nl.move("U1", "41", b)
            nl.move("U1", "50", a)
        self.bites(safety.check_mcu_pins, m)

    def test_standby_on_wrong_pin(self):
        self.bites(safety.check_mcu_pins, lambda nl: nl.move("U1", "2", None) or nl.move("U1", "3", "CAN2_STB"))

    def test_usb_swapped(self):
        def m(nl):
            a, b = nl.net_of("U1", "44"), nl.net_of("U1", "45")
            nl.move("U1", "44", b)
            nl.move("U1", "45", a)
        self.bites(safety.check_mcu_pins, m)

    def test_ign_sense_missing(self):
        self.bites(safety.check_mcu_pins, lambda nl: nl.move("U1", "15", None))

    # BOM and footprints
    def test_bom_missing_lcsc(self):
        nl = self.base.copy()
        nl.comps["U1"]["fields"]["LCSC"] = ""
        self.assertTrue(bom.check_bom(nl, self.rows))

    def test_bom_duplicate_designator(self):
        nl = self.base.copy()
        nl.refs.append("R1")
        self.assertTrue(bom.check_bom(nl, self.rows))

    def test_bom_csv_duplicate_designator(self):
        rows = [list(r) for r in self.rows]
        rows[1][1] += ",R1"
        self.assertTrue(bom.check_bom(self.base, rows))

    def test_bom_csv_missing_line(self):
        self.assertTrue(bom.check_bom(self.base, self.rows[:-1]))

    def test_unassembled_part_without_reason(self):
        nl = self.base.copy()
        nl.comps["K1"]["fields"].pop("LCSC")
        nl.comps["K1"]["fields"]["no_bom"] = "lazy"
        self.assertTrue(bom.check_bom(nl, self.rows))

    def test_footprint_pad_mismatch(self):
        nl = self.base.copy()
        nl.comps["K1"]["footprint"] = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
        self.assertTrue(bom.check_footprints(nl))


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        NET, BOM = sys.argv[1], sys.argv[2]
        del sys.argv[1:3]
    unittest.main(verbosity=2)
