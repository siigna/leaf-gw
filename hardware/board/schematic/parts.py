"""Every part on the board, with its JLCPCB/LCSC sourcing.

One row per distinct part. `lcsc`/`mpn`/`jlc` were checked against JLCPCB's
parts library on 2026-11-26 (`stock` is what it showed then); every row was
re-checked on 2026-11-27 for the pre-order review. `jlc` is
"basic" (no setup fee), "preferred" (extended, fee waived) or "extended".
"""

from collections import namedtuple

from skidl import Part

P = namedtuple("P", "lib sym fp value lcsc mpn mfr jlc stock")

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOD123 = "Diode_SMD:D_SOD-123"

PARTS = {
    # passives
    "R_1k": P("Device", "R", R0603, "1k", "C21190", "0603WAF1001T5E", "UNI-ROYAL", "basic", 36313912),
    "R_4k7": P("Device", "R", R0603, "4.7k", "C23162", "0603WAF4701T5E", "UNI-ROYAL", "basic", 18075861),
    "R_5k1": P("Device", "R", R0603, "5.1k", "C23186", "0603WAF5101T5E", "UNI-ROYAL", "basic", 17262608),
    "R_10k": P("Device", "R", R0603, "10k", "C25804", "0603WAF1002T5E", "UNI-ROYAL", "basic", 38840366),
    "R_22k": P("Device", "R", R0603, "22k", "C31850", "0603WAF2202T5E", "UNI-ROYAL", "basic", 2006051),
    "R_28k": P("Device", "R", R0603, "28k", "C22989", "0603WAF2802T5E", "UNI-ROYAL", "extended", 102251),
    "R_100k": P("Device", "R", R0603, "100k", "C25803", "0603WAF1003T5E", "UNI-ROYAL", "basic", 13791470),
    "R_60R4": P("Device", "R", R0603, "60.4", "C23090", "0603WAF604JT5E", "UNI-ROYAL", "extended", 17967),
    "C_10n": P("Device", "C", C0402, "10nF 50V", "C15195", "CL05B103KB5NNNC", "Samsung", "basic", 3704802),
    "C_30p": P("Device", "C", C0402, "30pF C0G", "C1570", "0402CG300J500NT", "FH", "preferred", 176619),
    "C_4n7": P("Device", "C", C0603, "4.7nF 50V", "C53987", "0603B472K500NT", "FH", "basic", 1193387),
    "C_100n": P("Device", "C", C0402, "100nF 16V", "C1525", "CL05B104KO5NNNC", "Samsung", "basic", 28139937),
    "C_100n_50V": P("Device", "C", C0603, "100nF 50V", "C14663", "CC0603KRX7R9BB104", "YAGEO", "basic", 44117980),
    "C_1u": P("Device", "C", C0402, "1uF 25V", "C52923", "CL05A105KA5NQNC", "Samsung", "basic", 11020353),
    "C_2u2_50V": P("Device", "C", C0805, "2.2uF 50V X7R", "C125847", "CC0805KKX7R9BB225", "YAGEO", "extended", 89345),
    "C_4u7": P("Device", "C", C0603, "4.7uF 16V", "C19666", "CL10A475KO8NNNC", "Samsung", "basic", 2823038),
    "C_22u": P("Device", "C", C0805, "22uF 25V", "C45783", "CL21A226MAQNNNE", "Samsung", "basic", 4353392),
    # 6.8 uH for the 2.1 MHz LMR16006Y (SNVSA24 table 2); Isat 2.75 A, Irms 1.6 A, DCR 117 mohm
    "L_6u8": P("Device", "L", "Inductor_SMD:L_Sunlord_SWPA4030S", "6.8uH 2.75A", "C62684", "SWPA4030S6R8MT", "Sunlord", "extended", 20484),
    "Y_8M": P("Device", "Crystal", "Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm", "8MHz 20pF", "C115962", "X50328MSB2GI", "YXC", "basic", 506868),
    "LED_red": P("Device", "LED", "LED_SMD:LED_0603_1608Metric", "red", "C2286", "KT-0603R", "KENTO", "basic", 8430004),
    "SW_push": P("Switch", "SW_Push", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "TS-1187A", "C318884", "TS-1187A-B-A-B", "XKB", "basic", 634624),
    # diodes and protection
    "D_SS210": P("Device", "D_Schottky", "Diode_SMD:D_SMA", "SS210", "C14996", "SS210", "MDD", "basic", 842768),
    "D_B5819W": P("Device", "D_Schottky", SOD123, "B5819W", "C8598", "B5819W SL", "CJ", "basic", 1044236),
    "D_1N4148W": P("Device", "D", SOD123, "1N4148W", "C81598", "1N4148W", "Semtech", "basic", 4126998),
    # unidirectional TVS, drawn as a Zener (pin 1 = cathode, like the SMB pad 1)
    "D_TVS33": P("Device", "D_Zener", "Diode_SMD:D_SMB", "SMBJ33A", "C224019", "SMBJ33A", "Littelfuse", "extended", 23761),
    "F_PTC": P("Device", "Polyfuse", "Fuse:Fuse_1812_4532Metric", "500mA hold 60V", "C70113", "mSMD050-60V", "TECHFUSE", "extended", 269194),
    "ESD_CAN": P("Power_Protection", "NUP2105L", "Package_TO_SOT_SMD:SOT-23", "PESD2CAN", "C75176", "PESD2CAN,215", "Nexperia", "extended", 47430),
    "ESD_USB": P("Power_Protection", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6", "C7519", "USBLC6-2SC6", "ST", "extended", 27004),
    # semiconductors
    # no T7/T3 (105/125 C) grade of the RG at JLCPCB; T6 = 85 C at full power, 105 C at low power (DS11581 table 16)
    "MCU": P("MCU_ST_STM32F4", "STM32F413RGTx", "Package_QFP:LQFP-64_10x10mm_P0.5mm", "STM32F413RGT6", "C468260", "STM32F413RGT6", "ST", "extended", 11),
    "CAN_XCVR": P("Interface_CAN_LIN", "TJA1042T-3", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "TJA1042T/3", "C132227", "TJA1042T/3/1J", "NXP", "extended", 37294),
    # every G6K is rated -40..+70 C ambient (en-g6k.pdf p.3); G6KU is latching, not fail-open
    "RELAY": P("Relay", "Omron_G6K-2", "Relay_SMD:Relay_DPDT_Omron_G6K-2F-Y", "G6K-2F-Y DC5", "C2982926", "G6K-2F-Y-5V", "Omron", "extended", 35487),
    "NMOS": P("Transistor_FET", "AO3400A", "Package_TO_SOT_SMD:SOT-23", "AO3400A", "C20917", "AO3400A", "AOS", "basic", 1303752),
    "AND": P("74xGxx", "74LVC1G08", "Package_TO_SOT_SMD:SOT-23-5", "SN74LVC1G08DBVR", "C7666", "SN74LVC1G08DBVR", "TI", "extended", 94527),
    # TPS3828 = TPS3823 with an open-drain RESET (same pinout, TI SLVS165O table 4-1); -40..85 C.
    # The -40..125 C TPS3828-33QDBVRQ1 (C2872895) had 1 in stock on 2026-11-27.
    "WDT": P("Power_Supervisor", "TPS3823-xxDBV", "Package_TO_SOT_SMD:SOT-23-5", "TPS3828-33DBVR", "C20032", "TPS3828-33DBVR", "TI", "extended", 41300),
    # LMR16006Y (2.1 MHz, above the AM band) DDC: CB GND FB SHDN VIN SW (SNVSA24 sec. 6), as the YQ symbol
    "BUCK": P("Regulator_Switching", "LMR16006YQ", "Package_TO_SOT_SMD:SOT-23-6", "LMR16006YDDCR", "C290195", "LMR16006YDDCR", "TI", "extended", 16130),
    # MCP1700 E grade: TA -40..+125 C (DS20001826E); SOT-23 1 GND 2 VOUT 3 VIN, as the XC6206 it replaced
    "LDO": P("Regulator_Linear", "MCP1700x-330xxTT", "Package_TO_SOT_SMD:SOT-23-3", "MCP1700T-3302E/TT", "C39051", "MCP1700T-3302E/TT", "Microchip", "extended", 23887),
    # connectors
    "USB_C": P("Connector", "USB_C_Receptacle_USB2.0_16P", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", "TYPE-C-31-M-12", "C165948", "TYPE-C-31-M-12", "HRO", "extended", 393127),
    "HDR18": P("Connector_Generic", "Conn_02x09_Odd_Even", "leaf_gw:Molex_iGrid_501645-1820_2x09_P2.00mm_Vertical", "501645-1820", "C504976", "5016451820", "Molex", "extended", 5760),
}

# Not assembled: bare copper, no BOM line. Each carries the reason in `no_bom`.
NOBOM = {
    "TP": ("Connector", "TestPoint", "TestPoint:TestPoint_Pad_D1.5mm", "test pad (bare copper)"),
    "JP_open": ("Jumper", "SolderJumper_2_Open", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
                "solder jumper, default open (bare copper)"),
}


def part(key, ref=None, value=None):
    d = PARTS[key]
    p = Part(d.lib, d.sym, value=value or d.value, footprint=d.fp, ref=ref, tag=ref or None)
    p.fields["LCSC"] = d.lcsc
    p.fields["MPN"] = d.mpn
    p.fields["Manufacturer"] = d.mfr
    p.fields["JLC"] = d.jlc
    return p


def nobom(key, value, ref=None):
    lib, sym, fp, reason = NOBOM[key]
    p = Part(lib, sym, value=value, footprint=fp, ref=ref, tag=ref or None)
    p.fields["no_bom"] = reason
    return p
