/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_engine.c -- see gw_engine.h. Pure, host-tested. */
#include "gw_engine.h"
#include <string.h>

void gw_init(gw_state *s, uint32_t timeout_ms) {
    memset(s, 0, sizeof(*s));
    s->timeout_ms = timeout_ms;
}

void gw_set_op(gw_state *s, uint32_t now_ms, bool engaged,
               bool brake_active, int pressure, bool accel_active, int command) {
    s->last_op_ms      = now_ms;
    s->engaged         = engaged;
    s->op_brake_active = brake_active;
    s->op_pressure     = pressure;
    s->op_accel_active = accel_active;
    s->op_command      = command;
}

gw_action gw_on_adas_frame(const gw_state *s, uint32_t now_ms,
                           uint32_t id, const uint8_t in[8], uint8_t out[8]) {
    memcpy(out, in, 8);                    /* default: pass through unchanged */
    if (id != LEAF_ID_BRAKE && id != LEAF_ID_ACCEL) return GW_FORWARD;

    leaf_mode_t m = leaf_mode(now_ms, s->last_op_ms, s->engaged, s->timeout_ms);
    if (m == LEAF_PASSTHROUGH) return GW_FORWARD;

    if (id == LEAF_ID_BRAKE) {
        if (!leaf_1c3_valid(in)) return GW_FORWARD;   /* don't touch a frame we can't trust */
        int stock_p = leaf_1c3_pressure(in);
        bool stock_a = leaf_1c3_active(in);
        int chosen = leaf_arb_pressure(m, s->op_pressure, s->op_brake_active, stock_p, stock_a);
        if (chosen == stock_p) return GW_FORWARD;     /* stock won (incl. AEB) -> untouched */
        uint8_t counter = in[5] & 0x03;               /* keep the ADAS rolling counter */
        leaf_1c3_encode(out, chosen, chosen > 0, chosen > 0, counter);
        return GW_SUBSTITUTE;
    }

    /* LEAF_ID_ACCEL */
    if (!leaf_2b0_valid(in)) return GW_FORWARD;
    int stock_c = leaf_2b0_command(in);
    bool stock_a = leaf_2b0_active(in);
    int chosen = leaf_arb_command(m, s->op_command, s->op_accel_active, stock_c, stock_a);
    if (chosen == stock_c) return GW_FORWARD;         /* stock won -> untouched */
    uint8_t counter = (in[6] >> 4) & 0x0F;            /* keep the ADAS rolling counter */
    leaf_2b0_encode(out, chosen, true, counter);
    out[3] = in[3];                                   /* keep the stock state field */
    out[4] = (uint8_t)(in[4] | 0x40u);
    return GW_SUBSTITUTE;
}
