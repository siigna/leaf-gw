/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* leaf_gw.h -- pure decision core for the Leaf Chassis CAN longitudinal gateway.
 *
 * Hardware-independent. No CAN driver here. This is the logic the bench and the
 * test suite can prove: decode/encode of the two ADAS request frames, the
 * 0x1C3 checksum, magnitude arbitration (stock emergency braking always wins),
 * and the fail-open mode decision. The firmware forwarding loop and the
 * hardware normally-closed fail-open relay wrap this core; they are integration
 * code, untested, and live in backends/panda/.
 *
 * CONSTANTS ARE PROVISIONAL: the 0x2B0/0x1C3 layouts/scaling are StarPilot's,
 * validated on a 2025 Leaf SV Plus only. Confirm on a 2018-2023 ZE1 with
 * tools/leaf_iccan_check.py (blocker #1) before trusting the numbers.
 */
#ifndef LEAF_GW_H
#define LEAF_GW_H

#include <stdint.h>
#include <stdbool.h>

#define LEAF_ID_ACCEL 0x2B0u   /* propulsion/regen request, ADAS -> VCM      */
#define LEAF_ID_BRAKE 0x1C3u   /* friction-brake request, ADAS -> ABS unit   */

#define LEAF_ACCEL_ZERO   6144 /* raw_command at 0 m/s^2                     */
#define LEAF_ACCEL_SCALE  2048 /* raw_command counts per m/s^2              */

/* ---- 0x1C3 friction brake ---- */
uint8_t leaf_1c3_checksum(const uint8_t d[8]);      /* (0x01+0xC3+sum d[0..6]) & 0xFF */
bool    leaf_1c3_valid(const uint8_t d[8]);         /* structure + checksum ok   */
int     leaf_1c3_pressure(const uint8_t d[8]);      /* 10-bit, 0.5-count units   */
bool    leaf_1c3_active(const uint8_t d[8]);
void    leaf_1c3_encode(uint8_t d[8], int pressure, bool active, bool brake_mode, uint8_t counter);

/* ---- 0x2B0 propulsion/regen ---- */
bool    leaf_2b0_valid(const uint8_t d[8]);         /* inverse-copy + fixed bytes ok */
int     leaf_2b0_command(const uint8_t d[8]);       /* raw_command (0..8191)     */
bool    leaf_2b0_active(const uint8_t d[8]);
float   leaf_2b0_accel(const uint8_t d[8]);         /* m/s^2                     */
void    leaf_2b0_encode(uint8_t d[8], int command, bool active, uint8_t counter);

/* ---- gateway heartbeat ----
 * The gateway sends this on its V-CAN port at 50 Hz so openpilot can tell a
 * gateway is installed (fingerprint) and alive (panda rx check) before and while
 * it controls longitudinal. Bytes: 'L' 'G' 'W' version status counter 0 checksum,
 * checksum = (0xFF + sum d[0..6]) & 0xFF. */
#define LEAF_ID_HEARTBEAT   0x5FFu  /* unused on every bus in 37 Leafs' logs (commaCarSegments) */
#define LEAF_HB_VERSION     1u
#define LEAF_HB_PERIOD_MS   20u   /* 50 Hz: older forks fingerprint for only 0.1 s */
#define LEAF_HB_INLINE      0x01u   /* MCU is bridging Chassis CAN (relay engaged)    */
#define LEAF_HB_OP_ACTIVE   0x02u   /* gateway is substituting openpilot's command    */
void leaf_hb_encode(uint8_t d[8], uint8_t status, uint8_t counter);
bool leaf_hb_valid(const uint8_t d[8]);

/* ---- fail-open mode ---- */
typedef enum { LEAF_PASSTHROUGH = 0, LEAF_ACTIVE = 1 } leaf_mode_t;
/* ACTIVE only while engaged AND an openpilot command arrived within timeout_ms.
 * Any other case (disengaged, stale command, startup) -> PASSTHROUGH (stock). */
leaf_mode_t leaf_mode(uint32_t now_ms, uint32_t last_op_ms, bool engaged, uint32_t timeout_ms);

/* ---- magnitude arbitration ---- */
/* Brake pressure (0x1C3): higher = more braking. Stock always allowed to win. */
int  leaf_arb_pressure(leaf_mode_t m, int op_press, bool op_active, int stock_press, bool stock_active);
/* Accel (0x2B0): lower command = more braking / less accel. Stock braking wins. */
int  leaf_arb_command(leaf_mode_t m, int op_cmd, bool op_active, int stock_cmd, bool stock_active);

#endif
