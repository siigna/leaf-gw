/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
/* gw_panda.c -- comma-panda / RetroPilot Ocelot firmware entry for the Leaf
 * Chassis CAN gateway (STM32F413 Ocelot Pro, 3x TJA1042).
 *
 * !!! UNTESTED, BENCH-ONLY. Validate the 0x2B0/0x1C3 layouts on a real ZE1
 * (tracker issue #5) and prove the external fail-open relay reverts to stock on
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
 * Fail-open: the Ocelot has NO onboard relay. An EXTERNAL normally-closed relay
 * on the Chassis CAN cut (driven from RELAY_GPIO below) must connect ADAS<->chassis
 * directly when de-energized (reset/brown-out/IWDG trip). See ../../HARDWARE.md.
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
static int  op_command = LEAF_ACCEL_ZERO;
static int  op_pressure = 0;
static bool op_engaged = false;
static bool op_brake = false;

/* External NC fail-open relay drive. CONFIRM the pin for your Ocelot wiring
 * (broken-out H4/H5 GPIO or an IGN_OUT-gated FET). High = energized = MCU in
 * circuit (Chassis CAN cut, gateway bridges); low/reset = relay closed = stock. */
#define RELAY_PORT GPIOB
#define RELAY_PIN  12U

static gw_state S;

static inline uint32_t now_ms(void) { return TIM2->CNT / 1000U; } /* TIM2 = 1us */

static void relay_engage(bool mcu_in_circuit) {
  set_gpio_output(RELAY_PORT, RELAY_PIN, mcu_in_circuit);
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

/* ADAS side (CAN1): run the gateway, emit toward the chassis (CAN2, bus 1). */
void CAN1_RX0_IRQ_Handler(void) {
  while ((CAN1->RF0R & CAN_RF0R_FMP0) != 0) {
    CAN_FIFOMailBox_TypeDef *mb = &CAN1->sFIFOMailBox[0];
    uint32_t addr = GET_ADDR(mb);
    uint8_t in[8], out[8];
    copy_bytes(mb, in);
    gw_on_adas_frame(&S, now_ms(), addr, in, out);  /* FORWARD or SUBSTITUTE */
    send_std(addr, out, 1);
    CAN1->RF0R |= CAN_RF0R_RFOM0;
  }
}

/* Chassis side (CAN2): pass straight back to ADAS (CAN1, bus 0). */
void CAN2_RX0_IRQ_Handler(void) {
  while ((CAN2->RF0R & CAN_RF0R_FMP0) != 0) {
    CAN_FIFOMailBox_TypeDef *mb = &CAN2->sFIFOMailBox[0];
    uint8_t d[8];
    copy_bytes(mb, d);
    send_std(GET_ADDR(mb), d, 0);
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
void CAN1_SCE_IRQ_Handler(void) { can_sce(CAN1); }
void CAN2_SCE_IRQ_Handler(void) { can_sce(CAN2); }
void CAN3_SCE_IRQ_Handler(void) { can_sce(CAN3); }

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

  clock_init();
  peripherals_init();
  detect_configuration();
  detect_board_type();

  /* 1 MHz free-running microsecond counter (48 MHz / 48). */
  TIM2->PSC = 48U - 1U;
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

  set_gpio_mode(RELAY_PORT, RELAY_PIN, MODE_OUTPUT);
  set_gpio_output_type(RELAY_PORT, RELAY_PIN, OUTPUT_TYPE_PUSH_PULL);

  gw_init(&S, OP_TIMEOUT_MS);
  relay_engage(true);   /* MCU now bridges Chassis CAN; reset de-energizes -> stock */

  watchdog_init();
  enable_interrupts();

  while (1) {
    watchdog_feed();    /* a stalled loop -> IWDG reset -> relay opens -> stock */
  }
  return 0;
}
