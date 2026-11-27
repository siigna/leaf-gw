/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_supervisor.h -- bring-up / fail-open relay supervisor for the gateway.
 *
 * Pure C, host-tested (test_gw_supervisor.c). It owns the order the board
 * SPEC ("Fail-open relay", "Firmware order") requires:
 *   bring up the transceivers -> energize the relay -> start forwarding;
 *   on any fault: stop forwarding -> release the relay.
 * and the external watchdog (TPS3828) kick, which it only toggles from
 * sup_step(), i.e. from the main loop, and only while every health input is
 * good. A stalled main loop never calls sup_step (no kick -> the watchdog pulls
 * NRST, which also drops the relay through the AND gate); a stalled forwarding
 * path stops the RX counters and trips SUP_F_STALL here.
 *
 * Faults latch until power-cycle (IGN off/on): one fault puts the car on the
 * stock path for the rest of the drive instead of retrying on a flaky bus.
 *
 * The backend implements the sup_hw_* seam; the test records the calls.
 */
#ifndef GW_SUPERVISOR_H
#define GW_SUPERVISOR_H

#include <stdint.h>
#include <stdbool.h>

#define SUP_XCVR_SETTLE_MS   10u   /* TJA1042 standby -> normal is ~50 us; margin  */
#define SUP_RELAY_SETTLE_MS  10u   /* G6K-2F-Y operate time <= 3 ms; margin        */
#define SUP_RX_STALE_MS     250u   /* a side silent this long = stalled or dead    */
#define SUP_KICK_MS         100u   /* WDI edge period; TPS3828-33 timeout >= 0.9 s  */
#define SUP_IGN_MIN_MV     8000u   /* VIN_PROT below this = ignition off / USB only */

typedef enum {
    SUP_WAIT = 0,      /* transceivers up, relay off (stock), waiting for health */
    SUP_ENGAGING = 1,  /* relay energized, settling; not forwarding yet          */
    SUP_ENGAGED = 2,   /* relay energized and forwarding                         */
    SUP_FAULT = 3      /* latched: not forwarding, relay off, watchdog disarmed  */
} sup_state_t;

/* latched fault reasons (sup_t.fault) */
#define SUP_F_IGN    0x01u  /* ignition sense low                              */
#define SUP_F_BUSOFF 0x02u  /* a CAN controller went bus-off                   */
#define SUP_F_STALL  0x04u  /* ADAS- or car-side RX stopped (ISR or bus dead)  */
#define SUP_F_FWD    0x08u  /* a forwarding TX queue overflowed (frames lost)  */

typedef struct {
    bool     ign;          /* ignition sense above SUP_IGN_MIN_MV               */
    bool     bus_off;      /* any controller bus-off since the last step        */
    uint32_t adas_rx;      /* frames received on CAN1 (ADAS side), free-running */
    uint32_t car_rx;       /* frames received on CAN2 (car side), free-running  */
    uint32_t fwd_errs;     /* TX queue overflow count, free-running             */
} sup_in;

typedef struct {
    sup_state_t st;
    uint8_t  fault;
    uint32_t t_state;      /* when st was entered                     */
    uint32_t adas_rx;      /* last seen counter values ...            */
    uint32_t car_rx;
    uint32_t fwd_errs;
    uint32_t t_adas;       /* ... and when they last changed          */
    uint32_t t_car;
    bool     adas_seen;
    bool     car_seen;
    bool     kick_armed;   /* WDI driven                              */
    bool     kick_level;
    uint32_t t_kick;       /* last WDI edge                           */
} sup_t;

/* hardware seam, called only from sup_init / sup_step */
void sup_hw_xcvr(bool on);       /* all three transceivers out of standby     */
void sup_hw_forward(bool on);    /* off also flushes queued chassis TX frames */
void sup_hw_relay(bool on);      /* RELAY_EN                                  */
void sup_hw_kick(bool level);    /* drive WDI (arms the external watchdog)    */
void sup_hw_kick_release(void);  /* float WDI (disarms it)                    */
void sup_hw_led(bool on);

void sup_init(sup_t *s, uint32_t now_ms);
void sup_step(sup_t *s, uint32_t now_ms, const sup_in *in);

/* Heartbeat on V-CAN: sent unless faulted, so openpilot's rx check drops
 * controls within ~1 s of a fault. INLINE bit only while forwarding. */
bool sup_heartbeat(const sup_t *s);
bool sup_inline(const sup_t *s);

/* PA1 ADC count (12 bit, 3.3 V ref) -> VIN_PROT in mV, through the
 * schematic's 100k / 33k divider (power.py). */
uint32_t sup_ign_mv(uint32_t adc_raw);

#endif
