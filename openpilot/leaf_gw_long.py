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
# openpilot->frame->gateway-decode contract is testable without the opendbc graph.
#
# 0x2B0 carries T = (b2 << 4) | (b1 & 0xF), with its inverted copy in b1_hi:b0.
# Higher T = more deceleration. The accel->T curve is the median of 37 stock Leafs'
# ICC logs (comma's commaCarSegments; acceleration from wheel speed) -- PROVISIONAL,
# it still needs an active bench / test-car check. Friction braking (0x1C3) keeps
# StarPilot's pressure gain, also unverified.

ACCEL_MIN = -3.5
ACCEL_BP = [-0.78, -0.45, -0.11, -0.04, 0.0, 0.05, 0.09, 0.59, 0.79]   # m/s^2
T_BP     = [2784, 2720, 2656, 2592, 2528, 2464, 2400, 2336, 2272]      # 0x2B0 T
PROPILOT_ACCEL_MIN = ACCEL_BP[0]    # below this, regen alone isn't enough: friction brake
ACCEL_MAX = PROPILOT_ACCEL_MAX = ACCEL_BP[-1]
T_MAX_ACCEL = T_BP[-1]              # lowest T openpilot sends (most acceleration)
PROPILOT_INACTIVE_RAW = 2595        # stock idle frame dc 53 a2 .. 1b .. 03
PROPILOT_BRAKE_RAW = 3415           # stock friction-brake marker a8 27 d5 .. 5b .. 09
BRAKE_MAX = 659
BRAKE_GAIN = 264.0
V_EGO_STOPPING = 0.5

LEAF_LONG_BUS = 2   # V-CAN segment the gateway taps (bench-verify)
LEAF_GW_HEARTBEAT = 0x5FF   # the gateway's 50 Hz "I'm installed and inline" frame on LEAF_LONG_BUS


def heartbeat_valid(d):
  """True for a well-formed leaf-gw heartbeat: 'LGW' version status counter 0 checksum."""
  return len(d) == 8 and bytes(d[:3]) == b"LGW" and d[3] == 1 and d[6] == 0 and d[7] == (0xFF + sum(d[:7])) & 0xFF


def _clip(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


def _interp(x, xp, fp):
  if x <= xp[0]:
    return fp[0]
  for i in range(1, len(xp)):
    if x <= xp[i]:
      return fp[i - 1] + (fp[i] - fp[i - 1]) * (x - xp[i - 1]) / (xp[i] - xp[i - 1])
  return fp[-1]


def gateway_longitudinal(accel, long_active, stopping, v_ego, v_ego_stopping=V_EGO_STOPPING):
  """Map desired accel (m/s^2) to (T, pressure, active, brake_mode)."""
  accel = float(_clip(accel, ACCEL_MIN, ACCEL_MAX))
  brake_mode = long_active and (accel < PROPILOT_ACCEL_MIN or stopping)
  if long_active:
    command = PROPILOT_BRAKE_RAW if brake_mode else round(_interp(accel, ACCEL_BP, T_BP))
  else:
    command = PROPILOT_INACTIVE_RAW
  pressure = round(max(0.0, PROPILOT_ACCEL_MIN - accel) * BRAKE_GAIN) if brake_mode else 0
  if stopping and v_ego < v_ego_stopping:
    pressure = BRAKE_MAX
  pressure = int(_clip(pressure, 0, BRAKE_MAX))
  return command, pressure, bool(long_active), bool(brake_mode)


def pack_accel(command, frame, active):
  """Build the real 0x2B0 propulsion/regen frame (8 bytes) for T = command."""
  t = int(_clip(int(command), 0, 4095))
  inverse = (~t) & 0xFFF
  aux = 2 if t == PROPILOT_BRAKE_RAW else 0   # stock pairs the marker with aux 2
  return bytes([
    inverse & 0xFF,
    (((inverse >> 8) & 0xF) << 4) | (t & 0xF),
    (t >> 4) & 0xFF,
    0xAC,
    0x5B if active else 0x1B,
    0x00,
    ((frame & 0xF) << 4) | 0xE,
    (aux << 2) | ((~aux) & 0x3),
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
