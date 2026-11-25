# Test env for the FlowPilot leaf-gw patches (used by fork.sh via nix-shell).
# nixpkgs pinned to the same rev as leaf-gw's flake.lock.
{ pkgs ? import (fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/619c39f6eac5d1ed6b8f073a9414baf7034b2356.tar.gz";
    sha256 = "1m4bsj927vplp8rd4fgb789cf897frgvcnp8q8w51bsycvjqzbd1";
  }) {} }:
let
  # the 2022-era .pyx files need Cython 0.29
  py = pkgs.python312.withPackages (ps: with ps; [
    cython_0 numpy pycapnp cffi pytest parameterized hypothesis tqdm pyyaml setuptools
    libusb1 requests pyzmq crcmod
  ]);
in pkgs.mkShell {
  packages = [ py pkgs.clang pkgs.capnproto pkgs.zeromq pkgs.lmdb pkgs.libusb1 pkgs.scons ];
  hardeningDisable = [ "fortify" ];
  # read by SConstruct.test; FP_PY because the scons wrapper puts its own python first on PATH
  FP_PY = "${py}/bin/python3";
  FP_INC = "${pkgs.capnproto}/include:${pkgs.zeromq}/include:${pkgs.lmdb.dev}/include:${pkgs.libusb1.dev}/include";
  FP_LIB = "${pkgs.capnproto}/lib:${pkgs.zeromq}/lib:${pkgs.lmdb.out}/lib";
}
