{
  description = "leaf-gw: Nissan Leaf Chassis CAN longitudinal gateway decision core (host-testable)";

  inputs = {
    nixpkgs.url = "flake:nixpkgs";

    # RetroPilot ocelot firmware tree, built offline into the panda backend.
    ocelot = {
      url = "github:RetroPilot/ocelot";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, ocelot }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
      lib = nixpkgs.lib;
    in {
      packages = forAll (pkgs: {
        # `nix build` compiles the pure core and runs the host test suite.
        default = pkgs.stdenv.mkDerivation {
          pname = "leaf-gw";
          version = "0.1.0";
          src = ./.;
          doCheck = true;
          buildPhase = "$CC $NIX_CFLAGS_COMPILE -Wall -Wextra -O2 -std=c11 leaf_gw.c gw_engine.c test_leaf_gw.c -lm -o test_leaf_gw";
          checkPhase = "./test_leaf_gw";
          installPhase = "mkdir -p $out/bin $out/include && cp test_leaf_gw $out/bin/ && cp leaf_gw.h $out/include/";
        };
      }
      # The panda/Ocelot firmware image. STM32 cross build (gcc-arm-embedded +
      # scons), offline; copies the backend + engine into the ocelot tree,
      # registers the scons project, and signs with the debug cert.
      // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        ocelot-firmware = pkgs.stdenv.mkDerivation {
          pname = "leaf-gw-ocelot-firmware";
          version = "0.1.0";
          src = ./.;
          nativeBuildInputs = [
            pkgs.gcc-arm-embedded
            pkgs.scons
            pkgs.git
            (pkgs.python3.withPackages (ps: [ ps.pycryptodome ]))
          ];
          dontConfigure = true;
          buildPhase = ''
            runHook preBuild
            cp -r ${ocelot}/firmware octree
            chmod -R u+w octree
            mkdir -p octree/leaf_gw
            cp backends/panda/gw_panda.c octree/leaf_gw/main.c
            cp leaf_gw.c leaf_gw.h gw_engine.c gw_engine.h octree/leaf_gw/
            cp octree/smart_dsu/can.h octree/leaf_gw/can.h
            patchShebangs octree/crypto
            python3 backends/panda/ocelot_register.py octree/SConscript
            ( cd octree && PROJECT=leaf_gw scons -u -j"$NIX_BUILD_CORES" )
            runHook postBuild
          '';
          installPhase = ''
            mkdir -p $out
            cp octree/obj/leaf_gw.bin.signed $out/leaf_gw.bin.signed
            cp octree/obj/leaf_gw/leaf_gw.elf $out/leaf_gw.elf
            cp octree/obj/leaf_gw/leaf_gw.bin $out/leaf_gw.bin
          '';
        };
      });

      # `nix run` the read-only phase-0 Chassis CAN validator on a candump log.
      apps = forAll (pkgs:
        let
          iccan = pkgs.writeShellScriptBin "leaf-iccan-check"
            ''exec ${pkgs.python3}/bin/python3 ${./tools/leaf_iccan_check.py} "$@"'';
        in {
          default = { type = "app"; program = "${iccan}/bin/leaf-iccan-check"; };
        });

      # `nix flake check` runs everything `make test` does: the C core plus both
      # host-testable Python pieces (the phase-0 validator and the openpilot
      # longitudinal mapping).
      checks = forAll (pkgs: {
        core = self.packages.${pkgs.system}.default;

        iccan-validator = pkgs.runCommand "leaf-gw-iccan-validator-test" { } ''
          ${pkgs.python3}/bin/python3 ${./tools/leaf_iccan_check.py} --self-test
          touch $out
        '';

        openpilot-long = pkgs.runCommand "leaf-gw-openpilot-long-test"
          { nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.numpy ])) ]; } ''
          cp ${./openpilot/leaf_gw_long.py} leaf_gw_long.py
          cp ${./openpilot/test_leaf_gw_long.py} test_leaf_gw_long.py
          python3 test_leaf_gw_long.py
          touch $out
        '';
      }
      // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
        # CI coverage that the panda/Ocelot firmware still compiles, links and signs.
        ocelot-firmware = self.packages.${pkgs.system}.ocelot-firmware;
      });

      devShells = forAll (pkgs: {
        # Host build/test: `make test` (C core + both Python suites).
        default = pkgs.mkShell {
          packages = [ pkgs.gcc pkgs.gnumake (pkgs.python3.withPackages (ps: [ ps.numpy ])) ];
        };

        # Build the panda/Ocelot firmware backend by hand inside an ocelot tree.
        panda = pkgs.mkShell {
          packages = [
            pkgs.gcc-arm-embedded
            pkgs.scons
            (pkgs.python3.withPackages (ps: [ ps.pycryptodome ]))
          ];
        };

        # Run the opendbc car-port and panda-safety patches' test suites.
        # opendbc needs Python < 3.13 (pycapnp); libsafety builds with cc + cffi.
        openpilot = pkgs.mkShell {
          # libsafety builds at -O0 -Werror; nix's _FORTIFY_SOURCE would make that fail.
          hardeningDisable = [ "fortify" ];
          packages = [
            pkgs.gcc
            (pkgs.python312.withPackages (ps: with ps; [
              numpy pycapnp cffi pytest hypothesis parameterized
              tqdm pytest-subtests pytest-xdist pycryptodome
              crcmod smbus2 pyzmq   # StarPilot's opendbc imports openpilot.system.hardware
            ]))
            pkgs.scons   # StarPilot's opendbc builds libsafety with it; after python so 3.12 wins on PATH
          ];
        };
      });
    };
}
