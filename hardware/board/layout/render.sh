#!/usr/bin/env bash
# Renders of the routed board into ../out/render (run inside `nix develop .#hardware`):
# 3D views of both sides (kicad-cli pcb render; KiCad's small library has no
# 3D models, so parts show as their pads and silkscreen) and 2D plots.
cd "$(dirname "$0")" || exit 1
out=../out/render
mkdir -p "$out"
pcb=leaf_gw.kicad_pcb
kicad-cli pcb render --side top --width 2400 --height 1600 --quality high --background opaque -o "$out/top.png" "$pcb" >/dev/null
kicad-cli pcb render --side bottom --width 2400 --height 1600 --quality high --background opaque -o "$out/bottom.png" "$pcb" >/dev/null
plot() {  # name, layers
  kicad-cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet -l "$2" -o "$out/$1.svg" "$pcb" >/dev/null
}
plot top-copper F.Cu,F.SilkS,F.Mask,Edge.Cuts
plot bottom-copper B.Cu,B.SilkS,Edge.Cuts
plot inner-gnd In1.Cu,Edge.Cuts
plot inner-3v3 In2.Cu,Edge.Cuts
plot assembly F.Fab,F.SilkS,Edge.Cuts
ls "$out"
