# panda / Ocelot backend

Runs the gateway core as comma-panda custom firmware on a **RetroPilot Ocelot
Pro** (STM32F413, 3× TJA1042). Panda-compatible, so stock panda firmware +
Cabana can do the phase-0 capture before any custom code.

`gw_panda.c` is a bare-metal, **interrupt-driven interceptor** modeled on the
RetroPilot ocelot `smart_dsu` MITM reference. Unlike the FreeRTOS backends it
does **not** use a blocking HAL seam; it calls the pure, host-tested
core (`leaf_gw.c`, `gw_engine.c`) straight from the CAN RX interrupts — the way
panda-class firmware forwards frames.

Bus map (Ocelot H1): **CAN1 = ADAS side**, **CAN2 = chassis side**,
**CAN3 = openpilot control link**.

> **UNTESTED ON A CAR, BENCH-ONLY.** It compiles, links and signs cleanly for
> the F413 (below), but nothing here has run on a Leaf. Validate the 0x2B0 /
> 0x1C3 layouts on a real ZE1 (tracker issue #5) and prove the external
> fail-open relay reverts to stock on reset and power loss first.

## Building it (in an Ocelot/panda firmware tree)

Drop this backend into the RetroPilot `ocelot/firmware/` tree as a project —
these steps produce a signed image:

1. `mkdir firmware/leaf_gw` and copy in `gw_panda.c` (as `main.c`), plus the
   repo's `leaf_gw.{c,h}` and `gw_engine.{c,h}`.
2. Copy the cut-down `smart_dsu/can.h` to `firmware/leaf_gw/can.h`. Every
   RetroPilot pedal-like core ships one; `gw_panda.c` includes it as `"can.h"`.
3. Register the project in `firmware/SConscript`: add a `leaf_gw` entry to the
   `projects` dict (startup `startup_stm32f413xx.s`, `PROJECT_FLAGS`), and add
   `leaf_gw.c` + `gw_engine.c` to that project's `Program(...)` sources — panda
   builds a single main TU, so the engine objects must be linked explicitly.
4. `cd firmware && PROJECT=leaf_gw scons -u`.

Toolchain: `arm-none-eabi-gcc` (`-mcpu=cortex-m4 -DSTM32F4 -DSTM32F413xx`) and
scons with `pycryptodome` for the signing step. A pinned build was verified with
`nix shell nixpkgs#gcc-arm-embedded nixpkgs#scons` (pycryptodome on `PYTHONPATH`).

## Headless vs USB

`gw_panda.c` builds **headless** by default: it stubs the serial `puts`/`puth`
and the USB TX-pacing hooks the pedal-core `can.h` expects, so no USB device
stack is pulled in. Define `TGW_USB` and include `drivers/uart.h` +
`drivers/usb.h` (and the `usb_cb_*` callbacks, see `smart_dsu/main.c`) if you
want Cabana over USB or a USB control link instead of CAN3.

## Fail-open relay

Ocelot has **no onboard fail-open relay** — wire an external normally-closed
relay on the Chassis CAN cut (GPIO on H4/H5 or the PA1 IGN_OUT rail) and set the pin
in `RELAY_PORT`/`RELAY_PIN` at the top of `gw_panda.c`. De-energized (reset /
brown-out / IWDG trip) it must connect ADAS↔chassis directly. See
`../../HARDWARE.md`.
