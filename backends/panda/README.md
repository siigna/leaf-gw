# panda / Ocelot backend

Runs the gateway core as comma-panda custom firmware, on two boards:

| board | scons project | board definition |
|---|---|---|
| **RetroPilot Ocelot Pro** (STM32F413, 3× TJA1042), the bench platform | `leaf_gw` | the tree's `boards/gateway.h` |
| **the leaf-gw board** ([`hardware/board/`](../../hardware/board/SPEC.md)) | `leaf_gw_board` | `board_leaf_gw.h`, built in as `boards/leaf_gw.h`, selected with `-DLEAF_GW_BOARD` |

Both are panda-compatible, so stock panda firmware + Cabana can do the phase-0
capture on the Ocelot before any custom code.

`gw_panda.c` is a bare-metal, **interrupt-driven interceptor** modeled on the
RetroPilot ocelot `smart_dsu` MITM reference. Unlike the FreeRTOS backends it
does **not** use a blocking HAL seam; it calls the pure, host-tested
core (`leaf_gw.c`, `gw_engine.c`) straight from the CAN RX interrupts — the way
panda-class firmware forwards frames. The relay, watchdog and fault handling
live in `gw_supervisor.c`, also pure and host-tested (`test_gw_supervisor.c`).

Bus map (Ocelot H1, and the board's transceivers 1–3): **CAN1 = Chassis CAN
ADAS side**, **CAN2 = Chassis CAN car side**, **CAN3 = V-CAN tap** (openpilot's
`0x2B0`/`0x1C3`, the gateway's `0x5FF` heartbeat).

> **UNTESTED ON HARDWARE, BENCH-ONLY.** Both images compile, link and sign for
> the F413 (below), but neither has run on a board, and nothing here has run on
> a Leaf. Validate the 0x2B0 / 0x1C3 layouts on a real ZE1 (tracker issue #5)
> and work through [`BRINGUP.md`](BRINGUP.md) on the bench first. Never on a
> car anyone drives.

## Building

`nix build .#ocelot-firmware` builds both images offline from the pinned
RetroPilot tree and leaves them in `result/`:

| file | what |
|---|---|
| `bootstub.bin` | the tree's bootstub, flashed at `0x08000000`; checks the signature, then jumps to the app |
| `leaf_gw.bin.signed` | Ocelot image, flashed at `0x08004000` |
| `leaf_gw_board.bin.signed` | leaf-gw board image, flashed at `0x08004000` |
| `*.elf` | the same with symbols, for SWD debugging |

Images are signed with the tree's debug key, which the bootstub from the same
build accepts (`ALLOW_DEBUG`). `nix flake check` runs the same build
(`checks.ocelot-firmware`), and also checks that only the board image contains
`board_leaf_gw`, so the build-time selection can't silently fall back to the
Ocelot's board.

By hand, inside the RetroPilot `ocelot/firmware/` tree (`nix develop .#panda`
gives `arm-none-eabi-gcc`, scons and pycryptodome):

1. `mkdir firmware/leaf_gw` and copy in `gw_panda.c` (as `main.c`) and the
   repo's `leaf_gw.{c,h}`, `gw_engine.{c,h}` and `gw_supervisor.{c,h}`.
2. Copy `board_leaf_gw.h` to `firmware/boards/leaf_gw.h`.
3. Copy the cut-down `smart_dsu/can.h` to `firmware/leaf_gw/can.h`. Every
   RetroPilot pedal-like core ships one; `gw_panda.c` includes it as `"can.h"`.
4. `python3 ocelot_register.py firmware/SConscript` adds both projects to the
   `projects` dict and links the three core objects into their `Program(...)`
   (panda builds a single main TU).
5. `cd firmware && PROJECT=leaf_gw scons -u` and/or
   `PROJECT=leaf_gw_board scons -u`. Both share `leaf_gw/main.o`, which scons
   rebuilds when the flags change, so build one project per invocation.

## What differs on the leaf-gw board

- **Clock.** The tree's `clock_init()` is written for the Ocelot's 16 MHz
  crystal; the board has 8 MHz (SPEC "MCU"). `leaf_gw_clock_init()` sets PLL
  N = 192 instead of 96, which gives the Ocelot's clocks (96 MHz SYSCLK, 24 MHz
  APB1 for CAN, 48 MHz USB). The bootstub still runs the tree's
  `clock_init()` (48 MHz on our crystal); that only matters for its USB soft
  flasher, which we don't use.
- **Ignition sense** on PA1 (ADC1_IN1), VIN_PROT through 100k / 22k. Below
  8 V (`SUP_IGN_MIN_MV`) the gateway won't engage, and drops out if engaged. On
  USB power alone VIN_PROT is 0 V, so the board stays in passthrough (and the
  relay coil has no supply there anyway).
- **Watchdog kick** on PC6 (TPS3828 WDI), **status LED** on PC7. The Ocelot
  build leaves both alone.

## Relay, watchdog and faults

`gw_supervisor.c`, called once per main-loop pass:

| state | transceivers | relay (PB12) | WDI (PC6) | forwarding | heartbeat | LED |
|---|---|---|---|---|---|---|
| `WAIT` | on | off (stock) | floating (watchdog off) | off | status 0 | 1 Hz blink |
| `ENGAGING` | on | **on** | toggling | off | status 0 | on |
| `ENGAGED` | on | on | toggling every 100 ms | **on** | `INLINE` (+ `OP_ACTIVE`) | on |
| `FAULT` (latched) | standby | off | floating | off | **none** | 5 Hz blink |

- `WAIT` → `ENGAGING` once the transceivers have been up 10 ms, ignition is
  on, no controller is bus-off, and both Chassis CAN sides received a frame in
  the last 250 ms. WDI starts toggling before the relay energizes.
- `ENGAGING` → `ENGAGED` after 10 ms of relay settle (G6K operate ≤ 3 ms).
  Only then do the RX interrupts forward.
- Any fault in `ENGAGING` / `ENGAGED` → `FAULT`, in this order in one pass:
  forwarding off (and the queued chassis TX frames dropped), relay off, WDI
  floated, transceivers to standby. Faults: ignition low, bus-off on any of the
  three controllers (latched in the SCE interrupt, since auto bus-off recovery
  can clear it within ~3 ms), no frame on either Chassis CAN side for 250 ms
  (RX interrupt dead, or that side's bus dead), or a forwarding TX queue
  overflow (frames lost).
- `FAULT` lasts until power is cycled (IGN off and on): the car stays stock
  for the rest of the drive instead of retrying on a flaky bus. The heartbeat
  stops, so openpilot's panda rx check drops controls within about 1 s.

**Why the kick is in the main loop.** The forwarding runs in the CAN RX
interrupts, which keep firing even if the main loop is dead; a kick from an
interrupt (or a timer) would keep the relay engaged with no supervisor running.
The kick sits inside `sup_step()`, and only in a pass where every health input
is good. If the main loop stalls, nothing kicks: the internal IWDG (50 ms) or
the TPS3828 (0.9–2.5 s) pulls NRST, and NRST is the AND gate's second input, so
the relay drops in hardware. If the interrupts stall instead, the RX counters
stop and the supervisor faults within 250 ms.

## Flashing

The images are headless (no USB stack), so `Panda().flash()` and the
bootstub's soft flasher can't reach them. Flash through the STM32 ROM
bootloader (DFU) or SWD.

**DFU (USB).** Hold the **DFU** button (SW1; or bridge the `BOOT0` pad to
`3V3`) while plugging in USB-C, or while shorting the `NRST` pad to `GND`
briefly. The board enumerates as `0483:df11` (STM32 BOOTLOADER). On the Ocelot
Pro, hold SW1 while plugging in. Then:

```sh
nix shell nixpkgs#dfu-util
dfu-util -d 0483:df11 -a 0 -s 0x08004000 -D result/leaf_gw_board.bin.signed
dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D result/bootstub.bin
```

(Ocelot: `leaf_gw.bin.signed` instead.) In ROM DFU, PB12 is high-Z (its
pull-down holds the relay off) and WDI floats (the TPS3828 is disabled), so the
board stays in DFU without resetting.

**SWD.** Pads `SWDIO`, `SWCLK`, `NRST`, `3V3`, `GND` (the `BOOT0` pad sits
with them). With an ST-Link:

```sh
nix shell nixpkgs#openocd
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
  -c "program result/bootstub.bin 0x08000000" \
  -c "program result/leaf_gw_board.bin.signed 0x08004000 verify reset exit"
```

A breakpoint while the relay is engaged stops the kicks, so the TPS3828 resets
the MCU after 0.9–2.5 s (and the IWDG after 50 ms unless frozen; see
`BRINGUP.md`). In `WAIT` WDI floats and breakpoints are safe.

## Headless vs USB

`gw_panda.c` builds **headless** by default: it stubs the serial `puts`/`puth`
and the USB TX-pacing hooks the pedal-core `can.h` expects, so no USB device
stack is pulled in. Define `TGW_USB` and include `drivers/uart.h` +
`drivers/usb.h` (and the `usb_cb_*` callbacks, see `smart_dsu/main.c`) if you
want Cabana over USB or a USB control link instead of CAN3.

## Fail-open relay on the Ocelot

The Ocelot has **no onboard fail-open relay** and no external watchdog. Wire an
external normally-closed relay on the Chassis CAN cut, driven from PB12
(`sup_hw_relay` in `gw_panda.c`; change the pin to match your wiring, H4/H5 or
an IGN_OUT-gated FET). De-energized (reset / brown-out / IWDG trip) it must
connect ADAS↔chassis directly. The Ocelot build has no ignition sense (PA1 is
its IGN_OUT output), so it treats ignition as always on. See
`../../HARDWARE.md`.
