#!/usr/bin/env python3
"""Prove test_gw_supervisor bites: each mutant of gw_supervisor.c must FAIL it.

Each mutation is one or more exact text replacements (each must match once, so a refactor that
moves the text fails here loudly instead of silently testing nothing).
Usage: tools/mutate_supervisor.py   (from the repo root; needs cc)
"""
import os
import subprocess
import sys
import tempfile

MUTANTS = [
    ("forward switched after the relay (fault order)", [
        ("    sup_hw_forward(s->st == SUP_ENGAGED);\n    if (relay) {", "    if (relay) {"),
        ("    sup_hw_xcvr(s->st != SUP_FAULT);",
         "    sup_hw_forward(s->st == SUP_ENGAGED);\n    sup_hw_xcvr(s->st != SUP_FAULT);")]),
    ("forwarding starts with the relay (no settle)",
     "sup_hw_forward(s->st == SUP_ENGAGED);", "sup_hw_forward(relay);"),
    ("relay energized before the watchdog is armed",
     "            sup_hw_kick(s->kick_level);\n        }\n        sup_hw_relay(true);",
     "        }\n        sup_hw_relay(true);\n        if (s->kick_armed) { sup_hw_kick(s->kick_level); }"),
    ("kick period 10x too slow", ">= SUP_KICK_MS)", ">= (SUP_KICK_MS * 10u))"),
    ("kick level never toggles", "s->kick_level = !s->kick_level;", "s->kick_level = true;"),
    ("watchdog not disarmed on release", "            sup_hw_kick_release();\n", ""),
    ("ignition ignored", "if (!in->ign)", "if (false)"),
    ("bus-off ignored", "if (in->bus_off)", "if (false)"),
    ("RX stall ignored", "return seen && ((uint32_t)(now_ms - t) <= SUP_RX_STALE_MS);", "return true;"),
    ("car-side stall ignored", " || !fresh(s->car_seen, s->t_car, now_ms)", ""),
    ("stall check not wrap-safe", "((uint32_t)(now_ms - t) <= SUP_RX_STALE_MS)", "(now_ms <= (t + SUP_RX_STALE_MS))"),
    ("TX overflow ignored", "if (in->fwd_errs != s->fwd_errs)", "if (false)"),
    ("fault not latched", "        case SUP_WAIT:", "        case SUP_FAULT:\n        case SUP_WAIT:"),
    ("no transceiver settle", ">= SUP_XCVR_SETTLE_MS)", ">= 0u)"),
    ("transceivers stay on in fault", "sup_hw_xcvr(s->st != SUP_FAULT);", "sup_hw_xcvr(true);"),
    ("heartbeat kept in fault", "return s->st != SUP_FAULT;", "return true;"),
    ("wrong IGN divider", "122u) / (4095u * 22u)", "133u) / (4095u * 33u)"),   # the old 100k/33k board
]


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "gw_supervisor.c")).read()
    cc = os.environ.get("CC", "cc")
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, *edits in MUTANTS:
            edits = edits[0] if len(edits) == 1 else [tuple(edits)]
            if any(src.count(old) != 1 for old, _ in edits):
                print(f"MUTANT TEXT NOT FOUND ONCE: {name}")
                bad += 1
                continue
            m = src
            for old, new in edits:
                m = m.replace(old, new)
            mut = os.path.join(tmp, "gw_supervisor.c")
            open(mut, "w").write(m)
            exe = os.path.join(tmp, "t")
            r = subprocess.run([cc, "-std=c11", "-I", root, mut, os.path.join(root, "test_gw_supervisor.c"),
                                "-o", exe], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"MUTANT DID NOT BUILD: {name}\n{r.stderr}")
                bad += 1
                continue
            r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                print(f"SURVIVED: {name}")
                bad += 1
            else:
                first = next((ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")), "")
                print(f"killed: {name}  ({first.strip()})")
    print(f"{len(MUTANTS) - bad}/{len(MUTANTS)} mutants killed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
