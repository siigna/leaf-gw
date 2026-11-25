#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Stephen Bouche. See LICENSE and ATTRIBUTION.md.
"""Phase-0 read-only validator for the Nissan Leaf (ZE1) Chassis CAN gateway.

Blocker #1: the 0x2B0 / 0x1C3 layouts and the 0x1C3 checksum. Confirmed on stock
logs from 38 ZE1s (comma's commaCarSegments, a public US LEAF_IC route, and
SHIOKAZE's 2022 JDM e+). The 0x2B0 value is T = (b2 << 4) | (b1 & 0xF); StarPilot's
packer had it scrambled. Capture Chassis CAN on your car -- with a panda + Cabana,
a USB-CAN adapter, or SocketCAN `candump` -- and feed the log to this script. It
checks the 0x1C3 checksum, the 0x2B0 inverse copy, and that T moves smoothly.

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


BRAKE_MARKER = 3415   # stock 0x2B0 T while the friction brake is applied
MAX_P99_STEP = 32     # a real command moves a few counts per 10 ms frame


def dec_2b0(d):
    # T = (b2 << 4) | (b1 & 0xF), inverted copy in b1_hi:b0; higher T = more decel
    t = (d[2] << 4) | (d[1] & 0x0F)
    active = bool(d[4] & 0x40)
    ok = (((d[1] >> 4) << 8) | d[0]) == ((~t) & 0xFFF)
    return t, None, active, ok


def run(lines):
    seen = {}
    bad = {0x1C3: 0, 0x2B0: 0}
    n = {0x1C3: 0, 0x2B0: 0}
    prev = None
    steps = []   # (step, prev frame, frame) between consecutive non-marker 0x2B0 frames
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
            pc = dec_2b0(prev)[0] if prev is not None else None
            if pc is not None and BRAKE_MARKER not in (pc, command):
                steps.append((abs(command - pc), prev.hex(), d.hex()))
            prev = d
            if not ok:
                bad[cid] += 1
            seen[cid] = f"0x2B0 accel  T={command:4d} active={int(active)} inv-copy={'OK' if ok else 'BAD'}  {d.hex()}"
    for cid in (0x1C3, 0x2B0):
        if cid in seen:
            print(seen[cid])
            print(f"      {n[cid]} frames, {bad[cid]} failed validation")
        else:
            print(f"0x{cid:03X} {IDS[cid]}: NOT SEEN -- wrong bus, or this ZE1 uses a different id")
    # A real command can't jump far in one ~10 ms frame: a jumpy signal means the
    # bit order is wrong even when the inverse copy checks out.
    smooth = True
    if steps:
        p99 = sorted(st for st, _, _ in steps)[int(len(steps) * 0.99)]
        smooth = p99 <= MAX_P99_STEP
        top = sorted(steps, reverse=True)[:3]
        print(f"0x2B0 smoothness: p99 step {p99} (limit {MAX_P99_STEP}) {'OK' if smooth else 'BAD -- bit order?'}; "
              "largest " + ", ".join(f"{st} ({a}->{b})" for st, a, b in top))
    ok_all = smooth and all(cid in seen and bad[cid] == 0 for cid in IDS)
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
    # 0x2B0 golden frames from stock ZE1 logs: brake marker, a cruise frame, two consecutive
    brk, neu = bytes.fromhex("a827d5ac5b000e09"), bytes.fromhex("ff6090ac1b000e03")
    assert dec_2b0(brk)[0] == BRAKE_MARKER and dec_2b0(brk)[3], "golden 0x2B0 brake marker"
    assert dec_2b0(neu)[0] == 2304 and dec_2b0(neu)[3], "golden 0x2B0 cruise frame"
    # consecutive stock frames across the 0x900 boundary: 3 counts apart, not ~510
    r1, r2 = bytes.fromhex("fd6290ac5b005e03"), bytes.fromhex("007f8fac5b006e06")
    assert dec_2b0(r1)[0] - dec_2b0(r2)[0] == 3 and dec_2b0(r1)[3] and dec_2b0(r2)[3], "field layout"
    print("self-test OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = open(args[0]) if args else sys.stdin
    sys.exit(run(src))
