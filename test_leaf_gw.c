/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* test_leaf_gw.c -- host unit tests for the gateway decision core.
 * Build + run:  make test   (or: cc -Wall -Wextra leaf_gw.c test_leaf_gw.c -o t && ./t)
 *
 * Golden CAN payloads are from StarPilot's opendbc test vectors (2025 Leaf SV
 * Plus). They prove our decode/encode/checksum logic is self-consistent and
 * matches that fork. They do NOT prove the layout is right for a 2018-2023 ZE1 --
 * that is blocker #1, confirmed separately with tools/leaf_iccan_check.py.
 */
#include "leaf_gw.h"
#include "gw_engine.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

static int fails = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)
#define EQ(a,b)  do { long _a=(long)(a),_b=(long)(b); if (_a!=_b){printf("FAIL %s:%d  %s=%ld != %s=%ld\n",__FILE__,__LINE__,#a,_a,#b,_b); fails++; } } while (0)
static int feq(float a, float b) { return fabsf(a - b) < 0.002f; }

/* StarPilot golden vectors */
static const uint8_t IDLE_1C3[8] = {0x00,0x00,0x00,0x00,0x64,0x00,0xFF,0x27};
static const uint8_t A_2B0[8]    = {0xff,0x60,0x90,0xac,0x5b,0x00,0x0e,0x03}; /* cmd 6144, accel 0 */
static const uint8_t B_2B0[8]    = {0x00,0x7f,0x8f,0xac,0x5b,0x00,0x0e,0x0c}; /* cmd 8191, ~+1 */
static const uint8_t C_2B0[8]    = {0xa8,0x27,0xd5,0xac,0x5b,0x00,0x0e,0x09}; /* cmd 2398: stock friction-brake marker */

static void test_1c3(void) {
    CHECK(leaf_1c3_valid(IDLE_1C3));
    EQ(leaf_1c3_checksum(IDLE_1C3), 0x27);
    EQ(leaf_1c3_pressure(IDLE_1C3), 0);
    CHECK(!leaf_1c3_active(IDLE_1C3));

    /* encode idle must reproduce the golden frame */
    uint8_t d[8];
    leaf_1c3_encode(d, 0, false, false, 0);
    CHECK(memcmp(d, IDLE_1C3, 8) == 0);

    /* round-trip arbitrary values */
    for (int p = 0; p <= 1023; p += 37) {
        leaf_1c3_encode(d, p, true, true, 2);
        CHECK(leaf_1c3_valid(d));
        EQ(leaf_1c3_pressure(d), p);
        CHECK(leaf_1c3_active(d));
        EQ(d[5] & 0x03, 2);               /* counter preserved */
        CHECK((d[5] & 0x04) != 0);        /* brake_mode preserved */
    }
    /* a corrupted checksum must fail validation */
    leaf_1c3_encode(d, 100, true, false, 0); d[7] ^= 0xFF;
    CHECK(!leaf_1c3_valid(d));
}

static void test_2b0(void) {
    CHECK(leaf_2b0_valid(A_2B0)); EQ(leaf_2b0_command(A_2B0), 6144); CHECK(leaf_2b0_active(A_2B0)); CHECK(feq(leaf_2b0_accel(A_2B0), 0.0f));
    CHECK(leaf_2b0_valid(B_2B0)); EQ(leaf_2b0_command(B_2B0), 8191); CHECK(feq(leaf_2b0_accel(B_2B0), (8191-6144)/2048.0f));
    CHECK(leaf_2b0_valid(C_2B0)); EQ(leaf_2b0_command(C_2B0), 2398); CHECK(feq(leaf_2b0_accel(C_2B0), (2398-6144)/2048.0f));

    uint8_t d[8];
    leaf_2b0_encode(d, 6144, true, 0); CHECK(memcmp(d, A_2B0, 8) == 0);
    leaf_2b0_encode(d, 8191, true, 0); CHECK(memcmp(d, B_2B0, 8) == 0);
    leaf_2b0_encode(d, 2398, true, 0); CHECK(memcmp(d, C_2B0, 8) == 0);
    /* consecutive frames from a stock ZE1 log (public route): +1 count apart */
    static const uint8_t R1[8] = {0xf0,0x5f,0xa0,0xac,0x5b,0x00,0x0e,0x09};
    static const uint8_t R2[8] = {0xef,0x50,0xa1,0xac,0x5b,0x00,0x1e,0x06};
    CHECK(leaf_2b0_valid(R1)); CHECK(leaf_2b0_valid(R2));
    EQ(leaf_2b0_command(R1), 0x50F * 4 + 2); EQ(leaf_2b0_command(R2), 0x510 * 4 + 1);

    for (int c = 0; c <= 8191; c += 257) {
        leaf_2b0_encode(d, c, true, 0);
        CHECK(leaf_2b0_valid(d));
        EQ(leaf_2b0_command(d), c);
        CHECK(leaf_2b0_active(d));
    }
}

static void test_heartbeat(void) {
    uint8_t d[8];
    static const uint8_t HB[8] = {'L','G','W',1,0x03,0x05,0x00,0xF2};  /* 0xFF+0x4C+0x47+0x57+1+3+5 */
    leaf_hb_encode(d, LEAF_HB_INLINE | LEAF_HB_OP_ACTIVE, 0x15);       /* counter is 4-bit */
    CHECK(memcmp(d, HB, 8) == 0); CHECK(leaf_hb_valid(d));
    d[4] ^= 0x02; CHECK(!leaf_hb_valid(d));
}

static void test_mode(void) {
    EQ(leaf_mode(1000, 990, true, 50), LEAF_ACTIVE);       /* fresh command */
    EQ(leaf_mode(1000, 940, true, 50), LEAF_PASSTHROUGH);  /* stale > 50ms */
    EQ(leaf_mode(1000, 990, false, 50), LEAF_PASSTHROUGH); /* disengaged */
    EQ(leaf_mode(1000, 1000, true, 50), LEAF_ACTIVE);      /* zero age */
}

static void test_arbitration(void) {
    /* passthrough: always the stock value, ignore op */
    EQ(leaf_arb_pressure(LEAF_PASSTHROUGH, 500, true, 0, false), 0);
    EQ(leaf_arb_command(LEAF_PASSTHROUGH, 7000, true, 6144, false), 6144);

    /* engaged, stock idle: op gets its way (accel and comfort brake) */
    EQ(leaf_arb_command(LEAF_ACTIVE, 7000, true, LEAF_ACCEL_ZERO, false), 7000);  /* op accel */
    EQ(leaf_arb_command(LEAF_ACTIVE, 4000, true, LEAF_ACCEL_ZERO, false), 4000);  /* op brake */
    EQ(leaf_arb_pressure(LEAF_ACTIVE, 50, true, 0, false), 50);

    /* engaged, stock emergency braking HARDER than op: stock always wins */
    EQ(leaf_arb_command(LEAF_ACTIVE, 6144, false, 2398, true), 2398);            /* AEB vs neutral op */
    EQ(leaf_arb_command(LEAF_ACTIVE, 4000, true, 3000, true), 3000);            /* stock brakes harder */
    EQ(leaf_arb_pressure(LEAF_ACTIVE, 50, true, 300, true), 300);              /* AEB pressure wins */

    /* engaged, op brakes harder than a mild stock request: op wins */
    EQ(leaf_arb_command(LEAF_ACTIVE, 3000, true, 5000, true), 3000);
    EQ(leaf_arb_pressure(LEAF_ACTIVE, 300, true, 50, true), 300);

    /* engaged, stock active but at NEUTRAL (6144) must not block op accel */
    EQ(leaf_arb_command(LEAF_ACTIVE, 7000, true, LEAF_ACCEL_ZERO, true), 7000);
}

static void test_engine(void) {
    gw_state s;
    uint8_t out[8];

    /* disengaged -> brake frame forwarded untouched */
    gw_init(&s, 50);
    gw_set_op(&s, 1000, false, false, 0, false, 0);
    CHECK(gw_on_adas_frame(&s, 1000, LEAF_ID_BRAKE, IDLE_1C3, out) == GW_FORWARD);
    CHECK(memcmp(out, IDLE_1C3, 8) == 0);

    /* engaged, op wants comfort braking, stock idle -> substitute op pressure */
    gw_init(&s, 50);
    gw_set_op(&s, 1000, true, true, 200, false, 0);
    CHECK(gw_on_adas_frame(&s, 1000, LEAF_ID_BRAKE, IDLE_1C3, out) == GW_SUBSTITUTE);
    CHECK(leaf_1c3_valid(out));
    EQ(leaf_1c3_pressure(out), 200);
    EQ(out[5] & 0x03, IDLE_1C3[5] & 0x03);     /* stock counter preserved */

    /* engaged, stock AEB (high pressure) beats mild op -> forward stock untouched */
    uint8_t aeb[8];
    leaf_1c3_encode(aeb, 600, true, true, 1);
    gw_init(&s, 50);
    gw_set_op(&s, 1000, true, true, 50, false, 0);
    CHECK(gw_on_adas_frame(&s, 1000, LEAF_ID_BRAKE, aeb, out) == GW_FORWARD);
    CHECK(memcmp(out, aeb, 8) == 0);           /* AEB passes through intact */

    /* engaged but command gone stale -> fail open (forward stock) */
    gw_init(&s, 50);
    gw_set_op(&s, 1000, true, true, 200, false, 0);
    CHECK(gw_on_adas_frame(&s, 1100, LEAF_ID_BRAKE, IDLE_1C3, out) == GW_FORWARD);

    /* engaged, op accel, stock 2B0 neutral -> substitute op command */
    gw_init(&s, 50);
    gw_set_op(&s, 1000, true, false, 0, true, 7000);
    CHECK(gw_on_adas_frame(&s, 1000, LEAF_ID_ACCEL, A_2B0, out) == GW_SUBSTITUTE);
    CHECK(leaf_2b0_valid(out));
    EQ(leaf_2b0_command(out), 7000);

    /* a non-controlled frame always forwards, even engaged */
    uint8_t other[8] = {1,2,3,4,5,6,7,8};
    gw_init(&s, 50);
    gw_set_op(&s, 1000, true, true, 200, true, 7000);
    CHECK(gw_on_adas_frame(&s, 1000, 0x355, other, out) == GW_FORWARD);
    CHECK(memcmp(out, other, 8) == 0);
}

int main(void) {
    test_1c3();
    test_2b0();
    test_heartbeat();
    test_mode();
    test_arbitration();
    test_engine();
    if (fails) { printf("\n%d test(s) FAILED\n", fails); return 1; }
    printf("all tests passed\n");
    return 0;
}
