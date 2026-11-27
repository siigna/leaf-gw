/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md. */
// ////////// //
//  leaf_gw   //
// ////////// //
/* Board definition for the leaf-gw board (hardware/board), in the style of the
 * RetroPilot tree's boards/gateway.h. Built in as firmware/boards/leaf_gw.h and
 * selected with -DLEAF_GW_BOARD (scons project `leaf_gw_board`); the Ocelot
 * build (`leaf_gw`) keeps board_gateway. Needs gateway.h (same CAN pins).
 *
 * Pin map, from hardware/board/out/leaf_gw.net (net names in caps):
 *   PB8/PB9  CAN1_RX/CAN1_TX  -> U2, Chassis CAN ADAS side
 *   PB5/PB6  CAN2_RX/CAN2_TX  -> U3, Chassis CAN car side
 *   PA8/PA15 CAN3_RX/CAN3_TX  -> U4, V-CAN tap
 *   PC1/PC13/PA0 CAN1_STB/CAN2_STB/CAN3_STB (high = standby; TJA1042 pull-up)
 *   PA1  IGN_SENSE  VIN_PROT through 100k/33k, ADC1_IN1
 *   PB12 RELAY_EN   AND gate input A (100k pull-down)
 *   PC6  WDT_KICK   TPS3828 WDI (floating = watchdog disabled)
 *   PC7  LED_STATUS high = on
 *   PA11/PA12 USB_DM/USB_DP (unused: the image is headless)
 *   PH0/PH1 HSE_IN/HSE_OUT, 8 MHz (the Ocelot has 16 MHz: own clock init below)
 */

#define LEAF_GW_ADC_IGN 1U   /* PA1 = ADC1_IN1 */

/* The tree's clock_init() is written for the Ocelot's 16 MHz crystal (M 8,
 * N 96); on our 8 MHz crystal it gives 48 MHz SYSCLK, 12 MHz APB1 (CAN at
 * half the bit rate) and 24 MHz USB. N 192 restores the Ocelot's clocks:
 * 8 / 8 * 192 = 192 MHz VCO, /2 = 96 MHz SYSCLK, /4 = 48 MHz USB, APB1 24 MHz
 * (llcan's CAN_PCLK), APB1 timers 48 MHz (TIM2 prescaler in main). The
 * bootstub has already run clock_init(), so leave the PLL before changing it. */
void leaf_gw_clock_init(void) {
  register_set_bits(&(RCC->CR), RCC_CR_HSEON);
  while ((RCC->CR & RCC_CR_HSERDY) == 0U) {}
  register_set(&(RCC->CFGR), RCC_CFGR_SW_HSE, RCC_CFGR_SW);
  while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_HSE) {}
  register_clear_bits(&(RCC->CR), RCC_CR_PLLON);
  while ((RCC->CR & RCC_CR_PLLRDY) != 0U) {}

  register_set(&(RCC->CFGR), RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE2_DIV2 | RCC_CFGR_PPRE1_DIV4, 0xFF7FFCF0U);
  register_set(&(RCC->PLLCFGR), RCC_PLLCFGR_PLLQ_2 | RCC_PLLCFGR_PLLM_3 | RCC_PLLCFGR_PLLN_7 | RCC_PLLCFGR_PLLN_6 | RCC_PLLCFGR_PLLSRC_HSE, 0x7F437FFFU);
  register_set_bits(&(RCC->CR), RCC_CR_PLLON);
  while ((RCC->CR & RCC_CR_PLLRDY) == 0U) {}

  register_set(&(FLASH->ACR), FLASH_ACR_ICEN | FLASH_ACR_DCEN | FLASH_ACR_LATENCY_5WS, 0x1F0FU);
  register_set(&(RCC->CFGR), RCC_CFGR_SW_PLL, RCC_CFGR_SW);
  while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) {}
}

void leaf_gw_set_led(uint8_t color, bool enabled) {
  UNUSED(color);
  set_gpio_output(GPIOC, 7, enabled);
}

void leaf_gw_relay(bool energize) {
  set_gpio_output(GPIOB, 12, energize);
}

/* Driving WDI starts the TPS3828's timer; floating it (input, no pull) stops it. */
void leaf_gw_kick(bool level) {
  set_gpio_output(GPIOC, 6, level);
}

void leaf_gw_kick_release(void) {
  set_gpio_mode(GPIOC, 6, MODE_INPUT);
}

uint32_t leaf_gw_ign_raw(void) {
  return adc_get(LEAF_GW_ADC_IGN);
}

bool leaf_gw_check_ignition(void) {
  return sup_ign_mv(leaf_gw_ign_raw()) >= SUP_IGN_MIN_MV;
}

void leaf_gw_init(void) {
  common_init_gpio();

  /* safe states first: relay off, WDI floating, LED off */
  leaf_gw_relay(false);
  leaf_gw_kick_release();   /* early() already cleared PUPDR: no pull */
  leaf_gw_set_led(0U, false);

  set_gpio_mode(GPIOA, 1, MODE_ANALOG);
  adc_init();

  /* transceivers stay in standby until the supervisor brings them up */
  for (uint8_t i = 1U; i <= 3U; i++) {
    gateway_enable_can_transceiver(i, false);
  }
  gateway_set_can_mode(CAN_MODE_NORMAL);
}

const board board_leaf_gw = {
  .board_type = "LeafGW",
  .harness_config = &gateway_harness_config,
  .init = leaf_gw_init,
  .enable_can_transceiver = gateway_enable_can_transceiver,
  .enable_can_transceivers = gateway_enable_can_transceivers,
  .set_led = leaf_gw_set_led,
  .set_usb_power_mode = gateway_set_usb_power_mode,
  .set_gps_mode = gateway_set_gps_mode,
  .set_can_mode = gateway_set_can_mode,
  .usb_power_mode_tick = gateway_usb_power_mode_tick,
  .check_ignition = leaf_gw_check_ignition,
  .read_current = gateway_read_current,
  .set_fan_power = gateway_set_fan_power,
  .set_ir_power = gateway_set_ir_power,
  .set_phone_power = gateway_set_phone_power,
  .set_clock_source_mode = gateway_set_clock_source_mode,
  .set_siren = gateway_set_siren
};
