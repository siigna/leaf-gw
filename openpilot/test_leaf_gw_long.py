#!/usr/bin/env python3
# Dependency-free test of the openpilot -> frame -> gateway-decode contract.
# Decoders below mirror leaf_gw.c (leaf_2b0_*/leaf_1c3_*) exactly, so a pass
# proves the frames openpilot packs are what the gateway will accept and read.
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import leaf_gw_long as L


# ---- decoders mirroring the firmware core (leaf_gw.c) ----
def dec_2b0(d):
  assert (d[4] & 0xBF) == 0x1B, "0x2B0 ownership/active byte"
  assert (d[3] & 0x1F) == 0x0C and d[5] == 0 and (d[6] & 0x0F) == 0x0E, "0x2B0 fixed bytes"
  t = (d[2] << 4) | (d[1] & 0x0F)
  aux = (d[7] >> 2) & 0x03
  assert (((d[1] >> 4) << 8) | d[0]) == ((~t) & 0xFFF), "0x2B0 inverse copy"
  assert d[7] == (((aux << 2) | ((~aux) & 0x3)) & 0xFF), "0x2B0 aux check"
  return t, bool(d[4] & 0x40)


def dec_1c3(d):
  assert d[7] == ((0x01 + 0xC3 + sum(d[:7])) & 0xFF), "0x1C3 checksum"
  assert d[4] == 0x64 and d[6] == 0xFF, "0x1C3 fixed bytes"
  pressure = ((d[0] & 0x3F) << 4) | (d[1] >> 4)
  active = bool(d[5] & 0x80)
  return pressure, active


def sweep():
  import numpy as np
  VES = 0.5
  for accel in np.arange(-4.0, 1.1, 0.25):
    for la in (True, False):
      for stop in (True, False):
        for v in (0.1, 5.0):
          yield float(accel), la, stop, v, VES


def main():
  # mapping sanity: 0 m/s^2 -> T at the fit's zero, monotonic (more accel = lower T)
  assert L.gateway_longitudinal(0.0, True, False, 10.0)[0] == 2528
  assert L.gateway_longitudinal(0.0, False, False, 10.0)[0] == L.PROPILOT_INACTIVE_RAW
  assert L.gateway_longitudinal(-2.0, True, False, 10.0)[0] == L.PROPILOT_BRAKE_RAW
  assert L.gateway_longitudinal(-9.0, True, False, 10.0)[1] == L.BRAKE_MAX  # clamp
  ts = [L.gateway_longitudinal(a / 100, True, False, 10.0)[0] for a in range(-78, 80)]
  assert all(x >= y for x, y in zip(ts, ts[1:])) and ts[-1] == L.T_MAX_ACCEL

  # stock frames (golden): idle, brake marker, a cruise frame
  assert L.pack_accel(L.PROPILOT_INACTIVE_RAW, 0, False).hex() == "dc53a2ac1b000e03"
  assert L.pack_accel(L.PROPILOT_BRAKE_RAW, 0, True).hex() == "a827d5ac5b000e09"
  assert L.pack_accel(2304, 0, True).hex() == "ff6090ac5b000e03"
  # consecutive stock frames across the 0x900 boundary are 3 counts apart (SHIOKAZE)
  assert dec_2b0(bytes.fromhex("fd6290ac5b005e03"))[0] - dec_2b0(bytes.fromhex("007f8fac5b006e06"))[0] == 3
  # byte 3's top bits are a state field (Park idle is 8c)
  assert dec_2b0(bytes.fromhex("dc53a28c1b000e03"))[0] == L.PROPILOT_INACTIVE_RAW
  # heartbeat
  hb = bytes([0x4C, 0x47, 0x57, 1, 3, 5, 0, 0xF2])
  assert L.heartbeat_valid(hb) and not L.heartbeat_valid(hb[:7] + b"\x00")

  # 0x180 feedback decode: D for T=2528 per the model is -0.796*2528+2067.1 ~= 54.8 -> raw 55
  fb = bytes([0, 0, (55 >> 4) & 0xFF, (55 & 0xF) << 4, 0, 0, 0, 0])
  assert abs(L.feedback_t(fb) - 2527.8) < 0.5
  neg = (-100) & 0xFFF
  assert abs(L.feedback_t(bytes([0, 0, neg >> 4, (neg & 0xF) << 4, 0, 0, 0, 0])) - (2067.1 + 100) / 0.796) < 0.01

  # follow monitor (time-based): car tracks op -> no fault; car slows less than asked
  # -> fault after LAG + WINDOW; car slows MORE (stock winning) -> no fault; brake marker /
  # not evaluating -> no fault; same timing at 100 Hz and 50 Hz
  def run(op, car, secs, evaluate=True, mon=None, dt=0.01, t=0.0):
    mon = mon or L.FollowMonitor(); f = False
    for i in range(round(secs / dt)):
      f = mon.update(op, car, True, evaluate, t + i * dt)
    return f, mon
  for dt in (0.01, 0.02):
    assert not run(2600, 2600, 5, dt=dt)[0]
    assert not run(2600, 2600 - L.FOLLOW_TOL, 5, dt=dt)[0]
    assert run(2700, 2600, L.FOLLOW_LAG + L.FOLLOW_WINDOW + 2 * dt, dt=dt)[0]
    assert not run(2700, 2600, L.FOLLOW_LAG + L.FOLLOW_WINDOW - 2 * dt, dt=dt)[0]
    assert not run(2500, 2800, 5, dt=dt)[0]
    assert not run(2700, 2600, 5, evaluate=False, dt=dt)[0]
    assert not run(L.PROPILOT_BRAKE_RAW, 2600, 5, dt=dt)[0]
  f, mon = run(2700, 2600, 3)
  assert f and mon.update(2700, 2700, True, True, 3.0)   # latched while active
  assert not mon.update(2700, 2700, False, True, 3.01)   # cleared when long goes inactive
  assert not L.FollowMonitor().update(2700, 2600, True, True, None)   # no clock: skip, don't crash
  # the lag really is in time: op stepped from 2600 to 2700 only 0.1 s ago is not yet compared
  mon = L.FollowMonitor()
  for i in range(300):
    mon.update(2600, 2600, True, True, i * 0.01)
  for i in range(10):
    assert not mon.update(2700, 2600, True, True, 3.0 + i * 0.01) and mon.bad_since is None

  # pack -> decode round-trip across the whole range; frames must be gateway-valid
  for accel, la, stop, v, ves in sweep():
    cmd, pr, active, bmode = L.gateway_longitudinal(accel, la, stop, v, ves)
    a = L.pack_accel(cmd, frame=7, active=active)
    b = L.pack_brake(pr, frame=7, active=(la and pr > 0), brake_mode=bmode)
    dcmd, dactive = dec_2b0(a)          # raises if inverse-copy / fraction wrong
    dpr, _ = dec_1c3(b)                 # raises if checksum wrong
    assert dcmd == cmd, f"{dcmd} != {cmd}"
    assert dpr == pr, f"{dpr} != {pr}"
    assert dactive == active

  print("leaf_gw_long: all tests passed")


if __name__ == "__main__":
  main()
