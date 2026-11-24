/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_engine.h -- platform-agnostic gateway brain.
 *
 * Holds the gateway state and decides, for each frame arriving from the ADAS
 * side, what to emit toward the chassis side. Pure C, no hardware: a backend
 * feeds it frames and carries out its decisions. Host-tested.
 *
 * Substitution keeps the stock frame's rolling counter and only rewrites the
 * controlled fields + checksum (matches comma sdsu / Dala bridge practice), so
 * the injected stream stays lockstep with the ADAS unit's cadence.
 */
#ifndef GW_ENGINE_H
#define GW_ENGINE_H

#include "leaf_gw.h"

typedef struct {
    /* latest openpilot request (set by the backend when a command arrives) */
    uint32_t last_op_ms;
    bool     engaged;
    bool     op_brake_active;   /* openpilot wants friction braking      */
    int      op_pressure;       /* 0x1C3 pressure units                  */
    bool     op_accel_active;   /* openpilot is commanding propulsion     */
    int      op_command;        /* 0x2B0 raw_command                      */
    uint32_t timeout_ms;        /* stale-command fail-open threshold      */
} gw_state;

void gw_init(gw_state *s, uint32_t timeout_ms);

/* Called by the backend when openpilot sends a desired command. */
void gw_set_op(gw_state *s, uint32_t now_ms, bool engaged,
               bool brake_active, int pressure, bool accel_active, int command);

typedef enum { GW_FORWARD = 0, GW_SUBSTITUTE = 1 } gw_action;

/* Decide what to emit toward the chassis for a frame from the ADAS side.
 * `id` is the frame's CAN id, `in` its 8 bytes. On GW_FORWARD the frame is
 * passed through unchanged (out == in). On GW_SUBSTITUTE, out holds the frame
 * to send instead. Frames other than 0x1C3/0x2B0 always forward. */
gw_action gw_on_adas_frame(const gw_state *s, uint32_t now_ms,
                           uint32_t id, const uint8_t in[8], uint8_t out[8]);

#endif
