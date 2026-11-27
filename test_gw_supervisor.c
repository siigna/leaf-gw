/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* test_gw_supervisor.c -- host tests for the bring-up / fail-open supervisor.
 * Build + run: make test. tools/mutate_supervisor.py proves each test bites.
 *
 * The fake hardware logs every output EDGE as one character, so ordering is a
 * string compare:  T/t xcvr on/off, R/r relay on/off, F/f forward on/off,
 * K kick edge (WDI driven), X WDI released.
 */
#include "gw_supervisor.h"
#include <stdio.h>
#include <string.h>

static int fails = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)
#define EQ(a,b)  do { long _a=(long)(a),_b=(long)(b); if (_a!=_b){printf("FAIL %s:%d  %s=%ld != %s=%ld\n",__FILE__,__LINE__,#a,_a,#b,_b); fails++; } } while (0)

/* ---- fake hardware ---- */
static char log_[4096];
static size_t nlog;
static bool hw_x, hw_f, hw_r, hw_armed;
static uint32_t now_g, t_relay_on, t_fwd_on, t_xcvr_on, last_kick, max_kick_gap, kicks;
static bool kick_lvl_ok, last_lvl;

static void put(char c) { if (nlog + 1u < sizeof log_) { log_[nlog++] = c; log_[nlog] = 0; } }
void sup_hw_xcvr(bool on)    { if (on != hw_x) { hw_x = on; put(on ? 'T' : 't'); if (on) t_xcvr_on = now_g; } }
void sup_hw_forward(bool on) { if (on != hw_f) { hw_f = on; put(on ? 'F' : 'f'); if (on) t_fwd_on = now_g; } }
void sup_hw_relay(bool on)   { if (on != hw_r) { hw_r = on; put(on ? 'R' : 'r'); if (on) t_relay_on = now_g; } }
void sup_hw_kick(bool level) {
    if (hw_armed) {
        uint32_t gap = now_g - last_kick;
        if (gap > max_kick_gap) max_kick_gap = gap;
        if (level == last_lvl) kick_lvl_ok = false;   /* TPS3828 needs an edge */
    }
    hw_armed = true; last_kick = now_g; last_lvl = level; kicks++;
    put('K');
}
void sup_hw_kick_release(void) { hw_armed = false; put('X'); }
void sup_hw_led(bool on) { (void)on; }

static sup_t S;
static sup_in in;

static void reset(uint32_t t0) {
    nlog = 0; log_[0] = 0;
    hw_x = hw_f = hw_r = hw_armed = false;
    max_kick_gap = 0; kicks = 0; kick_lvl_ok = true; last_lvl = false;
    t_relay_on = t_fwd_on = t_xcvr_on = 0;
    now_g = t0;
    memset(&in, 0, sizeof in);
    in.ign = true;
    sup_init(&S, now_g);
}

/* advance in 1 ms main-loop steps; a healthy bus moves both RX counters every step */
static void run(uint32_t ms, bool traffic) {
    for (uint32_t i = 0; i < ms; i++) {
        now_g++;
        if (traffic) { in.adas_rx++; in.car_rx++; }
        sup_step(&S, now_g, &in);
        in.bus_off = false;   /* the backend reports bus-off per step */
    }
}

/* log with kick edges dropped: the order of the other outputs */
static const char *order(void) {
    static char o[sizeof log_];
    size_t j = 0;
    for (size_t i = 0; i < nlog; i++) if (log_[i] != 'K') o[j++] = log_[i];
    o[j] = 0;
    return o;
}

static void engage(void) {
    reset(1000);
    run(200, true);
    EQ(S.st, SUP_ENGAGED);
}

static void test_bringup_order(void) {
    reset(1000);
    CHECK(strcmp(log_, "T") == 0);               /* transceivers first, nothing else */
    run(200, true);
    EQ(S.st, SUP_ENGAGED);
    CHECK(strncmp(log_, "TKR", 3) == 0);         /* xcvr, watchdog armed, then relay */
    CHECK(strcmp(order(), "TRF") == 0);          /* ... and only then forwarding     */
    CHECK(t_relay_on - t_xcvr_on >= SUP_XCVR_SETTLE_MS);
    CHECK(t_fwd_on - t_relay_on >= SUP_RELAY_SETTLE_MS);
    CHECK(sup_inline(&S) && sup_heartbeat(&S));
}

static void test_no_engage_unhealthy(void) {
    /* ignition low (or USB-only power): wait forever, relay never energizes */
    reset(1000); in.ign = false; run(2000, true);
    EQ(S.st, SUP_WAIT); CHECK(strchr(log_, 'R') == NULL); CHECK(kicks == 0);
    CHECK(sup_heartbeat(&S) && !sup_inline(&S));

    /* no traffic at all (RX counters never move) */
    reset(1000); run(2000, false);
    EQ(S.st, SUP_WAIT); CHECK(strchr(log_, 'R') == NULL);

    /* ADAS side silent, car side alive */
    reset(1000);
    for (int i = 0; i < 2000; i++) { now_g++; in.car_rx++; sup_step(&S, now_g, &in); }
    EQ(S.st, SUP_WAIT); CHECK(strchr(log_, 'R') == NULL);

    /* car side silent, ADAS side alive */
    reset(1000);
    for (int i = 0; i < 2000; i++) { now_g++; in.adas_rx++; sup_step(&S, now_g, &in); }
    EQ(S.st, SUP_WAIT); CHECK(strchr(log_, 'R') == NULL);

    /* bus-off every step */
    reset(1000);
    for (int i = 0; i < 2000; i++) { now_g++; in.adas_rx++; in.car_rx++; in.bus_off = true; sup_step(&S, now_g, &in); }
    EQ(S.st, SUP_WAIT); CHECK(strchr(log_, 'R') == NULL);

    /* not before the transceivers settled, even with traffic at once */
    reset(1000); run(SUP_XCVR_SETTLE_MS - 1u, true);
    EQ(S.st, SUP_WAIT); CHECK(!hw_r);

    /* heartbeat-queue overflow while waiting is not a fault */
    reset(1000); in.fwd_errs = 5; run(200, true);
    EQ(S.st, SUP_ENGAGED);
}

/* each fault from ENGAGED: stop forwarding, then relay, then disarm, then xcvr off */
static void check_fault(uint8_t bit, const char *what) {
    printf("  fault: %s\n", what);
    CHECK(S.st == SUP_FAULT);
    CHECK((S.fault & bit) != 0u);
    const char *o = order();
    CHECK(strcmp(o, "TRFfrXt") == 0);
    CHECK(!hw_f && !hw_r && !hw_armed && !hw_x);
    CHECK(!sup_heartbeat(&S) && !sup_inline(&S));
    /* latched: health back for 10 s, still stock, no kicks */
    uint32_t k = kicks;
    in.ign = true; run(10000, true);
    CHECK(S.st == SUP_FAULT && !hw_r && !hw_f && kicks == k);
}

static void test_faults(void) {
    engage(); in.ign = false; run(1, true);        check_fault(SUP_F_IGN, "ignition low");
    engage(); in.bus_off = true; sup_step(&S, ++now_g, &in); in.bus_off = false;
                                                   check_fault(SUP_F_BUSOFF, "bus-off");
    engage(); in.fwd_errs++; run(1, true);         check_fault(SUP_F_FWD, "TX queue overflow");

    /* ADAS side stops (CAN1 RX ISR dead, or the ADAS unit off): fault within the window */
    engage();
    uint32_t t0 = now_g;
    for (int i = 0; i < 1000 && S.st != SUP_FAULT; i++) { now_g++; in.car_rx++; sup_step(&S, now_g, &in); }
    CHECK(now_g - t0 <= SUP_RX_STALE_MS + 1u);
    check_fault(SUP_F_STALL, "ADAS-side RX stall");

    engage();
    t0 = now_g;
    for (int i = 0; i < 1000 && S.st != SUP_FAULT; i++) { now_g++; in.adas_rx++; sup_step(&S, now_g, &in); }
    CHECK(now_g - t0 <= SUP_RX_STALE_MS + 1u);
    check_fault(SUP_F_STALL, "car-side RX stall");

    /* a fault while the relay settles: forwarding never started */
    reset(1000);
    while (S.st != SUP_ENGAGING) run(1, true);
    in.ign = false; run(1, true);
    CHECK(S.st == SUP_FAULT);
    CHECK(strcmp(order(), "TRrXt") == 0);
}

static void test_kick_cadence(void) {
    /* 1 ms loop: an edge at least every SUP_KICK_MS, alternating level */
    engage(); run(10000, true);
    EQ(S.st, SUP_ENGAGED);
    CHECK(max_kick_gap <= SUP_KICK_MS);
    CHECK(max_kick_gap < 900u);                  /* TPS3828-33 minimum timeout */
    CHECK(kick_lvl_ok);
    CHECK(kicks >= 10000u / SUP_KICK_MS);

    /* a slow 37 ms loop still kicks within one loop period of the deadline */
    engage();
    max_kick_gap = 0;
    for (int i = 0; i < 300; i++) { now_g += 37; in.adas_rx++; in.car_rx++; sup_step(&S, now_g, &in); }
    EQ(S.st, SUP_ENGAGED);
    CHECK(max_kick_gap <= SUP_KICK_MS + 37u);

    /* no kicks before the relay is engaged: WDI stays floating (watchdog off) */
    reset(1000); in.ign = false; run(5000, true);
    CHECK(kicks == 0 && !hw_armed);
}

static void test_wrap(void) {
    /* ms counter wraps (49.7 days): no false stall, keeps kicking */
    reset(0xFFFFFF00u);
    run(200, true);
    EQ(S.st, SUP_ENGAGED);
    max_kick_gap = 0;
    run(1000, true);                             /* crosses 0 */
    EQ(S.st, SUP_ENGAGED);
    CHECK(max_kick_gap <= SUP_KICK_MS);
}

static void test_ign_mv(void) {
    /* 12 V at VIN_PROT -> 12 * 33/133 = 2.977 V at PA1 -> 3694 counts */
    uint32_t mv = sup_ign_mv(3694u);
    CHECK(mv > 11950u && mv < 12050u);
    CHECK(sup_ign_mv(0u) == 0u);
    CHECK(sup_ign_mv(4095u) == 13300u);          /* full scale, no overflow */
    /* threshold: 8 V reads 2463 counts */
    CHECK(sup_ign_mv(2470u) >= SUP_IGN_MIN_MV);
    CHECK(sup_ign_mv(2455u) < SUP_IGN_MIN_MV);
}

int main(void) {
    test_bringup_order();
    test_no_engage_unhealthy();
    test_faults();
    test_kick_cadence();
    test_wrap();
    test_ign_mv();
    if (fails) { printf("\n%d test(s) FAILED\n", fails); return 1; }
    printf("all supervisor tests passed\n");
    return 0;
}
