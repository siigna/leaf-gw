# Test env for RetroPilot c2 (openpilot 0.8.13.1) + the leaf-gw patches; used by fork.sh.
# nixos-23.05: Python 3.11, Cython 0.29, numpy 1.24, pycapnp 1.1 (24.05 marks pycapnp
# broken; numpy 2 breaks common/transformations/transformations.pyx).
{ pkgs ? import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/70bdadeb94ffc8806c0570eb5c2695ad29f0e421.tar.gz";
    sha256 = "05cbl1k193c9la9xhlz4y6y8ijpb2mkaqrab30zij6z4kqgclsrd";
  }) {} }:
pkgs.mkShell {
  hardeningDisable = [ "fortify" ];
  packages = [
    pkgs.clang pkgs.capnproto pkgs.zeromq pkgs.libusb1 pkgs.eigen pkgs.git
    (pkgs.python311.withPackages (ps: with ps; [
      numpy cython pycapnp cffi pytest parameterized crcmod pyzmq libusb1 pyserial
      hypothesis tqdm setproctitle psutil requests jinja2 pyyaml smbus2 pycryptodome
    ]))
    pkgs.scons  # after python so 3.11 wins on PATH; scons runs on its own interpreter, hence PY=
  ];
}
