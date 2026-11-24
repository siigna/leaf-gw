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
  assert d[3] == 0xAC and d[5] == 0 and (d[6] & 0x0F) == 0x0E, "0x2B0 fixed bytes"
  raw12 = (d[1] << 4) | (d[2] & 0x0F)
  frac = (d[7] >> 2) & 0x03
  inverse = ((d[2] >> 4) << 8) | ((d[0] & 0x0F) << 4) | (d[0] >> 4)
  assert inverse == ((~raw12) & 0xFFF), "0x2B0 inverse copy"
  assert d[7] == (((frac << 2) | ((~frac) & 0x3)) & 0xFF), "0x2B0 fraction check"
  command = raw12 * 4 + frac
  active = bool(d[4] & 0x40)
  return command, active


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
  # mapping sanity
  assert L.gateway_longitudinal(0.0, True, False, 10.0)[0] == 6144
  assert L.gateway_longitudinal(0.0, False, False, 10.0)[0] == L.PROPILOT_INACTIVE_RAW
  assert L.gateway_longitudinal(-2.0, True, False, 10.0)[0] == L.PROPILOT_BRAKE_RAW
  assert L.gateway_longitudinal(-9.0, True, False, 10.0)[1] == L.BRAKE_MAX  # clamp

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
