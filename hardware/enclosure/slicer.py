"""Print profiles and pre-oriented 3MF projects, via the OrcaSlicer CLI.

    python3 slicer.py build [out_dir]    # out/leaf-gw-case-{asa,abs,petg}.3mf from out/*.stl
    python3 slicer.py check [3mf ...]    # slice each with supports off; exit 1 on any failure

OrcaSlicer 2.4.2's CLI does not resolve a system profile's "inherits" chain
(a filament loaded by path comes out as PLA), so each profile is flattened
here from the bundled BBL tree, with our overrides on top. H2D is a
two-nozzle printer; in a project made this way both parts print from one
filament (the left nozzle, filament_map 1).
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PARTS = ("tray", "lid")
MACHINE = "Bambu Lab H2D 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL H2D"
# Our changes to the stock process: no supports (the parts need none: checks.py
# printable), stronger shells for screw bosses and clips, textured PEI.
PROCESS_SET = {"enable_support": "0", "wall_loops": "4", "sparse_infill_density": "25%",
               "curr_bed_type": "Textured PEI Plate"}
# filament_shrink: Orca scales XY by 100/shrink to cancel the plastic's
# shrinkage (the setting, not scaled STLs). Starting values; calibrate yours.
MATERIALS = {
    "asa": ("Bambu ASA @BBL H2D 0.4 nozzle", {"filament_shrink": ["99.5%"]}),
    "abs": ("Bambu ABS @BBL H2D", {"filament_shrink": ["99.4%"]}),
    "petg": ("Bambu PETG Basic @BBL H2D 0.4 nozzle", {}),   # PETG shrinks ~0.2-0.3 %: leave at 100 %
}


def orca():
    exe = shutil.which("orca-slicer")
    if not exe:
        return None, None
    return exe, os.path.join(os.path.dirname(os.path.realpath(exe)), "..", "share", "OrcaSlicer", "profiles", "BBL")


def resolve(root, kind, name):
    idx = {}
    for f in glob.glob(os.path.join(root, kind, "**", "*.json"), recursive=True):
        d = json.load(open(f))
        idx.setdefault(d.get("name"), d)

    def walk(n):
        d = idx[n]
        base = walk(d["inherits"]) if d.get("inherits") else {}
        base.update(d)
        base.pop("inherits", None)
        return base
    return walk(name)


def run(args):
    """orca-slicer, its result.json read back (it exits 0 on some failures)."""
    exe, _ = orca()
    od = args[args.index("--outputdir") + 1]
    p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=900, cwd=od)   # it logs to cwd
    try:
        r = json.load(open(os.path.join(od, "result.json")))
    except OSError:
        r = {"return_code": p.returncode, "error_string": (p.stdout + p.stderr)[-500:]}
    return r


def build(out=OUT):
    exe, root = orca()
    tmp = tempfile.mkdtemp()
    m = resolve(root, "machine", MACHINE)
    p = resolve(root, "process", PROCESS) | PROCESS_SET
    json.dump(m, open(os.path.join(tmp, "machine.json"), "w"))
    json.dump(p, open(os.path.join(tmp, "process.json"), "w"))
    stls = [os.path.join(OUT, f"{n}.stl") for n in PARTS]
    for mat, (name, extra) in MATERIALS.items():
        f = resolve(root, "filament", name) | extra
        fj = os.path.join(tmp, f"{mat}.json")
        json.dump(f, open(fj, "w"))
        dst = os.path.join(out, f"leaf-gw-case-{mat}.3mf")
        r = run(["--load-settings", f"{tmp}/machine.json;{tmp}/process.json", "--load-filaments", fj,
                 "--orient", "0", "--arrange", "1", "--export-3mf", os.path.basename(dst), "--outputdir", tmp, *stls])
        if r.get("return_code") != 0:
            raise SystemExit(f"{mat}: {r}")
        shutil.move(os.path.join(tmp, os.path.basename(dst)), dst)
        print(dst)


def project(path):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("Metadata/project_settings.config")), z


def check(paths, label=""):
    """Each 3MF: supports off, the right filament, objects as the STLs, and it slices."""
    import numpy as np
    import trimesh
    fails = 0
    want = {mat: name for mat, (name, _) in MATERIALS.items()}
    vols = sorted(trimesh.load(os.path.join(OUT, f"{n}.stl")).volume for n in PARTS)
    for path in paths:
        mat = re.search(r"-(\w+)\.3mf$", path).group(1)
        bad = []
        cfg, _ = project(path)
        if cfg.get("enable_support") != "0":
            bad.append(f"enable_support = {cfg.get('enable_support')}")
        if cfg.get("filament_settings_id") != [want.get(mat)]:
            bad.append(f"filament {cfg.get('filament_settings_id')}, want {want.get(mat)}")
        with zipfile.ZipFile(path) as z:
            models = [n for n in z.namelist() if n.startswith("3D/Objects/") and n.endswith(".model")]
            got = sorted(_volume(z.read(n).decode()) for n in models)
        if len(got) != len(vols) or not np.allclose(got, vols, rtol=1e-3):
            bad.append(f"object volumes {np.round(got)} differ from out/*.stl {np.round(vols)}: slicer.py build")
        od = tempfile.mkdtemp()
        r = run(["--slice", "0", "--outputdir", od, os.path.abspath(path)])
        if r.get("return_code") != 0:
            bad.append(f"slice failed: {r.get('error_string')}")
        else:
            g = open(glob.glob(os.path.join(od, "*.gcode"))[0]).read()
            if re.search(r";\s*FEATURE:\s*Support", g) or "; TYPE:Support" in g:
                bad.append("the G-code has support")
        print(f"{label or ('FAIL' if bad else 'ok  ')} {os.path.basename(path)}" + "".join(f"\n     {b}" for b in bad))
        fails += bool(bad)
    return fails


def _rewrite(src, dst, fn):
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            zo.writestr(it, fn(it.filename, zi.read(it)))


def selftest():
    """check() must fail a 3MF with supports turned on, and one whose objects
    are not the current STLs."""
    src = os.path.join(OUT, "leaf-gw-case-asa.3mf")
    tmp = tempfile.mkdtemp()
    sup, old = os.path.join(tmp, "support-asa.3mf"), os.path.join(tmp, "stale-asa.3mf")

    def support(name, data):
        if name == "Metadata/project_settings.config":
            cfg = json.loads(data)
            cfg.update(enable_support="1", support_type="normal(auto)")
            return json.dumps(cfg).encode()
        return data

    def stale(name, data):   # objects 2 % bigger in X
        if name.startswith("3D/Objects/"):
            return re.sub(rb'<vertex x="([^"]+)"', lambda m: b'<vertex x="%.4f"' % (float(m.group(1)) * 1.02), data)
        return data
    _rewrite(src, sup, support)
    _rewrite(src, old, stale)
    bad = [p for p in (sup, old) if not check([p], label="caught (expected)")]
    print(f"{'FAIL' if bad else 'ok  '} slicer check failed both broken 3MFs" + (f"; passed {bad}" if bad else ""))
    return bool(bad)


def _volume(xml):
    import numpy as np
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', xml), float)
    t = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', xml), int)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


if __name__ == "__main__":
    if not orca()[0]:
        print("SKIP: orca-slicer not on PATH (nix develop .#enclosure)")
        sys.exit(0)
    if sys.argv[1] == "build":
        build(*sys.argv[2:])
    elif sys.argv[1] == "selftest":
        sys.exit(1 if selftest() else 0)
    else:
        sys.exit(1 if check(sys.argv[2:] or sorted(glob.glob(os.path.join(OUT, "*.3mf")))) else 0)
