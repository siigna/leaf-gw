/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* leaf_gw.c -- pure decision core for the Leaf Chassis CAN longitudinal gateway.
 * See leaf_gw.h. Hardware-independent; unit-tested in test_leaf_gw.c.
 */
#include "leaf_gw.h"

/* ---------- 0x1C3 friction brake ---------- */

uint8_t leaf_1c3_checksum(const uint8_t d[8]) {
    unsigned s = 0x01u + 0xC3u;
    for (int i = 0; i < 7; i++) s += d[i];
    return (uint8_t)(s & 0xFFu);
}

int leaf_1c3_pressure(const uint8_t d[8]) {
    return ((d[0] & 0x3F) << 4) | (d[1] >> 4);
}

bool leaf_1c3_active(const uint8_t d[8]) {
    return (d[5] & 0x80u) != 0;
}

bool leaf_1c3_valid(const uint8_t d[8]) {
    if ((d[0] & 0xC0u) != 0) return false;
    if ((d[1] & 0x0Fu) != 0) return false;
    if (d[2] != 0 || d[3] != 0) return false;
    if (d[4] != 0x64u) return false;
    if ((d[5] & 0x78u) != 0) return false;   /* only 0x80|0x04|0x03 are defined */
    if (d[6] != 0xFFu) return false;
    return d[7] == leaf_1c3_checksum(d);
}

void leaf_1c3_encode(uint8_t d[8], int pressure, bool active, bool brake_mode, uint8_t counter) {
    if (pressure < 0) pressure = 0;
    if (pressure > 1023) pressure = 1023;
    d[0] = (uint8_t)((pressure >> 4) & 0x3F);
    d[1] = (uint8_t)((pressure & 0x0F) << 4);
    d[2] = 0;
    d[3] = 0;
    d[4] = 0x64;
    d[5] = (uint8_t)((active ? 0x80u : 0u) | (brake_mode ? 0x04u : 0u) | (counter & 0x03u));
    d[6] = 0xFF;
    d[7] = leaf_1c3_checksum(d);
}

/* ---------- 0x2B0 propulsion/regen ---------- */

static int b2b0_raw(const uint8_t d[8]) {
    return (d[1] << 4) | (d[2] & 0x0F);
}
static int b2b0_frac(const uint8_t d[8]) {
    return (d[7] >> 2) & 0x03;
}

int leaf_2b0_command(const uint8_t d[8]) {
    return b2b0_raw(d) * 4 + b2b0_frac(d);
}

bool leaf_2b0_active(const uint8_t d[8]) {
    return (d[4] & 0x40u) != 0;
}

float leaf_2b0_accel(const uint8_t d[8]) {
    return (float)(leaf_2b0_command(d) - LEAF_ACCEL_ZERO) / (float)LEAF_ACCEL_SCALE;
}

bool leaf_2b0_valid(const uint8_t d[8]) {
    int raw = b2b0_raw(d);
    int inverse = ((d[2] >> 4) << 8) | ((d[0] & 0x0F) << 4) | (d[0] >> 4);
    if (inverse != ((~raw) & 0xFFF)) return false;
    int frac = b2b0_frac(d);
    if (d[7] != (uint8_t)(((frac << 2) | ((~frac) & 0x3)) & 0xFF)) return false;
    if (d[3] != 0xAC) return false;
    if ((d[4] & 0xBFu) != 0x1Bu) return false;   /* active bit 0x40 masked off -> 0x1B */
    if (d[5] != 0) return false;
    if ((d[6] & 0x0Fu) != 0x0Eu) return false;
    return true;
}

void leaf_2b0_encode(uint8_t d[8], int command, bool active, uint8_t counter) {
    if (command < 0) command = 0;
    if (command > 8191) command = 8191;
    int raw = command >> 2;
    int frac = command & 0x03;
    int inverse = (~raw) & 0xFFF;
    d[1] = (uint8_t)((raw >> 4) & 0xFF);
    d[2] = (uint8_t)((((inverse >> 8) & 0x0F) << 4) | (raw & 0x0F));
    uint8_t y = (uint8_t)(inverse & 0xFF);
    d[0] = (uint8_t)(((y & 0x0F) << 4) | (y >> 4));   /* nibble swap */
    d[3] = 0xAC;
    d[4] = active ? 0x5B : 0x1B;
    d[5] = 0;
    d[6] = (uint8_t)(0x0E | ((counter & 0x0F) << 4));
    d[7] = (uint8_t)(((frac << 2) | ((~frac) & 0x3)) & 0xFF);
}

/* ---------- fail-open mode ---------- */

leaf_mode_t leaf_mode(uint32_t now_ms, uint32_t last_op_ms, bool engaged, uint32_t timeout_ms) {
    if (!engaged) return LEAF_PASSTHROUGH;
    if ((uint32_t)(now_ms - last_op_ms) > timeout_ms) return LEAF_PASSTHROUGH;
    return LEAF_ACTIVE;
}

/* ---------- magnitude arbitration ---------- *
 * Stock emergency braking must always get through. The gateway never silences
 * the ADAS unit, so the stock request is live on the bus; we forward whichever
 * commands more braking, and yield to a stronger stock request.
 */

int leaf_arb_pressure(leaf_mode_t m, int op_press, bool op_active, int stock_press, bool stock_active) {
    if (m == LEAF_PASSTHROUGH) return stock_press;
    int op = op_active ? op_press : 0;
    /* higher pressure = more braking; stock wins when it asks for more */
    if (stock_active && stock_press > op) return stock_press;
    return op;
}

int leaf_arb_command(leaf_mode_t m, int op_cmd, bool op_active, int stock_cmd, bool stock_active) {
    if (m == LEAF_PASSTHROUGH) return stock_cmd;
    int op = op_active ? op_cmd : LEAF_ACCEL_ZERO;   /* inactive op = neutral */
    /* Stock wins only when it is actually braking (command below neutral) AND
     * braking harder than op. A stock frame merely sitting at neutral must not
     * block op's acceleration. Lower command = more deceleration. */
    if (stock_active && stock_cmd < LEAF_ACCEL_ZERO && stock_cmd < op) return stock_cmd;
    return op;
}
