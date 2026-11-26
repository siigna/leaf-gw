"""Every part on the board, with its JLCPCB/LCSC sourcing.

One row per distinct part. `lcsc`/`mpn`/`jlc` were checked against JLCPCB's
parts library on 2026-11-26 (`stock` is what it showed then). `jlc` is
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
    "R_1k": P("Device", "R", R0603, "1k", "C21190", "0603WAF1001T5E", "UNI-ROYAL", "basic", 37717478),
    "R_4k7": P("Device", "R", R0603, "4.7k", "C23162", "0603WAF4701T5E", "UNI-ROYAL", "basic", 17957610),
    "R_5k1": P("Device", "R", R0603, "5.1k", "C23186", "0603WAF5101T5E", "UNI-ROYAL", "basic", 17462792),
    "R_10k": P("Device", "R", R0603, "10k", "C25804", "0603WAF1002T5E", "UNI-ROYAL", "basic", 39826936),
    "R_27k": P("Device", "R", R0603, "27k", "C22967", "0603WAF2702T5E", "UNI-ROYAL", "basic", 565535),
    "R_33k": P("Device", "R", R0603, "33k", "C4216", "0603WAF3302T5E", "UNI-ROYAL", "basic", 2613605),
    "R_100k": P("Device", "R", R0603, "100k", "C25803", "0603WAF1003T5E", "UNI-ROYAL", "basic", 12032554),
    "R_60R4": P("Device", "R", R0603, "60.4", "C23090", "0603WAF604JT5E", "UNI-ROYAL", "extended", 21358),
    "C_30p": P("Device", "C", C0402, "30pF C0G", "C1570", "0402CG300J500NT", "FH", "preferred", 176434),
    "C_4n7": P("Device", "C", C0603, "4.7nF 50V", "C53987", "0603B472K500NT", "FH", "basic", 761583),
    "C_100n": P("Device", "C", C0402, "100nF 16V", "C1525", "CL05B104KO5NNNC", "Samsung", "basic", 30646311),
    "C_100n_50V": P("Device", "C", C0603, "100nF 50V", "C14663", "CC0603KRX7R9BB104", "YAGEO", "basic", 42508247),
    "C_1u": P("Device", "C", C0402, "1uF 25V", "C52923", "CL05A105KA5NQNC", "Samsung", "basic", 12174155),
    "C_1u_50V": P("Device", "C", C0805, "1uF 50V", "C28323", "CL21B105KBFNNNE", "Samsung", "basic", 3622240),
    "C_4u7": P("Device", "C", C0603, "4.7uF 16V", "C19666", "CL10A475KO8NNNC", "Samsung", "basic", 2943222),
    "C_22u": P("Device", "C", C0805, "22uF 25V", "C45783", "CL21A226MAQNNNE", "Samsung", "basic", 4438348),
    "L_22u": P("Device", "L", "Inductor_SMD:L_Sunlord_SWPA4030S", "22uH 1A", "C83472", "SWPA4030S220MT", "Sunlord", "extended", 16749),
    "Y_8M": P("Device", "Crystal", "Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm", "8MHz 20pF", "C115962", "X50328MSB2GI", "YXC", "basic", 510086),
    "LED_red": P("Device", "LED", "LED_SMD:LED_0603_1608Metric", "red", "C2286", "KT-0603R", "KENTO", "basic", 8572121),
    "SW_push": P("Switch", "SW_Push", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "TS-1187A", "C318884", "TS-1187A-B-A-B", "XKB", "basic", 653959),
    # diodes and protection
    "D_SS210": P("Device", "D_Schottky", "Diode_SMD:D_SMA", "SS210", "C14996", "SS210", "MDD", "basic", 879732),
    "D_B5819W": P("Device", "D_Schottky", SOD123, "B5819W", "C8598", "B5819W SL", "CJ", "basic", 878213),
    "D_1N4148W": P("Device", "D", SOD123, "1N4148W", "C81598", "1N4148W", "Semtech", "basic", 4223528),
    # unidirectional TVS, drawn as a Zener (pin 1 = cathode, like the SMB pad 1)
    "D_TVS24": P("Device", "D_Zener", "Diode_SMD:D_SMB", "SMBJ24A", "C123819", "SMBJ24A", "MDD", "extended", 47592),
    "F_PTC": P("Device", "Polyfuse", "Fuse:Fuse_1206_3216Metric", "200mA hold 30V", "C69680", "nSMD020-30V", "TECHFUSE", "extended", 342225),
    "ESD_CAN": P("Power_Protection", "NUP2105L", "Package_TO_SOT_SMD:SOT-23", "PESD2CAN", "C75176", "PESD2CAN,215", "Nexperia", "extended", 28898),
    "ESD_USB": P("Power_Protection", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6", "C7519", "USBLC6-2SC6", "ST", "extended", 34701),
    # semiconductors
    "MCU": P("MCU_ST_STM32F4", "STM32F413RGTx", "Package_QFP:LQFP-64_10x10mm_P0.5mm", "STM32F413RGT6", "C468260", "STM32F413RGT6", "ST", "extended", 90),
    "CAN_XCVR": P("Interface_CAN_LIN", "TJA1042T-3", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "TJA1042T/3", "C132227", "TJA1042T/3/1J", "NXP", "extended", 47911),
    "RELAY": P("Relay", "Omron_G6K-2", "Relay_SMD:Relay_DPDT_Omron_G6K-2F-Y", "G6K-2F-Y DC5", "C2982926", "G6K-2F-Y-5V", "Omron", "extended", 14095),
    "NMOS": P("Transistor_FET", "AO3400A", "Package_TO_SOT_SMD:SOT-23", "AO3400A", "C20917", "AO3400A", "AOS", "basic", 1337567),
    "AND": P("74xGxx", "74LVC1G08", "Package_TO_SOT_SMD:SOT-23-5", "SN74LVC1G08DBVR", "C7666", "SN74LVC1G08DBVR", "TI", "extended", 100026),
    # TPS3828 = TPS3823 with an open-drain RESET (same pinout, TI SLVS165O table 4-1)
    "WDT": P("Power_Supervisor", "TPS3823-xxDBV", "Package_TO_SOT_SMD:SOT-23-5", "TPS3828-33DBVR", "C20032", "TPS3828-33DBVR", "TI", "extended", 37485),
    # LMR16006X (700 kHz) DDC: CB GND FB SHDN VIN SW, same pinout as the YQ symbol
    "BUCK": P("Regulator_Switching", "LMR16006YQ", "Package_TO_SOT_SMD:SOT-23-6", "LMR16006XDDCR", "C87080", "LMR16006XDDCR", "TI", "extended", 65748),
    "LDO": P("Regulator_Linear", "XC6206PxxxMR", "Package_TO_SOT_SMD:SOT-23-3", "XC6206P332MR", "C5446", "XC6206P332MR-G", "Torex", "basic", 458235),
    # connectors
    "USB_C": P("Connector", "USB_C_Receptacle_USB2.0_16P", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", "TYPE-C-31-M-12", "C165948", "TYPE-C-31-M-12", "HRO", "extended", 424994),
    "HDR18": P("Connector_Generic", "Conn_02x09_Odd_Even", "leaf_gw:Molex_iGrid_501645-1820_2x09_P2.00mm_Vertical", "501645-1820", "C504976", "5016451820", "Molex", "extended", 5765),
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
