#!/usr/bin/env python3
"""Register the leaf_gw project in a RetroPilot ocelot firmware/SConscript.

Idempotent, anchor-based (resilient to line shifts). Adds two entries to the
`projects` dict, both built from leaf_gw/main.c (gw_panda.c): `leaf_gw` for the
Ocelot (board_gateway) and `leaf_gw_board` for the leaf-gw board
(-DLEAF_GW_BOARD, boards/leaf_gw.h). Links the core translation units
(leaf_gw.c, gw_engine.c, gw_supervisor.c) into their Program(), since panda
builds a single main TU.

Usage: ocelot_register.py <path-to-ocelot/firmware/SConscript>
"""
import sys


def register(path: str) -> None:
    s = open(path).read()
    if '"leaf_gw"' not in s:
        entry = ('  "leaf_gw": {\n'
                 '  "main": "leaf_gw/main.c",\n'
                 '  "startup": "startup_stm32f413xx.s",\n'
                 '  "flags": PROJECT_FLAGS\n'
                 '  },\n'
                 '  "leaf_gw_board": {\n'
                 '  "main": "leaf_gw/main.c",\n'
                 '  "startup": "startup_stm32f413xx.s",\n'
                 '  "flags": PROJECT_FLAGS + ["-DLEAF_GW_BOARD"]\n'
                 '  },\n')
        anchor = "projects = {\n"
        if anchor not in s:
            raise SystemExit("SConscript: `projects = {` not found")
        s = s.replace(anchor, anchor + entry, 1)

    if "leaf_gw_extra" not in s:
        prog = '  main_elf = panda_env.Program(f"{project_obj_dir}/{PROJECT}.elf", [startup, MAIN],'
        if prog not in s:
            raise SystemExit("SConscript: main Program() line not found")
        inject = (
            '  leaf_gw_extra = []\n'
            '  if PROJECT in ("leaf_gw", "leaf_gw_board"):\n'
            '    leaf_gw_extra = [panda_env.Object(f"{project_obj_dir}/{n}.o", f"leaf_gw/{n}.c") '
            'for n in ["leaf_gw", "gw_engine", "gw_supervisor"]]\n'
        )
        s = s.replace(prog, inject + prog.replace("[startup, MAIN],", "[startup, MAIN] + leaf_gw_extra,"), 1)

    open(path, "w").write(s)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    register(sys.argv[1])
    print(f"registered leaf_gw in {sys.argv[1]}")
