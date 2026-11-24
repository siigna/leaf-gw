#!/usr/bin/env python3
"""Register the leaf_gw project in a RetroPilot ocelot firmware/SConscript.

Idempotent, anchor-based (resilient to line shifts). Adds a `leaf_gw` entry to
the `projects` dict and links the engine translation units (leaf_gw.c,
gw_engine.c) into that project's Program(), since panda builds a single main TU.

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
            '  if PROJECT == "leaf_gw":\n'
            '    leaf_gw_extra = [panda_env.Object(f"{project_obj_dir}/{n}.o", f"leaf_gw/{n}.c") '
            'for n in ["leaf_gw", "gw_engine"]]\n'
        )
        s = s.replace(prog, inject + prog.replace("[startup, MAIN],", "[startup, MAIN] + leaf_gw_extra,"), 1)

    open(path, "w").write(s)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    register(sys.argv[1])
    print(f"registered leaf_gw in {sys.argv[1]}")
