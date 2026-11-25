# Nissan Leaf (ZE1) openpilot longitudinal — the accel→frame spec, dependency-free.
#
# Path B: openpilot emits the REAL Leaf ADAS frames (0x2B0 propulsion/regen,
# 0x1C3 friction brake) on the leaf-gw gateway's control bus (V-CAN). It does NOT
# silence the stock ADAS ECU, so stock AEB stays live; the inline gateway
# (github.com/siigna/leaf-gw) re-emits these onto Chassis CAN and yields to a stronger
# stock request (magnitude arbitration).
#
# This module mirrors what the opendbc patch puts in car/nissan (the mapping in
# carcontroller + the packers in nissancan). It is kept dependency-free so the
# openpilot→frame→gateway-decode contract is testable without the opendbc graph.
# The accel→(command, pressure) calibration is StarPilot's (2025 SV Plus).

ACCEL_MIN = -3.5
ACCEL_MAX = 2047 / 2048
PROPILOT_ACCEL_MIN = -1.0
PROPILOT_ACCEL_MAX = ACCEL_MAX
PROPILOT_ACCEL_OFFSET = 6144
PROPILOT_ACCEL_SCALE = 2048
PROPILOT_INACTIVE_RAW = 5260   # stock idle frame dc53a2ac1b00.e03
PROPILOT_BRAKE_RAW = 2398      # stock friction-brake marker a827d5ac5b00.e09
BRAKE_MAX = 659
BRAKE_GAIN = 264.0
V_EGO_STOPPING = 0.5

LEAF_LONG_BUS = 2   # V-CAN segment the gateway taps (bench-verify)
LEAF_GW_HEARTBEAT = 0x5FF   # the gateway's 10 Hz "I'm installed and inline" frame on LEAF_LONG_BUS


def heartbeat_valid(d):
  """True for a well-formed leaf-gw heartbeat: 'LGW' version status counter 0 checksum."""
  return len(d) == 8 and bytes(d[:3]) == b"LGW" and d[3] == 1 and d[6] == 0 and d[7] == (0xFF + sum(d[:7])) & 0xFF


def _clip(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


def gateway_longitudinal(accel, long_active, stopping, v_ego, v_ego_stopping=V_EGO_STOPPING):
  """Map desired accel (m/s^2) to (raw_command, pressure, active, brake_mode)."""
  accel = float(_clip(accel, ACCEL_MIN, ACCEL_MAX))
  brake_mode = long_active and (accel < PROPILOT_ACCEL_MIN or stopping)
  if long_active:
    if brake_mode:
      command = PROPILOT_BRAKE_RAW
    else:
      propulsion = _clip(accel, PROPILOT_ACCEL_MIN, PROPILOT_ACCEL_MAX)
      command = round(propulsion * PROPILOT_ACCEL_SCALE + PROPILOT_ACCEL_OFFSET)
  else:
    command = PROPILOT_INACTIVE_RAW
  pressure = round(max(0.0, -accel - 1.0) * BRAKE_GAIN) if brake_mode else 0
  if stopping and v_ego < v_ego_stopping:
    pressure = BRAKE_MAX
  pressure = int(_clip(pressure, 0, BRAKE_MAX))
  return command, pressure, bool(long_active), bool(brake_mode)


def pack_accel(raw_command, frame, active):
  """Build the real 0x2B0 propulsion/regen frame (8 bytes)."""
  raw_command = int(raw_command)
  # value nibbles: b1 = V_hi:V_lo, b2 = I_hi:V_mid, b0 = I (I = ~V), per stock ZE1 logs
  raw12, fraction = divmod(raw_command, 4)
  inverse = (~raw12) & 0xFFF
  return bytes([
    inverse & 0xFF,
    (((raw12 >> 8) & 0xF) << 4) | (raw12 & 0xF),
    (((inverse >> 8) & 0xF) << 4) | ((raw12 >> 4) & 0xF),
    0xAC,
    0x5B if active else 0x1B,
    0x00,
    ((frame & 0xF) << 4) | 0xE,
    (fraction << 2) | ((~fraction) & 0x3),
  ])


def pack_brake(pressure, frame, active, brake_mode):
  """Build the real 0x1C3 friction-brake frame (8 bytes)."""
  pressure = int(pressure)
  d = bytearray(8)
  d[0] = (pressure >> 4) & 0x3F
  d[1] = (pressure & 0xF) << 4
  d[4] = 0x64
  d[5] = (0x80 if active else 0) | (0x04 if brake_mode else 0) | (frame & 0x3)
  d[6] = 0xFF
  d[7] = (0x01 + 0xC3 + sum(d[:7])) & 0xFF
  return bytes(d)
