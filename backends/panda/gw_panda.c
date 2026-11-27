/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_panda.c -- comma-panda / RetroPilot Ocelot firmware entry for the Leaf
 * Chassis CAN gateway. Two boards, picked at build time:
 *   Ocelot Pro (STM32F413, 3x TJA1042)       scons project leaf_gw
 *   the leaf-gw board (hardware/board)        scons project leaf_gw_board
 *                                             (-DLEAF_GW_BOARD, boards/leaf_gw.h)
 *
 * !!! UNTESTED ON HARDWARE, BENCH-ONLY. Validate the 0x2B0/0x1C3 layouts on a
 * real ZE1 (tracker issue #5) and prove the fail-open relay reverts to stock on
 * reset/power-loss before this touches a car anyone drives. !!!
 *
 * Shape follows the RetroPilot ocelot `smart_dsu` MITM reference (comma panda,
 * MIT): bare-metal, interrupt-driven. Unlike the FreeRTOS backends this does
 * use a blocking HAL seam -- it calls the pure, host-tested core
 * (leaf_gw.c, gw_engine.c) directly from the CAN RX interrupts, which is how
 * panda-class firmware forwards frames.
 *
 * Bus map (Ocelot H1): CAN1 = ADAS side (bus 0), CAN2 = chassis side (bus 1),
 *                      CAN3 = V-CAN tap: reads openpilot's real 0x2B0/0x1C3.
 *
 * Fail-open: a normally-closed relay on the Chassis CAN cut joins ADAS<->chassis
 * when de-energized (reset/brown-out/IWDG trip). On the leaf-gw board it is
 * onboard and also gated by a TPS3828 watchdog; the Ocelot has none, so wire an
 * external one to PB12 (see ../../HARDWARE.md). gw_supervisor.c sequences it:
 * transceivers -> relay -> forwarding; on a fault, forwarding off -> relay off.
 */
#include "../config.h"
#include "libc.h"

#include "main_declarations.h"
#include "critical.h"
#include "faults.h"

#include "drivers/registers.h"
#include "drivers/interrupts.h"
#include "drivers/llcan.h"
#include "drivers/llgpio.h"
#include "drivers/adc.h"

#include "board.h"

#include "drivers/clock.h"
#include "drivers/timer.h"

#include "gpio.h"
#include "crc.h"

/* Project-local CUT-DOWN CAN driver (no GMLAN/USB bulk), as every RetroPilot
 * pedal-like core ships one. Copy smart_dsu/can.h into this project dir as
 * can.h -- see README. It must come after board.h (board typedef, CAN_MODE_*)
 * and provides can_send/process_can/can_sce/can_init_all.
 *
 * That can.h assumes a USB-attached panda: process_can() resumes the USB OUT
 * endpoint after draining the TX queue. This gateway is headless/inline, so
 * stub those two USB hooks to no-ops. To build a USB panda instead (Cabana,
 * USB control link), define TGW_USB and include drivers/uart.h + drivers/usb.h
 * here, and provide the usb_cb_* callbacks (see smart_dsu/main.c). */
#ifndef TGW_USB
#define MAX_CAN_MSGS_PER_BULK_TRANSFER 0x100U
static void usb_outep3_resume_if_paused(void) { }
#endif
#include "can.h"

#include "gw_engine.h"
#include "gw_supervisor.h"
#ifdef LEAF_GW_BOARD
  #include "boards/leaf_gw.h"
#endif

/* Headless: no serial console. The board/harness headers log through these;
 * stub them to no-ops. (drivers/uart.h defines the real ones -- include it
 * under TGW_USB if you want debug output.) */
#ifndef TGW_USB
void puts(const char *a) { (void)a; }
void puth(unsigned int i) { (void)i; }
void puth2(unsigned int i) { (void)i; }
#endif

/* --- configuration ------------------------------------------------------- */
#define OP_TIMEOUT_MS 50U     /* fail-open if no command within this window    */

/* openpilot's desired request. It arrives on CAN3 (the V-CAN tap) as the REAL
 * Leaf ADAS frames 0x2B0 (propulsion/regen) and 0x1C3 (friction brake) -- the
 * same formats the stock ADAS unit uses -- so the gateway just decodes them and
 * feeds gw_set_op. The engine re-stamps the stock rolling counter + checksum
 * when it substitutes onto Chassis CAN, so openpilot's own counter here is ignored. */
static int  op_command = LEAF_2B0_IDLE;
static int  op_pressure = 0;
static bool op_engaged = false;
static bool op_brake = false;

static gw_state S;
static sup_t SUP;

/* Set by the main loop (sup_hw_forward), read by the RX interrupts. Main never
 * preempts an ISR, so once it writes false no new chassis frame is queued. */
static volatile bool fwd_on = false;
/* RX liveness and bus-off, written by the ISRs, read by the supervisor. */
static volatile uint32_t adas_rx_cnt = 0U;
static volatile uint32_t car_rx_cnt = 0U;
static volatile bool bus_off_seen = false;

static inline uint32_t now_ms(void) { return TIM2->CNT; } /* TIM2 = 1 kHz, wraps at 2^32 ms */

/* ---- supervisor hardware seam ---- */
void sup_hw_forward(bool on) {
  static bool was_on = false;
  fwd_on = on;
  if (was_on && !on) {
    /* drop chassis frames still queued, so none goes out after the relay rejoins the bus */
    can_clear(&can_tx1_q);
    can_clear(&can_tx2_q);
    llcan_clear_send(CAN1);
    llcan_clear_send(CAN2);
  }
  was_on = on;
}

void sup_hw_xcvr(bool on) {
  for (uint8_t i = 1U; i <= 3U; i++) {
    current_board->enable_can_transceiver(i, on);
  }
}

void sup_hw_led(bool on) { current_board->set_led(LED_GREEN, on); }

#ifdef LEAF_GW_BOARD
void sup_hw_relay(bool on) { leaf_gw_relay(on); }
void sup_hw_kick(bool level) { leaf_gw_kick(level); }
void sup_hw_kick_release(void) { leaf_gw_kick_release(); }
static bool ign_ok(void) { return leaf_gw_check_ignition(); }
#else
/* Ocelot: external relay on PB12 (CONFIRM for your wiring: H4/H5 GPIO or an
 * IGN_OUT-gated FET). No external watchdog, no ignition sense (PA1 is IGN_OUT
 * there, an output). */
void sup_hw_relay(bool on) { set_gpio_output(GPIOB, 12, on); }
void sup_hw_kick(bool level) { UNUSED(level); }
void sup_hw_kick_release(void) { }
static bool ign_ok(void) { return true; }
#endif

/* Copy a received frame (id, IDE/RTR, DLC, data) into a TX mailbox. */
static void rx_to_tx(const CAN_FIFOMailBox_TypeDef *mb, CAN_FIFOMailBox_TypeDef *m) {
  m->RIR = (mb->RIR & 0xFFFFFFFEU) | 1U;   /* same id/IDE/RTR, TXRQ */
  m->RDTR = mb->RDTR & 0xFU;              /* DLC */
  m->RDLR = mb->RDLR;
  m->RDHR = mb->RDHR;
}

/* Build a standard-id TX mailbox from id + 8 bytes and send it on a bus. */
static void send_std(uint32_t id, const uint8_t d[8], uint8_t bus) {
  CAN_FIFOMailBox_TypeDef m;
  m.RDLR = d[0] | (d[1] << 8) | (d[2] << 16) | ((uint32_t)d[3] << 24);
  m.RDHR = d[4] | (d[5] << 8) | (d[6] << 16) | ((uint32_t)d[7] << 24);
  m.RDTR = 8U;
  m.RIR = (id << 21) | 1U;   /* std id, TXRQ */
  can_send(&m, bus, false);
}

static void copy_bytes(const CAN_FIFOMailBox_TypeDef *mb, uint8_t out[8]) {
  for (int i = 0; i < 8; i++) out[i] = GET_BYTE(mb, i);
}

/* ADAS side (CAN1): run the gateway, emit toward the chassis (CAN2, bus 1).
 * Frames are always drained and counted (liveness), forwarded only while the
 * supervisor has the relay engaged. */
void CAN1_RX0_IRQ_Handler(void) {
  while ((CAN1->RF0R & CAN_RF0R_FMP0) != 0) {
    CAN_FIFOMailBox_TypeDef *mb = &CAN1->sFIFOMailBox[0];
    adas_rx_cnt++;
    if (fwd_on) {
      CAN_FIFOMailBox_TypeDef m;
      rx_to_tx(mb, &m);
      if (((mb->RIR & 4U) == 0U) && (GET_LEN(mb) == 8U)) {   /* std, 8 bytes: may substitute */
        uint8_t in[8], out[8];
        copy_bytes(mb, in);
        if (gw_on_adas_frame(&S, now_ms(), GET_ADDR(mb), in, out) == GW_SUBSTITUTE) {
          m.RDLR = out[0] | (out[1] << 8) | (out[2] << 16) | ((uint32_t)out[3] << 24);
          m.RDHR = out[4] | (out[5] << 8) | (out[6] << 16) | ((uint32_t)out[7] << 24);
        }
      }
      can_send(&m, 1, false);
    }
    CAN1->RF0R |= CAN_RF0R_RFOM0;
  }
}

/* Chassis side (CAN2): pass straight back to ADAS (CAN1, bus 0). */
void CAN2_RX0_IRQ_Handler(void) {
  while ((CAN2->RF0R & CAN_RF0R_FMP0) != 0) {
    car_rx_cnt++;
    if (fwd_on) {
      CAN_FIFOMailBox_TypeDef m;
      rx_to_tx(&CAN2->sFIFOMailBox[0], &m);
      can_send(&m, 0, false);
    }
    CAN2->RF0R |= CAN_RF0R_RFOM0;
  }
}

/* V-CAN tap (CAN3): openpilot's real 0x2B0 / 0x1C3. Decode and feed gw_set_op;
 * never forwarded. Invalid frames (bad checksum/inverse-copy) are ignored. */
void CAN3_RX0_IRQ_Handler(void) {
  while ((CAN3->RF0R & CAN_RF0R_FMP0) != 0) {
    CAN_FIFOMailBox_TypeDef *mb = &CAN3->sFIFOMailBox[0];
    uint32_t addr = GET_ADDR(mb);
    uint8_t d[8]; copy_bytes(mb, d);
    bool upd = false;
    if ((addr == 0x2B0U) && leaf_2b0_valid(d)) {
      op_command = leaf_2b0_command(d);
      op_engaged = leaf_2b0_active(d);
      upd = true;
    } else if ((addr == 0x1C3U) && leaf_1c3_valid(d)) {
      op_pressure = leaf_1c3_pressure(d);
      op_brake = leaf_1c3_active(d);
      upd = true;
    }
    if (upd) {
      gw_set_op(&S, now_ms(), op_engaged, op_brake, op_pressure, op_engaged, op_command);
    }
    CAN3->RF0R |= CAN_RF0R_RFOM0;
  }
}

/* TX + bus-error plumbing the can.h driver expects, one set per bus. */
void CAN1_TX_IRQ_Handler(void) { process_can(0); }
void CAN2_TX_IRQ_Handler(void) { process_can(1); }
void CAN3_TX_IRQ_Handler(void) { process_can(2); }
/* Bus-off is latched here: ABOM recovers the controller on its own after
 * 128 x 11 recessive bits, which a main-loop poll of ESR could miss. */
static void sce(CAN_TypeDef *c) {
  if ((c->ESR & CAN_ESR_BOFF) != 0U) { bus_off_seen = true; }
  can_sce(c);
}
void CAN1_SCE_IRQ_Handler(void) { sce(CAN1); }
void CAN2_SCE_IRQ_Handler(void) { sce(CAN2); }
void CAN3_SCE_IRQ_Handler(void) { sce(CAN3); }

void __initialize_hardware_early(void) { early(); }

int main(void) {
  disable_interrupts();

  init_interrupts(true);
  REGISTER_INTERRUPT(CAN1_TX_IRQn,  CAN1_TX_IRQ_Handler,  CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_1)
  REGISTER_INTERRUPT(CAN1_RX0_IRQn, CAN1_RX0_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_1)
  REGISTER_INTERRUPT(CAN1_SCE_IRQn, CAN1_SCE_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_1)
  REGISTER_INTERRUPT(CAN2_TX_IRQn,  CAN2_TX_IRQ_Handler,  CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_2)
  REGISTER_INTERRUPT(CAN2_RX0_IRQn, CAN2_RX0_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_2)
  REGISTER_INTERRUPT(CAN2_SCE_IRQn, CAN2_SCE_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_2)
  REGISTER_INTERRUPT(CAN3_TX_IRQn,  CAN3_TX_IRQ_Handler,  CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_3)
  REGISTER_INTERRUPT(CAN3_RX0_IRQn, CAN3_RX0_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_3)
  REGISTER_INTERRUPT(CAN3_SCE_IRQn, CAN3_SCE_IRQ_Handler, CAN_INTERRUPT_RATE, FAULT_INTERRUPT_RATE_CAN_3)

#ifdef LEAF_GW_BOARD
  leaf_gw_clock_init();
#else
  clock_init();
#endif
  peripherals_init();
  detect_configuration();
  detect_board_type();
#ifdef LEAF_GW_BOARD
  current_board = &board_leaf_gw;
#endif

  /* 1 kHz free-running millisecond counter (48 MHz APB1 timer clock / 48000),
   * so now_ms() wraps at 2^32 ms like the unsigned differences expect. */
  TIM2->PSC = 48000U - 1U;
  TIM2->CR1 = TIM_CR1_CEN;
  TIM2->EGR = TIM_EGR_UG;

  current_board->init();

  /* Chassis CAN is 500 kbit. llcan speed is in 0.1 kbit units (5000 = 500k). */
  llcan_set_speed(CAN1, 5000, false, false);
  llcan_set_speed(CAN2, 5000, false, false);
  llcan_set_speed(CAN3, 5000, false, false);
  llcan_init(CAN1);
  llcan_init(CAN2);
  llcan_init(CAN3);
  /* bus-off interrupts, latched in sce() (llcan_init enables TX/RX only) */
  register_set_bits(&(CAN1->IER), CAN_IER_ERRIE | CAN_IER_BOFIE);
  register_set_bits(&(CAN2->IER), CAN_IER_ERRIE | CAN_IER_BOFIE);
  register_set_bits(&(CAN3->IER), CAN_IER_ERRIE | CAN_IER_BOFIE);

  gw_init(&S, OP_TIMEOUT_MS);
  sup_init(&SUP, now_ms());   /* transceivers up; relay stays off (stock) */

  watchdog_init();
  enable_interrupts();

  uint32_t hb_last = now_ms();
  uint8_t hb_counter = 0;
  while (1) {
    /* a stalled loop -> IWDG reset (and, once engaged, no WDI kick -> TPS3828
     * reset); either pulls NRST, which drops the relay -> stock */
    watchdog_feed();
    uint32_t now = now_ms();

    /* The external watchdog is kicked only inside sup_step, here: not from an
     * ISR, which could keep running while this loop or forwarding is dead. */
    sup_in in;
    ENTER_CRITICAL();
    in.bus_off = bus_off_seen ||
                 ((CAN1->ESR & CAN_ESR_BOFF) != 0U) ||
                 ((CAN2->ESR & CAN_ESR_BOFF) != 0U) ||
                 ((CAN3->ESR & CAN_ESR_BOFF) != 0U);
    bus_off_seen = false;
    in.adas_rx = adas_rx_cnt;
    in.car_rx = car_rx_cnt;
    in.fwd_errs = can_fwd_errs;
    EXIT_CRITICAL();
    in.ign = ign_ok();
    sup_step(&SUP, now, &in);

    if (sup_heartbeat(&SUP) && ((uint32_t)(now - hb_last) >= LEAF_HB_PERIOD_MS)) {
      /* heartbeat on the V-CAN tap: openpilot only offers / keeps longitudinal
       * while it hears us; silent once faulted, so its rx check drops controls */
      uint8_t hb[8];
      uint8_t status = sup_inline(&SUP) ? LEAF_HB_INLINE : 0U;
      if (sup_inline(&SUP) && (leaf_mode(now, S.last_op_ms, S.engaged, S.timeout_ms) == LEAF_ACTIVE)) {
        status |= LEAF_HB_OP_ACTIVE;
      }
      leaf_hb_encode(hb, status, hb_counter++);
      send_std(LEAF_ID_HEARTBEAT, hb, 2);
      hb_last = now;
    }
  }
  return 0;
}
