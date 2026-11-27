"""Write copies of a board with each solder-mask / silkscreen / finish choice
in its stackup, for render.sh's colour previews (the order picks the colour;
the board files carry none), with STAND_INS swapped in for missing 3D models.

    kicad-python colors.py board.kicad_pcb out_dir   # prints the scheme names
"""

import os
import sys

# name: (mask, silkscreen, finish); JLCPCB's mask colours
SCHEMES = {
    "green-hasl": ("Green", "White", "HAL lead-free"),
    "black-enig": ("Black", "White", "ENIG"),
    "white-enig": ("White", "Black", "ENIG"),
    "blue-enig": ("Blue", "White", "ENIG"),
    "purple-enig": ("Purple", "White", "ENIG"),
    "red-enig": ("Red", "White", "ENIG"),
    "yellow-enig": ("Yellow", "Black", "ENIG"),
}

# Parts whose footprint names a 3D model KiCad's library doesn't ship: a
# look-alike for renders only (the board file keeps the real name).
STAND_INS = {
    "Connector_USB.3dshapes/USB_C_Receptacle_HRO_TYPE-C-31-M-12.stpZ":
        "Connector_USB.3dshapes/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.stpZ",
}


def stackup(mask, silk, finish):
    import board as B
    rows = []
    for name, kind, thick, _ in B.STACKUP:
        if "Paste" in kind:
            continue
        extra = f' (color "{mask}")' if "Mask" in kind else f' (color "{silk}")' if "Silk" in kind else ""
        t = f" (thickness {thick})" if thick else ""
        rows.append(f'\t\t\t(layer "{name}" (type "{kind}"){extra}{t})')
    return ("(stackup\n" + "\n".join(rows) + f'\n\t\t\t(copper_finish "{finish}")\n'
            "\t\t\t(dielectric_constraints no)\n\t\t)\n\t\t")


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    text = open(src).read()
    for real, look in STAND_INS.items():
        text = text.replace(real, look)
    assert "(stackup" not in text and "(setup\n\t\t" in text, "board already has a stackup, or a new setup layout"
    os.makedirs(out, exist_ok=True)
    for name, scheme in SCHEMES.items():
        with open(os.path.join(out, f"{name}.kicad_pcb"), "w") as fh:
            fh.write(text.replace("(setup\n\t\t", "(setup\n\t\t" + stackup(*scheme), 1))
        print(name)
