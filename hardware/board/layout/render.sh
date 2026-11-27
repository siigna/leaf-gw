#!/usr/bin/env bash
# Renders of the routed board into ../out/render (run inside `nix develop .#hardware`):
# 3D views of both sides (kicad-cli pcb render, with KiCad's 3D models; the
# Molex headers and the DFU button have none and show as pads), the same in
# every mask colour JLCPCB offers plus an angled view (out/render/colors), and
# 2D plots.
cd "$(dirname "$0")" || exit 1
out=../out/render
mkdir -p "$out"
pcb=leaf_gw.kicad_pcb
kicad-cli pcb render --side top --width 2400 --height 1600 --quality high --background opaque -o "$out/top.png" "$pcb" >/dev/null
kicad-cli pcb render --side bottom --width 2400 --height 1600 --quality high --background opaque -o "$out/bottom.png" "$pcb" >/dev/null
plot() {  # name, layers
  kicad-cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet -l "$2" -o "$out/$1.svg" "$pcb" >/dev/null
}
# colour previews (colors.py: JLCPCB mask colours, ENIG or HASL), both sides,
# for whoever picks the order colour
tmp=$(mktemp -d) && trap 'rm -rf "$tmp"' EXIT
rm -rf "$out/colors" && mkdir -p "$out/colors"
for name in $(kicad-python colors.py "$pcb" "$tmp"); do
  for side in top bottom; do
    kicad-cli pcb render --use-board-stackup-colors --side $side --width 1200 --height 800 --quality high \
      --background opaque -o "$out/colors/$name-$side.png" "$tmp/$name.kicad_pcb" >/dev/null
  done
  kicad-cli pcb render --use-board-stackup-colors --rotate "-45,0,30" --perspective --width 1200 --height 800 \
    --quality high --background opaque -o "$out/colors/$name-angle.png" "$tmp/$name.kicad_pcb" >/dev/null
done
plot top-copper F.Cu,F.SilkS,F.Mask,Edge.Cuts
plot bottom-copper B.Cu,B.SilkS,Edge.Cuts
plot inner-gnd In1.Cu,Edge.Cuts
plot inner-3v3 In2.Cu,Edge.Cuts
plot assembly F.Fab,F.SilkS,Edge.Cuts
ls "$out"
