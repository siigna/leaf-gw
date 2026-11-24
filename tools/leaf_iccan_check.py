#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md.
"""Phase-0 read-only validator for the Nissan Leaf (ZE1) Chassis CAN gateway.

Blocker #1: the 0x2B0 / 0x1C3 layouts and the 0x1C3 checksum are confirmed on a
2025 Leaf SV Plus only. Capture Chassis CAN on the actual 2018-2023 car -- with a
panda + Cabana, a USB-CAN adapter, or SocketCAN `candump` -- and feed the log to
this script. If the 0x1C3 checksum and the 0x2B0 inverse-copy validate, the
layout almost certainly carries over and the gateway can be trusted on that car.

Pure decode. It reads a log; it never touches a bus, so it is safe on any car.

Input: `candump` output on stdin or a file, either format:
    (1700000000.0) can0 1C3#000000006400FF27
    can0  1C3   [8]  00 00 00 00 64 00 FF 27
Usage:  candump can0 | leaf_iccan_check.py
        leaf_iccan_check.py capture.log
        leaf_iccan_check.py --self-test
"""
import re, sys

IDS = {0x1C3: "brake", 0x2B0: "accel"}
LINE = re.compile(r"\b([0-9A-Fa-f]{3})(?:#([0-9A-Fa-f]{16})|\s*(?:\[\d\])?\s*((?:[0-9A-Fa-f]{2}[\s]*){8}))")


def parse(line):
    m = LINE.search(line)
    if not m:
        return None
    cid = int(m.group(1), 16)
    if cid not in IDS:
        return None
    hexs = m.group(2) or m.group(3).replace(" ", "")
    if len(hexs) < 16:
        return None
    return cid, bytes.fromhex(hexs[:16])


def ck_1c3(d):
    return (0x01 + 0xC3 + sum(d[0:7])) & 0xFF


def dec_1c3(d):
    pressure = ((d[0] & 0x3F) << 4) | (d[1] >> 4)
    active = bool(d[5] & 0x80)
    ok = d[7] == ck_1c3(d)
    return pressure, active, ok


def dec_2b0(d):
    raw = (d[1] << 4) | (d[2] & 0x0F)
    frac = (d[7] >> 2) & 0x03
    command = raw * 4 + frac
    active = bool(d[4] & 0x40)
    accel = (command - 6144) / 2048.0
    inverse = ((d[2] >> 4) << 8) | ((d[0] & 0x0F) << 4) | (d[0] >> 4)
    ok = inverse == ((~raw) & 0xFFF)
    return command, accel, active, ok


def run(lines):
    seen = {}
    bad = {0x1C3: 0, 0x2B0: 0}
    n = {0x1C3: 0, 0x2B0: 0}
    for line in lines:
        p = parse(line)
        if not p:
            continue
        cid, d = p
        n[cid] += 1
        if cid == 0x1C3:
            pressure, active, ok = dec_1c3(d)
            if not ok:
                bad[cid] += 1
            seen[cid] = f"0x1C3 brake  pressure={pressure:4d} active={int(active)} cksum={'OK' if ok else 'BAD'}  {d.hex()}"
        else:
            command, accel, active, ok = dec_2b0(d)
            if not ok:
                bad[cid] += 1
            seen[cid] = f"0x2B0 accel  cmd={command:4d} ({accel:+.2f} m/s^2) active={int(active)} inv-copy={'OK' if ok else 'BAD'}  {d.hex()}"
    for cid in (0x1C3, 0x2B0):
        if cid in seen:
            print(seen[cid])
            print(f"      {n[cid]} frames, {bad[cid]} failed validation")
        else:
            print(f"0x{cid:03X} {IDS[cid]}: NOT SEEN -- wrong bus, or this ZE1 uses a different id")
    ok_all = all(cid in seen and bad[cid] == 0 for cid in IDS)
    print("\nblocker #1:", "PASS -- layouts validate on this car" if ok_all
          else "INCOMPLETE -- see failures/missing ids above")
    return 0 if ok_all else 1


def self_test():
    # Golden idle vector (StarPilot 2025 SV Plus): 0x1C3 = 000000006400ff27
    d = bytes.fromhex("000000006400ff27")
    assert ck_1c3(d) == 0x27, "checksum formula wrong"
    _, _, ok = dec_1c3(d)
    assert ok, "golden 0x1C3 idle should validate"
    bad = bytearray(d); bad[2] ^= 0x10
    assert not dec_1c3(bytes(bad))[2], "corrupted frame should fail checksum"
    print("self-test OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = open(args[0]) if args else sys.stdin
    sys.exit(run(src))
