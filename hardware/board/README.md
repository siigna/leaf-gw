# leaf-gw board

The inline gateway board from [SPEC.md](SPEC.md). This is phase 2: the
schematic as SKiDL code, the BOM with LCSC numbers, and the checks that stand
in for a schematic review. Layout is phase 3.

## Files

| path | what |
|---|---|
| `SPEC.md` | the contract |
| `schematic/` | SKiDL, one module per block: `connectors`, `mcu`, `can`, `relay`, `power`, `usb`; `parts.py` holds every part with its LCSC number; `nets.py` names the nets; `board.py` builds the board and writes `out/` |
| `footprints/leaf_gw.pretty/` | project footprints for parts KiCad's library lacks (the Molex iGrid header) |
| `out/leaf_gw.net` | KiCad netlist, for phase 3 to import into the PCB |
| `out/bom_jlcpcb.csv` | JLCPCB BOM: Comment, Designator, Footprint, LCSC |
| `out/parts.csv` | the same parts with manufacturer, MPN, JLC basic/extended and stock as checked |
| `out/no_connects.csv` | every pin left unconnected on purpose, with its reason |
| `checks/` | netlist reader, safety-net checks, BOM/footprint checks, mutation tests |
| `check.sh` | runs all of it |

`out/` is generated, but committed so phase 3 and reviewers have it; the check
fails if it is stale.

There is no `.kicad_sch`: SKiDL 2.2.1 generates schematics only for KiCad 5 to
8 (`gen_schematic` for KiCad 9 and later is an unimplemented stub), and KiCad 10's
libraries are what nixpkgs ships. The netlist is the design's source of truth
between phases.

## Running the checks

```bash
nix develop .#hardware --command ./hardware/board/check.sh            # check
nix develop .#hardware --command ./hardware/board/check.sh --update   # after editing schematic/
nix flake check                                                       # includes board-schematic
```

`nix flake check` copies the flake's git tree, so new files have to be
`git add`ed before it sees them.

Stages, in order (one failing stage doesn't stop the others):

1. **Build + SKiDL ERC.** Any ERC error or warning fails. Unused pins are
   connected to `NC` only through `nets.nc(pin, reason)`, which records the
   reason in `out/no_connects.csv`; every other unconnected pin is an ERC warning.
2. **Freshness.** `out/` must match a fresh build byte for byte.
3. **Safety-net checks** (`checks/safety.py`), on the netlist file and
   independent of the SKiDL code (expected pin numbers come from the
   datasheets, roles from SPEC.md's tables):
   - pass-through: pins 3, 5, 13, 15, 4, 6, 10, 12 join J1.n to J2.n and nothing
     else; GND, IGN, V-CAN ADAS-side and car-side CAN1 join J1 and J2 with no
     other harness pin; IGN enters the board only through the fuse;
   - box-side J2.9 / J2.11 connect to nothing;
   - relay: pole A COM on J1.9, NC on J1.8; pole B COM on J1.11, NC on J1.7;
     NO contacts open; the two CAN1 halves are not hard-wired;
   - CAN lines: each line holds exactly its harness pins, one transceiver pin
     (CANH on H), one ESD pin, one termination jumper and, on CAN1, its relay
     contact. Termination is default-open jumper → 60.4 Ω → split midpoint
     → 60.4 Ω → jumper, midpoint → 4.7 nF → GND. Anything else on a CAN line
     fails, so a CAN line has no other path to power or ground;
   - coil driver: coil+ on the IGN-derived 5 V, coil− on the low-side FET drain
     with a flyback diode; the gate net holds only the AND output and one
     pull-down; AND input A is PB12 with one pull-down; input B is the
     open-drain watchdog RESET, which is also MCU NRST; WDI is driven only by the
     kick pin;
   - USB isolation: the coil supply is not DC-reachable from VBUS (diodes
     forward only), and it is reachable from IGN;
   - MCU pins, by LQFP64 pin number: CAN1/2/3 RX/TX and standby go to the
     transceiver on the right bus, PA1 to the IGN divider, PA11/PA12 to USB D−/D+;
     no two table pins share a net.
4. **BOM + footprints** (`checks/bom.py`): every assembled part has an LCSC
   number and a JLC library type; designators are unique in the netlist and in
   the CSV; the CSV lists exactly the assembled parts; parts off the BOM are bare
   copper (test pads, solder jumpers) with a reason. Every footprint exists and
   has a pad for each connected pin.
5. **Mutation tests** (`checks/test_mutations.py`): 41 in-memory mutations of
   the real netlist, each of which must make its check fail (relay NC/NO
   swapped, poles crossed, box 9/11 connected, gate pull-down dropped, gate fed
   from PB12 directly, watchdog off NRST, CAN1 on the CAN2 pins, RX/TX swapped,
   resistor from a CAN line to GND, closed termination jumper, coil on the USB
   rail, OR diode reversed, missing LCSC, duplicated designator, pin without a
   pad, and more), plus the unmutated netlist passing everything.

## Connectors

comma's car-harness cable ends in a Molex **501646-1800** iGrid receptacle
(2.00 mm, 2×9). Molex lists three mating headers: 501645 (vertical, through
hole), 503091 (vertical) and 501876 (right angle; the harness box uses
501876-1840).

- **J1, J2: Molex 501645-1820** (LCSC C504976), vertical through-hole with a PCB
  locator, 5765 in stock. The right-angle 501876-1840 (C293583) had 4 in stock,
  not enough for 5 boards; 503091 18-way isn't stocked. JLCPCB assembles
  through-hole parts on the top side, so assembly stays single-sided.
  The iGrid header is rated for 30 mating cycles.
- **Board to box:** the box's 501876 header needs a 501646-1800 receptacle, so
  the link is a short cable with a 501646-1800 on **both** ends, wired 1:1
  (pin n to pin n), 26 AWG, about 100 mm, positions 9 and 11 left empty. Parts:
  2 × 501646-1800 (C564678), 16 × 501647-1000 terminals (C122426). Molex lists
  no off-the-shelf iGrid cable assembly, so order it pre-made from a harness
  service (LCSC Cable, lcsccable.com, takes drawings with no MOQ; Molex's custom
  cable service is the alternative). The user only plugs it in. Leaving 9/11
  empty in the cable keeps the box's CAN1 ADAS pins open even if the board were
  wrong.

The header footprint is project-local because KiCad's library has no iGrid
part. Its pads and locator come from LCSC/EasyEDA's footprint for C504976,
which is what JLCPCB assembles to, because Molex's sales drawing
(SD-501645-001) could not be downloaded. Check it against that drawing before
the first order (phase 4).

## Part choices

All 37 BOM lines are JLCPCB-assemblable: 22 basic, 1 preferred extended, 14
extended. `out/parts.csv` has the lot, with stock as of 2026-11-26.

| block | part | LCSC | note |
|---|---|---|---|
| MCU | STM32F413RGT6 | C468260 | as spec; only 90 in stock, so buy it early |
| CAN ×3 | TJA1042T/3/1J | C132227 | STB and TXD pulled up to VIO inside (datasheet 7.2.3), so standby by default |
| CAN ESD ×3 | PESD2CAN,215 | C75176 | |
| relay | Omron G6K-2F-Y DC5 | C2982926 | as spec, 14k in stock |
| coil FET | AO3400A | C20917 | logic-level at 3.3 V gate |
| AND | SN74LVC1G08DBVR | C7666 | |
| watchdog | TPS3828-33DBVR | C20032 | **substitution**, see below |
| buck | LMR16006XDDCR | C87080 | 4–60 V in, 600 mA |
| LDO | XC6206P332MR-G | C5446 | 250 mV dropout at 100 mA, so USB-only power works |
| input | nSMD020-30V PTC, SMBJ24A, SS210 | C69680, C123819, C14996 | fuse → TVS → reverse diode |
| USB | HRO TYPE-C-31-M-12, USBLC6-2SC6 | C165948, C7519 | |

Pin picks the spec left open: watchdog kick **PC6**, status LED **PC7**, both
unused by the Ocelot gateway board. BOOT1 (PB2) is pulled down so ROM DFU boots
system memory.

## Deviations from SPEC.md

- **Watchdog TPS3828-33 instead of TPS3823-33.** Same family, pinout and
  timing (SLVS165O), but the RESET output is open drain. TPS3823's push-pull
  output on NRST would fight the STM32, which drives NRST low itself on IWDG and
  software resets. Open drain on a shared NRST net also means every MCU reset
  releases the relay.
- **Floating WDI disables the timer** (SLVS165O 7.3.4). WDI has no pull
  resistor, so the watchdog does not bite while the MCU is in reset, in ROM DFU
  or halted under SWD reset. That is what makes flashing possible, and in all
  three states PB12 is high-Z and its pull-down keeps the relay off. While
  firmware runs, a stalled kick pin times out in 0.9–2.5 s. The firmware must
  toggle PC6 at least every 0.9 s; `gw_panda.c` doesn't yet (phase 5).
  Breakpoints longer than that reset the MCU.
- **Buck at 5.16 V, not 5.0 V** (27k / 4.7k on the 0.765 V reference). After the
  OR diode, +5V_SYS has to stay inside the TJA1042's 4.5–5.5 V VCC range. The
  relay coil runs from +5V_IGN before the diode; it is rated for 150 % of 5 V.
- **Vertical headers**, not right-angle (stock, above).
- **Ignition sense**: 100k / 33k from the protected IGN rail, 100 nF, and a
  1N4148W clamp to 3V3 (12 V in gives 2.9 V on PA1).
- **No `.kicad_sch`**, so phase 2's ERC is SKiDL's, not `kicad-cli sch erc`.
