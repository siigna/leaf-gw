# Ordering the board (JLCPCB)

Everything JLCPCB needs is generated in `out/fab/` by `layout/fab.py` and
checked by `check_layout.sh`. Order only from a commit where
`nix flake check` passes.

> Bench and a dedicated test car only (see `SPEC.md`).

## Files

| upload step | file |
|---|---|
| PCB (Gerber) | `out/fab/leaf_gw-gerbers.zip` |
| Assembly: BOM | `out/fab/leaf_gw-bom.csv` |
| Assembly: pick and place (CPL) | `out/fab/leaf_gw-cpl.csv` |

`out/fab/leaf_gw-cpl-corrections.csv` lists what `fab.py` changed in each
part's rotation and where the number came from. It is for checking, not for
upload.

## PCB options

| option | choose | why |
|---|---|---|
| Base material | FR-4 | |
| Material type | FR4-TG155 if offered, else TG135 | margin for reflow and a hot cabin; keep whichever still offers the JLC04161H-7628 stackup (below) |
| Different design | 1 | |
| Delivery format | single PCB | 75 × 50 mm assembles without a panel |
| Layers | 4 | |
| Dimensions | 75 × 50 mm (read from the Gerbers) | |
| PCB qty | 5 | the first batch: bring-up and spares |
| Thickness | 1.6 mm | |
| Impedance control | yes, stackup **JLC04161H-7628** | the CAN (120 Ω) and USB (90 Ω) pair geometry is calculated for this stackup (`layout/impedance.py`) |
| Solder mask colour | purple | the colour previews are in `out/render/colors/` |
| Silkscreen | white | |
| Surface finish | **ENIG** | the leaf on the top is exposed copper and reads as gold only with ENIG; HASL leaves it lumpy and silver |
| Gold thickness | 1 µ″ | ENIG's standard; thicker gold is for edge connectors that wear, which this board has none of |
| Outer copper | 1 oz | |
| Inner copper | 0.5 oz | the In2 checks assume 15.2 µm inner copper |
| Via covering | tented | the board is drawn with tented vias |
| Min via hole / diameter | 0.3 / 0.6 mm (no upgrade needed) | |
| Mark on PCB (order number) | remove it, or specify a location | JLC's default spot may land on the silkscreen or the leaf |

If JLC doesn't offer purple with ENIG for this stackup, pick another mask
colour from the previews. Don't drop ENIG.

## Assembly options

| option | choose | why |
|---|---|---|
| PCBA type | Standard | the two 18-pin headers are through-hole; Economic doesn't place them |
| Assembly side | top | every part is on the top (`check_top_side`) |
| PCBA qty | 5 (or 2 to start) | |
| Tooling holes | added by JLCPCB | |
| Through-hole parts (J1, J2) | assembled by JLCPCB | or leave them off and hand-solder: 2 × 18 pins |

### At the BOM step

- Every line has an LCSC number. Check each shows in stock. The ones to
  watch are the extended parts with low stock: STM32F413RGT6 (C468260,
  about 90 in stock when last checked), the Molex headers (C504976), the
  G6K-2F-Y relay (C2982926) and the TJA1042T/3 (C132227).
- If one is out of stock, stop and swap it in the schematic (`schematic/`).
  Don't let JLC substitute.

### At the placement preview

The CPL rotations for these parts come from community tables, not from each
part's own footprint. Check each against its pin 1 / orientation mark in the
preview:

| part | what to check |
|---|---|
| U1 (STM32, LQFP-64) | pin 1 dot at the board's pin 1 mark |
| K1 (relay) | the relay's pin 1 mark at the footprint's pin 1 |
| U7, U9 (SOT-23-6) | pin 1 at the footprint's pin 1 dot |
| J1, J2 (Molex headers) | the body over its 18 holes; the locator peg on the hole outside the pin 1/2 column |

Also check polarity on every diode, LED and ESD array: the cathode band, or
the pin 1 mark, on the footprint's mark. If something is off, fix it in
`layout/fab.py`, not in JLC's editor. Otherwise the next order has the same
error.

## The board-to-box cable (make it yourself)

The board reaches the stock harness box through J2 and a short cable. This
cable is not sold.

- 2 × Molex **501646-1800** receptacle housing (iGrid, 18 circuits).
- 16 × Molex **501647-1000** crimp terminals (AWG 22–26), plus spares.
- AWG 24–26 stranded wire. Twist the CAN pairs: 4/6, 16/18 and 8/7.
- Crimp tool: Molex's hand tool for 501647 is 578021-5300. A generic
  open-barrel crimper for 2.0 mm terminals (Engineer PA-09 class) also
  works, with care.
- Wire pin n to pin n. **Leave positions 9 and 11 empty at both ends.** The
  box would otherwise join the ADAS-side and car-side Chassis CAN halves
  around the gateway (`SPEC.md`, "The 18-pin connector").
- Keep it short (10–15 cm). Don't bundle the wires within 35 mm of either
  housing (Molex application spec).
- Before use, with a meter:
  - every pin n reaches pin n;
  - no two pins touch;
  - 9 and 11 are open.

## The case

See `../enclosure/README.md`. You need 2 × M2 × 10 pan-head self-tapping
screws for plastic, plus the printed tray and lid.
