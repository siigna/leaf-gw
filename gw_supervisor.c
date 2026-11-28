/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_supervisor.c -- see gw_supervisor.h. Pure, host-tested. */
#include "gw_supervisor.h"

static void enter(sup_t *s, sup_state_t st, uint32_t now_ms) {
    s->st = st;
    s->t_state = now_ms;
}

/* A counter that moved since the last step proves its RX path is alive. */
static void track(uint32_t cnt, uint32_t now_ms, uint32_t *last, uint32_t *t, bool *seen) {
    if (cnt != *last) {
        *last = cnt;
        *t = now_ms;
        *seen = true;
    }
}

static bool fresh(bool seen, uint32_t t, uint32_t now_ms) {
    return seen && ((uint32_t)(now_ms - t) <= SUP_RX_STALE_MS);
}

static uint8_t faults(const sup_t *s, uint32_t now_ms, const sup_in *in) {
    uint8_t f = 0u;
    if (!in->ign) { f |= SUP_F_IGN; }
    if (in->bus_off) { f |= SUP_F_BUSOFF; }
    if (!fresh(s->adas_seen, s->t_adas, now_ms) || !fresh(s->car_seen, s->t_car, now_ms)) {
        f |= SUP_F_STALL;
    }
    if (in->fwd_errs != s->fwd_errs) { f |= SUP_F_FWD; }
    return f;
}

/* Outputs, re-asserted every step in a fixed order. Forwarding is switched
 * first, so on a fault it stops before the relay drops; it only turns on in a
 * later step than the relay (ENGAGING -> ENGAGED), so engage order holds too.
 * The watchdog is armed before the relay energizes and disarmed after it drops. */
static void apply(sup_t *s, uint32_t now_ms) {
    bool relay = (s->st == SUP_ENGAGING) || (s->st == SUP_ENGAGED);
    sup_hw_forward(s->st == SUP_ENGAGED);
    if (relay) {
        if (!s->kick_armed || ((uint32_t)(now_ms - s->t_kick) >= SUP_KICK_MS)) {
            s->kick_armed = true;
            s->kick_level = !s->kick_level;
            s->t_kick = now_ms;
            sup_hw_kick(s->kick_level);
        }
        sup_hw_relay(true);
    } else {
        sup_hw_relay(false);
        if (s->kick_armed) {
            s->kick_armed = false;
            sup_hw_kick_release();
        }
    }
    sup_hw_xcvr(s->st != SUP_FAULT);
    /* LED: blink 1 Hz waiting, solid engaged, blink 5 Hz faulted */
    if (relay) {
        sup_hw_led(true);
    } else {
        uint32_t half = (s->st == SUP_FAULT) ? 100u : 500u;
        sup_hw_led(((now_ms / half) & 1u) != 0u);
    }
}

void sup_init(sup_t *s, uint32_t now_ms) {
    s->st = SUP_WAIT;
    s->fault = 0u;
    s->t_state = now_ms;
    s->adas_rx = 0u;
    s->car_rx = 0u;
    s->fwd_errs = 0u;
    s->t_adas = now_ms;
    s->t_car = now_ms;
    s->adas_seen = false;
    s->car_seen = false;
    s->kick_armed = false;
    s->kick_level = false;
    s->t_kick = now_ms;
    apply(s, now_ms);
}

void sup_step(sup_t *s, uint32_t now_ms, const sup_in *in) {
    track(in->adas_rx, now_ms, &s->adas_rx, &s->t_adas, &s->adas_seen);
    track(in->car_rx, now_ms, &s->car_rx, &s->t_car, &s->car_seen);
    uint8_t f = faults(s, now_ms, in);
    switch (s->st) {
        case SUP_WAIT:
            /* nothing forwards yet, so queue errors (heartbeat) aren't a fault here */
            s->fwd_errs = in->fwd_errs;
            f &= (uint8_t)~SUP_F_FWD;
            if ((f == 0u) && ((uint32_t)(now_ms - s->t_state) >= SUP_XCVR_SETTLE_MS)) {
                enter(s, SUP_ENGAGING, now_ms);
            }
            break;
        case SUP_ENGAGING:
        case SUP_ENGAGED:
            if (f != 0u) {
                s->fault = f;
                enter(s, SUP_FAULT, now_ms);
            } else if ((s->st == SUP_ENGAGING) &&
                       ((uint32_t)(now_ms - s->t_state) >= SUP_RELAY_SETTLE_MS)) {
                enter(s, SUP_ENGAGED, now_ms);
            } else {
                /* healthy, no transition */
            }
            break;
        default:
            break;   /* SUP_FAULT: latched until power-cycle */
    }
    apply(s, now_ms);
}

bool sup_heartbeat(const sup_t *s) { return s->st != SUP_FAULT; }
bool sup_inline(const sup_t *s) { return s->st == SUP_ENGAGED; }

uint32_t sup_ign_mv(uint32_t adc_raw) {
    /* pin mV = raw * 3300 / 4095; VIN_PROT = pin * (100k + 22k) / 22k */
    return (adc_raw * 3300u * 122u) / (4095u * 22u);
}
