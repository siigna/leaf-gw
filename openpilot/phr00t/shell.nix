# Test env for the phr00t/flowpilot leaf-gw patch, used by fork.sh via nix-shell.
# nixpkgs pinned to the same rev as leaf-gw's flake.lock.
{ pkgs ? import (fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/619c39f6eac5d1ed6b8f073a9414baf7034b2356.tar.gz";
    sha256 = "1m4bsj927vplp8rd4fgb789cf897frgvcnp8q8w51bsycvjqzbd1";
  }) {} }:
let
  # Cython 3: numpy 2 headers (common/transformations) require it
  py = pkgs.python312.withPackages (ps: with ps; [
    cython numpy pycapnp cffi pytest pytest-xdist parameterized hypothesis tqdm pyyaml setuptools
    libusb1 requests pyzmq crcmod
  ]);
  # boardd_api_impl.pyx declares the extern "C" can_list_to_can_capnp_cpp with a bare
  # `cdef extern`; Cython 3 gives that C++ linkage (undefined symbol), Cython 0.29 doesn't
  cython0 = pkgs.python312.withPackages (ps: [ ps.cython_0 ps.setuptools ]);
  # boardd includes <libusb/libusb.h> (its vendored libusb layout); nixpkgs ships libusb-1.0/
  usbInc = pkgs.runCommand "libusb-include" {} "mkdir -p $out/include && ln -s ${pkgs.libusb1.dev}/include/libusb-1.0 $out/include/libusb";
in pkgs.mkShell {
  packages = [ py pkgs.clang pkgs.capnproto pkgs.zeromq pkgs.lmdb pkgs.libusb1 pkgs.scons ];
  hardeningDisable = [ "fortify" ];
  # read by SConstruct.test; FP_PY because the scons wrapper puts its own python first on PATH
  FP_PY = "${py}/bin/python3";
  FP_CYTHON0 = "${cython0}/bin/cythonize";
  FP_INC = "${pkgs.capnproto}/include:${pkgs.zeromq}/include:${pkgs.lmdb.dev}/include:${pkgs.libusb1.dev}/include:${usbInc}/include:${pkgs.eigen}/include";
  FP_LIB = "${pkgs.capnproto}/lib:${pkgs.zeromq}/lib:${pkgs.lmdb.out}/lib";
}
