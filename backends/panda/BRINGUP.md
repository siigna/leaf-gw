# leaf-gw board: bring-up checklist

For the day the boards arrive. **Bench only, never on a car**, and never on the
family car. Work through it in order on each board and stop at the first step
that doesn't match; note the board's number and what you saw.

Net and part names are the schematic's (`hardware/board/schematic/`,
`hardware/board/out/leaf_gw.net`). "J1" is the harness-cable header, "J2" the
box-side header; pins are the 18-pin connector's (`SPEC.md`).

## You need

- Bench supply, 12 V, current limit **200 mA** (SPEC budget is ~150 mA with the
  relay coil on).
- Multimeter (continuity, DC volts, mA).
- Three CAN adapters at 500 kbit (candleLight / USB-CAN / a panda), SocketCAN
  `can-utils` (`cangen`, `candump`). Each Chassis CAN side needs its **own**
  traffic once the relay opens: the gateway's stall check faults a side that
  is silent for 250 ms.
- 120 Ω at each end of each bus segment: close the board's `TERM` jumpers for
  the bench, or terminate at the adapters, so each segment reads about 60 Ω.
- USB-C cable, `dfu-util`, optionally an ST-Link + `openocd` on the SWD pads.
- `nix build .#ocelot-firmware` (images in `result/`).

## 1. Unpowered

- [ ] Visual: no bridges on U1 (LQFP64), relay K1 and both headers seated.
- [ ] Continuity **through the relay NC contacts**: J1-9 ↔ J1-8 (CAN_H) and
      J1-11 ↔ J1-7 (CAN_L) beep. This is the stock path.
- [ ] J2-9 and J2-11 connect to nothing.
- [ ] Pass-throughs J1-n ↔ J2-n for every other pin (1–8, 10, 12–18).
- [ ] No short: IGN (pin 2) to GND, +5V_IGN, +5V_SYS and +3V3 to GND (test
      pads or capacitor ends) all read well above 100 Ω.

## 2. Power on (12 V on pins 2/14, GND on 1/17)

- [ ] Current with a blank MCU: note it; steady and well under the 150 mA
      budget, no climb.
- [ ] Rails: +5V_IGN ≈ 5.16 V, +5V_SYS ≈ 4.8–4.9 V (after the OR diode),
      +3V3 ≈ 3.30 V, IGN_SENSE (PA1) ≈ 2.8–2.9 V at 12 V in.
- [ ] Power LED on. Relay doesn't click; J1-9 ↔ J1-8 still continuous.
- [ ] USB-C alone (no 12 V): power LED on, relay still closed (coil runs from
      +5V_IGN only), IGN_SENSE ≈ 0 V.

## 3. DFU and flashing

- [ ] Hold **DFU** (SW1) while plugging in USB-C: `lsusb` shows `0483:df11`,
      `dfu-util -l` lists the internal flash.
- [ ] It stays in DFU for a minute without re-enumerating (WDI floats, so the
      TPS3828 is off; PB12's pull-down holds the relay off).
- [ ] Flash (see [`README.md`](README.md), "Flashing"):
      `leaf_gw_board.bin.signed` at `0x08004000`, `bootstub.bin` at
      `0x08000000:leave`.
- [ ] Optional: SWD connects (`openocd -f interface/stlink.cfg -f target/stm32f4x.cfg`),
      reads `0x463` as the device id.

## 4. Firmware up, no CAN traffic

12 V on, adapters connected but silent.

- [ ] Status LED blinks at 1 Hz (`WAIT`). Relay closed.
- [ ] V-CAN adapter (J1-16/18) sees `0x5FF` at 50 Hz, `4C 47 57 01 00 cc 00 ss`
      (status `00`: not inline). This also proves the clock: on the wrong
      crystal setting CAN would run at 250 kbit and nothing would decode.
- [ ] Current unchanged from step 2 (± the LED).

## 5. Transceivers and engage

Adapter A on the ADAS side (J1-9/11), adapter B on the car side (J1-8/7),
both sending: `cangen can0 -g 10 -I 100 -L 8` and `cangen can1 -g 10 -I 200 -L 8`.
Keep adapter C on V-CAN: it ACKs the heartbeat. With no ACKing node there,
the heartbeat queue overflows, and once engaged that counts as a fault.

- [ ] Within a second: relay **clicks**, status LED **solid**, current rises
      by the coil current.
- [ ] J1-9 ↔ J1-8 continuity is now **open** (meter; power stays on).
- [ ] Heartbeat status `01` (inline).
- [ ] A's frames arrive at B and B's at A, same id, DLC and data (`candump`
      both). Send a few with DLC < 8 and an extended id: they must arrive
      unchanged.
- [ ] `0x1C3` / `0x2B0` frames from A arrive unchanged while nothing sends
      openpilot commands on V-CAN (passthrough).

## 6. Faults release the relay

Do each from the engaged state; after each, the board must stay faulted
(LED 5 Hz, relay closed, no heartbeat) until power is cycled, even when the
fault goes away. Power-cycle to re-engage before the next one.

- [ ] Stop adapter B: within 250 ms the relay drops, J1-9 ↔ J1-8 continuous
      again, `0x5FF` stops.
- [ ] Stop adapter A: same.
- [ ] Short car-side CAN_H to CAN_L briefly (bus-off): same.
- [ ] Lower the supply to 7 V (below the 8 V ignition threshold; the buck
      still runs): same.

## 7. Reset and watchdog timeout release the relay

- [ ] Engaged, short the `NRST` pad to `GND`: the relay drops at once (NRST is
      the AND gate's input B); released, the board boots into `WAIT` and
      re-engages.

The TPS3828 must drop the relay on its own when the kicks stop. Halting the
core over SWD stops the main loop, and so the kicks; freeze the internal IWDG
first, or it resets the MCU after 50 ms and hides the external watchdog.

- [ ] Engaged (step 5), then
      `openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "reset_config none" -c init -c "mww 0xE0042008 0x1000" -c halt`
      (`DBGMCU_APB1_FZ.DBG_IWDG_STOP`). The relay must drop **0.9–2.5 s**
      after the halt (scope on RELAY_GATE, or meter continuity and a
      stopwatch); NRST pulses low for about 200 ms and the board reboots.
- [ ] Same without the `mww` (IWDG not frozen): the relay drops within about
      50 ms.
- [ ] With the board in `WAIT` (no traffic), halting doesn't reset it: WDI is
      floating, so the TPS3828 is off.

## 8. Done

- [ ] Temperature: after 10 minutes engaged, nothing hotter than warm.
- [ ] Record the board number, the currents and rail voltages, and any
      deviation, in the tracker before the board goes anywhere near a car.
