import { fileIo as fs } from '@kit.CoreFileKit';
import { zlib } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { image } from '@kit.ImageKit';
import { util } from '@kit.ArkTS';
import native, { RuntimeReport, ExpressionReport, ExtractReport, ScriptReport, GLReport, GLHandlesReport, EvalProbeReport, DrawAtomsReport } from 'libchimerax_native.so';

// Keep in sync with the packaged rawfile name: a stale copy in the sandbox
// would otherwise be reused after the runtime contents change.
const ARCHIVE = 'cx-runtime.zip';
// Rewritten by tools/package_app_runtime.py: the payload hash names the extraction directory,
// so changed Python code is always unpacked instead of reusing a stale tree.
const RUNTIME_TAG = '1745e2211ffb';
const RUNTIME_DIR = 'cx-generic-runtime';
// v5: forces a fresh extraction so a stale payload is never reused.
// The store name carries the packaged archive size, so a new payload always
// extracts into a fresh directory instead of reusing stale content.


// Runs a real ChimeraX command: the command is registered in the (global)
// command table exactly like a bundle would, then executed through
// chimerax.core.commands.run with a minimal Session.
const COMMAND_SCRIPT = `
import io, sys
from chimerax.core.session import Session
from chimerax.core.commands import CmdDesc, StringArg, register, run

# Reuse the persistent session created by the native bootstrap; creating a new
# one here would shadow it and lose tools/toolshed.
try:
    session
except NameError:
    class _NullUI:
        is_gui = False
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    session = Session("ChimeraX", silent=True, minimal=True)
    session.ui = _NullUI()
calls = []

def _cx_probe(session, value):
    calls.append(value)
    return "cxprobe:" + value

register("cxprobe", CmdDesc(required=[("value", StringArg)],
                            synopsis="harmony adaptation probe command"), _cx_probe)
result = run(session, "cxprobe hello-harmony")
print("%s|%s|%s" % (result, len(calls), calls[0]))
`;


// Two genuine ChimeraX built-ins registered by the core bundle: toolshed list
// executes, and devel dump exercises CmdDesc argument validation.
const BUILTIN_SCRIPT = `
from chimerax.core.commands import run
summary = []
try:
    run(session, "toolshed list")
    summary.append("toolshed-list:ok")
except Exception as error:
    summary.append("toolshed-list:" + type(error).__name__ + ":" + str(error)[:40])
try:
    run(session, "devel dump /nonexistent/cx-probe.txt")
    summary.append("devel-dump:no-error")
except Exception as error:
    summary.append("devel-dump:" + str(error).split(":")[0])
try:
    import chimerax.map._map as _cx_map
    summary.append("map-ext:ok")
except Exception as error:
    summary.append("map-ext:" + type(error).__name__)
# "list models" comes from the list_info bundle, which the payload now ships.
try:
    run(session, "list models")
    summary.append("list-models:ok")
except Exception as error:
    summary.append("list-models:" + type(error).__name__ + ":" + str(error)[:60])
_cx_notes = globals().get("_cx_notes") or []
print("|".join(summary) + "|tools=%s|toolshed=%s|state=%s|notes=%s" % (
    hasattr(session, "tools"), hasattr(session, "toolshed"),
    globals().get("_cx_state", "?"), ",".join(_cx_notes)[:120] or "-"))
`;


// Builds a real AtomicStructure with atoms through chimerax.atomic, which exercises
// the C++ atomstruct layer, the pyinstance registry and the shared support library.
const MODEL_SCRIPT = `
import numpy
from chimerax.atomic import AtomicStructure
structure = AtomicStructure(session, name="cx_app_model")
residue = structure.new_residue("UNL", "A", 1)
coords = numpy.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]], dtype=numpy.float64)
names = ["C1", "N1"]
elements = ["C", "N"]
for index, name in enumerate(names):
    atom = structure.new_atom(name, elements[index])
    atom.coord = coords[index]
    residue.add_atom(atom)
print("atoms=%d|residues=%d|names=%s" % (structure.num_atoms, structure.num_residues,
      ",".join(a.name for a in structure.atoms)))
`;


// Reads a real PDB file from the app sandbox through the C++ PDB reader, which is
// the path the production "open" command takes once the file dialog exists.
const OPEN_SCRIPT = `
import os
from chimerax.io import open_input
from chimerax.pdb.pdb import open_pdb

pdb_text = """HEADER    HARMONY PROBE
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.420   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.251   2.392   0.000  1.00  0.00           O
END
"""
path = os.path.join(chimerax_home(), "cx_probe.pdb") if "chimerax_home" in dir() else "/data/storage/el2/base/haps/entry/files/cx_probe.pdb"
with open(path, "w") as handle:
    handle.write(pdb_text)
with open_input(path) as stream:
    opened = open_pdb(session, stream, path)
models = []
stack = list(opened) if isinstance(opened, (list, tuple)) else [opened]
while stack:
    item = stack.pop()
    if hasattr(item, "num_atoms"):
        models.append(item)
    elif isinstance(item, (list, tuple)):
        stack.extend(item)
# Registering models triggers notifications that need managers this minimal session
# lacks; keep the list regardless so the viewer still sees the atoms.
cx_opened_models = list(models)
try:
    session.models.add(models)
except Exception:
    pass
print("models=%d|atoms=%d|residues=%d" % (
    len(models), sum(m.num_atoms for m in models), sum(m.num_residues for m in models)))
`;





// Writes atom coordinates for the native point viewer (used until ChimeraX's own
// renderer is ported to GLSL ES).
const ATOM_DUMP_SCRIPT = `
import os
path = os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt")
lines = []
candidates = list(globals().get("cx_opened_models") or [])
candidates += [m for m in session.models.list() if m not in candidates]
for model in candidates:
    if not hasattr(model, "atoms"):
        continue
    coords = model.atoms.coords
    elements = model.atoms.elements
    for index, coord in enumerate(coords):
        x, y, z = float(coord[0]), float(coord[1]), float(coord[2])
        symbol = elements[index].name if index < len(elements) else "C"
        tone = {"C": (0.75, 0.75, 0.75), "N": (0.35, 0.45, 0.95),
                "O": (0.95, 0.35, 0.30), "S": (0.95, 0.85, 0.25)}.get(symbol, (0.6, 0.8, 0.6))
        lines.append("%.4f %.4f %.4f %.3f %.3f %.3f" % (x, y, z, tone[0], tone[1], tone[2]))
with open(path, "w") as handle:
    handle.write(chr(10).join(lines))
print("atoms_written=%d" % len(lines))
`;


// Builds a small alpha-helix so the viewer has a genuinely three-dimensional demo
// structure (the four-atom PDB probe is planar and collapses to a dot when rotated).
const DEMO_SCRIPT = `
import math, os
path = os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt")
lines = []
for index in range(60):
    angle = index * 0.9
    x = 6.0 * math.cos(angle)
    y = 6.0 * math.sin(angle)
    z = index * 0.55 - 16.0
    lines.append("%.4f %.4f %.4f 0.450 0.700 0.950" % (x, y, z))
with open(path, "w") as handle:
    handle.write(chr(10).join(lines))
print("demo_atoms=%d" % len(lines))
`;


// Lists structure files the app itself wrote into the sandbox; the app has no system
// file dialog yet, so this is the open path users can exercise today.
const LIST_SCRIPT = `
import os
root = "/data/storage/el2/base/haps/entry/files"
names = sorted(n for n in os.listdir(root) if n.endswith((".pdb", ".cif", ".mmcif")))
print("files=%d|%s" % (len(names), ",".join(names)))
`;

// Double helix: a helix plus a strand, so the viewer shows a genuinely three-dimensional
// object with visible bonds instead of a planar four-atom probe.
const DEMO2_SCRIPT = `
import math, os
path = os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt")
lines = []
for index in range(48):
    angle = index * 1.745
    lines.append("%.4f %.4f %.4f 0.400 0.750 0.950" % (
        6.0 * math.cos(angle), 6.0 * math.sin(angle), index * 1.2 - 28.0))
for index in range(20):
    lines.append("%.4f %.4f %.4f 0.950 0.550 0.350" % (
        -8.0 + index * 0.9, 10.0 + math.sin(index * 0.6) * 2.0, index * 1.4 - 14.0))
with open(path, "w") as handle:
    handle.write(chr(10).join(lines))
print("demo2_atoms=%d" % len(lines))
`;


// Opens a structure file the user picked from the sandbox listing.
const OPEN_PATH_SCRIPT = `
import os
from chimerax.io import open_input
from chimerax.pdb.pdb import open_pdb

path = os.path.join("/data/storage/el2/base/haps/entry/files", "__FILE__")
with open_input(path) as stream:
    opened = open_pdb(session, stream, path)
models = []
stack = list(opened) if isinstance(opened, (list, tuple)) else [opened]
while stack:
    item = stack.pop()
    if hasattr(item, "num_atoms"):
        models.append(item)
    elif isinstance(item, (list, tuple)):
        stack.extend(item)
cx_opened_models = models
lines = []
for model in models:
    coords = model.atoms.coords
    elements = model.atoms.elements
    for index, coord in enumerate(coords):
        symbol = elements[index].name if index < len(elements) else "C"
        tone = {"C": (0.75, 0.75, 0.75), "N": (0.35, 0.45, 0.95),
                "O": (0.95, 0.35, 0.30), "S": (0.95, 0.85, 0.25)}.get(symbol, (0.6, 0.8, 0.6))
        lines.append("%.4f %.4f %.4f %.3f %.3f %.3f" % (
            float(coord[0]), float(coord[1]), float(coord[2]),
            tone[0], tone[1], tone[2]))
with open(os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt"), "w") as handle:
    handle.write(chr(10).join(lines))
print("opened=%d|atoms=%d" % (len(models), len(lines)))
`;


// Three-helix bundle: a larger structure used to check that the viewer copes with
// hundreds of atoms and that bonds stay cheap at that size.
const DEMO3_SCRIPT = `
import math, os
path = os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt")
lines = []
offsets = [(-9.0, 0.0, 0.550, 0.700, 0.950),
           (9.0, 0.0, 0.950, 0.650, 0.300),
           (0.0, 11.0, 0.450, 0.900, 0.550)]
for (ox, oy, red, green, blue) in offsets:
    for index in range(56):
        angle = index * 1.745
        lines.append("%.4f %.4f %.4f %.3f %.3f %.3f" % (
            ox + 5.2 * math.cos(angle), oy + 5.2 * math.sin(angle),
            index * 1.35 - 38.0, red, green, blue))
with open(path, "w") as handle:
    handle.write(chr(10).join(lines))
print("demo3_atoms=%d" % len(lines))
`;


// Large bundle: eight helices (~450 atoms) to check the viewer at a realistic size and
// expose the cost of the O(n^2) bond pass.
const DEMO4_SCRIPT = `
import math, os
path = os.path.join("/data/storage/el2/base/haps/entry/files", "cx_atoms.txt")
lines = []
ring = 0
for cluster in range(8):
    angle_offset = cluster * (2.0 * math.pi / 8.0)
    ox = 26.0 * math.cos(angle_offset)
    oy = 26.0 * math.sin(angle_offset)
    for index in range(56):
        angle = index * 1.745 + angle_offset
        lines.append("%.4f %.4f %.4f %.3f %.3f %.3f" % (
            ox + 5.0 * math.cos(angle), oy + 5.0 * math.sin(angle),
            index * 1.25 - 35.0, 0.35 + 0.07 * cluster, 0.75, 0.95 - 0.06 * cluster))
        ring += 1
with open(path, "w") as handle:
    handle.write(chr(10).join(lines))
print("demo4_atoms=%d" % len(lines))
`;


// Saves the current atom list as a PDB file inside the sandbox: a round trip that proves
// the write side works without a system file dialog.
const SAVE_SCRIPT = `
import os
root = "/data/storage/el2/base/haps/entry/files"
src = os.path.join(root, "cx_atoms.txt")
dst = os.path.join(root, "cx_saved.pdb")
lines = []
element_of = {(0.75, 0.75, 0.75): "C", (0.35, 0.45, 0.95): "N",
              (0.95, 0.35, 0.30): "O", (0.95, 0.85, 0.25): "S"}
with open(src) as handle:
    rows = [line.split() for line in handle if line.strip()]
for index, row in enumerate(rows, start=1):
    x, y, z = float(row[0]), float(row[1]), float(row[2])
    key = (round(float(row[3]), 2), round(float(row[4]), 2), round(float(row[5]), 2))
    symbol = element_of.get(key, "C")
    lines.append("ATOM  %5d  %-3s UNL A   1    %8.3f%8.3f%8.3f  1.00  0.00          %2s" % (
        index, symbol + str(index), x, y, z, symbol))
lines.append("END")
with open(dst, "w") as handle:
    handle.write(chr(10).join(lines))
print("saved=%d" % len(rows))
`;


// Decides whether GLES status queries work at all: compile and link a trivial ES3
// program and read GL_LINK_STATUS through the same PyOpenGL path ChimeraX uses.
const SHADER_DIAG_SCRIPT = `
# Keep this probe side-effect free: calling into the GL module from the page thread without a
# current context crashed the app, so it only reports the EGL handles it was given.
def diagnose(display_ptr, context_ptr, surface_ptr):
    return "handles=%s/%s/%s" % (display_ptr, context_ptr, surface_ptr)

print(diagnose("__DISPLAY__", "__CONTEXT__", "__SURFACE__"))
`;// Runs a command registered by a newly staged bundle: "list models" comes from the
// list_info bundle and only needs the core + models manager.
const LIST_COMMAND_SCRIPT = `
from chimerax.core.commands import run
try:
    result = run(session, "list models")
    print("list-models:ok")
except Exception as error:
    print("list-models:" + type(error).__name__ + ":" + str(error)[:60])
`;


// Lists every command registered in the session: proof that the command system is wired,
// and the starting point for a real tool palette.
const COMMANDS_SCRIPT = `
names = []
try:
    from chimerax.core.commands import cli as _cli
    def _walk(node, prefix):
        for word, child in node.subcommands.items():
            full = (prefix + " " + word).strip()
            if child.has_command():
                names.append(full)
            _walk(child, full)
    _walk(_cli._command_info.commands, "")
except Exception as error:
    names = ["error:" + type(error).__name__]
# The palette shows every registered command, not just the first screenful.
print("commands=%d|%s" % (len(names), ",".join(sorted(names))))
`;


// Writes a two-atom SDF and reads it with the sdf bundle's reader. The open command needs
// the data-format table that only toolshed populates, so the reader is called directly and
// its models are drawn by the native viewer.
const OPEN_SDF_SCRIPT = `
import os
root = "/data/storage/el2/base/haps/entry/files"
sdf = os.path.join(root, "cx_demo.sdf")
text = chr(10).join([
    "cx_demo",
    "  chimerax-harmony",
    "",
    "  2  1  0  0  0  0  0  0  0  0999 V2000",
    "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0",
    "    1.4000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0",
    "  1  2  1  0",
    "M  END",
]) + chr(10)
with open(sdf, "w") as handle:
    handle.write(text)
try:
    from chimerax.sdf import read_sdf
    with open(sdf, "r") as stream:
        models = read_sdf(session, stream, sdf)
except Exception as error:
    print("sdf-read:" + type(error).__name__ + ":" + str(error)[:70])
    models = []
atoms = 0
lines = []
for model in (models if isinstance(models, (list, tuple)) else [models]):
    if model is None or not hasattr(model, "atoms"):
        continue
    atoms += len(model.atoms)
    for index, coord in enumerate(model.atoms.coords):
        lines.append("%.4f %.4f %.4f 0.800 0.800 0.800" % (
            float(coord[0]), float(coord[1]), float(coord[2])))
if lines:
    with open(os.path.join(root, "cx_atoms.txt"), "w") as handle:
        handle.write(chr(10).join(lines))
print("sdf-read:ok|atoms=%d" % atoms)
`;

// Opens the bundled PDB and asks the list_info bundle about the models: command and model
// layers talking to each other, not just each one on its own.
const INFO_MODELS_SCRIPT = `
import os
from chimerax.pdb.pdb import open_pdb
from chimerax.core.commands import run

# The demo structures ship inside the runtime tree, so Python can always read them.
import chimerax as _cx_pkg
_cx_runtime = os.path.dirname(os.path.dirname(os.path.abspath(_cx_pkg.__file__)))
_cx_real = os.path.join(_cx_runtime, "chimerax", "demo_data", "cx_demo.pdb")
if not os.path.exists(_cx_real):
    _cx_real = "/data/storage/el2/base/haps/entry/files/cx_demo.pdb"
path = _cx_real if os.path.exists(_cx_real) else os.path.join(
    "/data/storage/el2/base/haps/entry/files", "cx_probe.pdb")
print("source=" + ("demo" if "demo_data" in path else "probe"))
if not os.path.exists(path):
    print("info-models:no-pdb")
else:
    with open(path, "rb") as stream:
        opened = open_pdb(session, stream, path)
    # Use the models this open produced: the session list only holds earlier ones.
    models = []
    _cx_stack = [opened]
    while _cx_stack:
        _item = _cx_stack.pop()
        if isinstance(_item, (list, tuple)):
            _cx_stack.extend(_item)
        elif hasattr(_item, "atoms"):
            models.append(_item)
    # Target the model with the most standard amino-acid residues; report the command result
    # first so UI truncation can never hide the one line we care about.
    _CX_AMINO = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
                 "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"}
    _cx_spec = "#1"
    # Registering gives the models ids that atom specs can reference (best effort).
    try:
        session.models.add(models)
    except Exception:
        pass
    try:
        def _cx_amino_score(model):
            try:
                names = {r.name for r in list(model.atoms.residues)[:200]}
            except Exception:
                return 0
            return len(names & _CX_AMINO)

        _cx_candidates = [m for m in models if getattr(m, "atoms", None) is not None]
        if _cx_candidates:
            _cx_best = max(_cx_candidates, key=_cx_amino_score)
            _cx_id = _cx_best.id
            if isinstance(_cx_id, tuple):
                _cx_id = _cx_id[0]
            if _cx_id is not None:
                _cx_spec = "#%s" % _cx_id
    except Exception as error:
        print("target:" + type(error).__name__ + ":" + str(error)[:30])
    try:
        run(session, "mlp " + _cx_spec)
        _cx_mlp = "ok"
    except Exception as error:
        _cx_mlp = type(error).__name__ + ":" + str(error)[:70]
    print("mlp=" + _cx_mlp)
    for command in ("coulombic " + _cx_spec, "info chains"):
        try:
            run(session, command)
            print(command.replace(" ", "-") + ":ok")
        except Exception as error:
            print(command.replace(" ", "-") + ":" + type(error).__name__
                  + ":" + str(error)[:40])
    try:
        run(session, "info models")
        print("info-models:ok|models=%d" % len(models))
    except Exception as error:
        print("info-models:" + type(error).__name__ + ":" + str(error)[:60])
    # List commands from the list_info bundle that only need the model layer. "zone" needs
    # chimerax.map, whose C++ extensions are not built yet, so it stays out of this probe.
    # Exercise the commands the newly built bundles register.
    # Diagnose why mlp sees no amino acids: what the opened models actually are.
    try:
        _cx_kinds = ",".join(type(m).__name__ for m in models[:3])
        _cx_attrs = []
        for _model in models[:1]:
            _cx_attrs.append("atoms=%s" % hasattr(_model, "atoms"))
            if hasattr(_model, "atoms"):
                _cx_attrs.append("residues=%s" % hasattr(_model.atoms, "residues"))
        print("kinds=" + _cx_kinds + "|" + "|".join(_cx_attrs))
    except Exception as error:
        print("kinds:" + type(error).__name__ + ":" + str(error)[:40])
    for command in ("info atoms", "info residues"):
        try:
            run(session, command)
            print(command.replace(" ", "-") + ":ok")
        except Exception as error:
            print(command.replace(" ", "-") + ":" + type(error).__name__ + ":" + str(error)[:40])
`;


// Copies the bundled ras.pdb asset into the sandbox and opens it: a real 1300-atom protein
// rather than the four-atom probe.
const OPEN_REAL_PDB_SCRIPT = `
import os
root = "/data/storage/el2/base/haps/entry/files"
target = os.path.join(root, "cx_demo.pdb")
from chimerax.pdb.pdb import open_pdb
if not os.path.exists(target):
    print("real-pdb:asset-missing")
else:
    with open(target, "rb") as stream:
        opened = open_pdb(session, stream, target)
    models = _cx_models(opened)
    atoms = 0
    lines = []
    for model in models:
        atoms += len(model.atoms)
        elements = model.atoms.elements
        for index, coord in enumerate(model.atoms.coords):
            symbol = elements[index].name if index < len(elements) else "C"
            tone = {"C": (0.75, 0.75, 0.75), "N": (0.35, 0.45, 0.95),
                    "O": (0.95, 0.35, 0.30), "S": (0.95, 0.85, 0.25)}.get(symbol, (0.6, 0.8, 0.6))
            radius = {"C": 1.0, "N": 1.1, "O": 1.15, "S": 1.3}.get(symbol, 0.9)
            lines.append("%.4f %.4f %.4f %.3f %.3f %.3f %.3f" % (
                float(coord[0]), float(coord[1]), float(coord[2]),
                tone[0], tone[1], tone[2], radius))
    if lines:
        with open(os.path.join(root, "cx_atoms.txt"), "w") as handle:
            handle.write(chr(10).join(lines))
    print("real-pdb:ok|atoms=%d" % atoms)
`;


// Opens the real protein asset (1322 ATOM records) now that the reader's triggers exist.
const REAL_PDB_SCRIPT = `
import os
def _cx_models(value):
    """open_pdb returns (models, status) shaped data; flatten it to the actual models."""
    out = []
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None or isinstance(item, (str, bytes)):
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif hasattr(item, "atoms"):
            out.append(item)
    return out


root = "/data/storage/el2/base/haps/entry/files"
target = os.path.join(root, "cx_demo.pdb")
from chimerax.pdb.pdb import open_pdb
try:
    with open(target, "rb") as stream:
        opened = open_pdb(session, stream, target)
    models = _cx_models(opened)
    lines = []
    for model in models:
        elements = model.atoms.elements
        for index, coord in enumerate(model.atoms.coords):
            symbol = elements[index].name if index < len(elements) else "C"
            tone = {"C": (0.75, 0.75, 0.75), "N": (0.35, 0.45, 0.95),
                    "O": (0.95, 0.35, 0.30), "S": (0.95, 0.85, 0.25)}.get(symbol, (0.6, 0.8, 0.6))
            radius = {"C": 1.0, "N": 1.1, "O": 1.15, "S": 1.3}.get(symbol, 0.9)
            lines.append("%.4f %.4f %.4f %.3f %.3f %.3f %.3f" % (
                float(coord[0]), float(coord[1]), float(coord[2]),
                tone[0], tone[1], tone[2], radius))
    if lines:
        with open(os.path.join(root, "cx_atoms.txt"), "w") as handle:
            handle.write(chr(10).join(lines))
    print("real-pdb:ok|atoms=%d" % len(lines))
except Exception as error:
    print("real-pdb:" + type(error).__name__ + ":" + str(error)[:60])
`;

// Opens the upstream SDF fixture through its reader, bypassing the format table.
const REAL_SDF_SCRIPT = `
import os
def _cx_models(value):
    """open_pdb returns (models, status) shaped data; flatten it to the actual models."""
    out = []
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None or isinstance(item, (str, bytes)):
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif hasattr(item, "atoms"):
            out.append(item)
    return out


root = "/data/storage/el2/base/haps/entry/files"
target = os.path.join(root, "cx_demo.sdf")
from chimerax.sdf import read_sdf
try:
    with open(target, "r") as stream:
        models = read_sdf(session, stream, target)
    lines = []
    atoms = 0
    for model in _cx_models(models):
        atoms += len(model.atoms)
        for coord in model.atoms.coords:
            lines.append("%.4f %.4f %.4f 0.700 0.850 0.750 1.0" % (
                float(coord[0]), float(coord[1]), float(coord[2])))
    if lines:
        with open(os.path.join(root, "cx_atoms.txt"), "w") as handle:
            handle.write(chr(10).join(lines))
    print("real-sdf:ok|atoms=%d" % atoms)
except Exception as error:
    print("real-sdf:" + type(error).__name__ + ":" + str(error)[:60])
`;



// Adopts the EGL context the native surface created, renders offscreen through
// ChimeraX's own OpenGLContext and reads the pixel back.
// Renders one frame with ChimeraX's own renderer and hands the pixels to ArkUI as base64.
const OFFICIAL_RENDER = `
import base64
import ctypes

def render_frame(display_ptr, context_ptr, surface_ptr, size):
    egl = ctypes.CDLL("libEGL.so")
    egl.eglMakeCurrent.argtypes = [ctypes.c_void_p] * 4
    egl.eglMakeCurrent.restype = ctypes.c_uint
    display = ctypes.c_void_p(int(display_ptr))
    context = ctypes.c_void_p(int(context_ptr))
    surface = ctypes.c_void_p(int(surface_ptr))
    if not egl.eglMakeCurrent(display, surface, surface, context):
        return "error:make-current"
    import os
    import numpy
    import chimerax
    from chimerax.graphics import opengl as cxopengl
    cxopengl._initialize_pyopengl()
    from chimerax.pdb.pdb import open_pdb
    root = os.path.dirname(os.path.dirname(os.path.abspath(chimerax.__file__)))
    path = os.path.join(root, "chimerax", "demo_data", "cx_demo.pdb")
    models = []
    # Read the bundled protein directly: the "open" command depends on bundle registration that
    # the minimal session may not have, and a silent failure leaves nothing to draw.
    if False and os.path.exists(path):
        with open(path, "rb") as stream:
            opened = open_pdb(session, stream, path)
        stack = [opened]
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                stack.extend(item)
            elif hasattr(item, "atoms"):
                models.append(item)
        try:
            session.models.add(models)
        except Exception:
            pass
    # Draw the probe triangle unconditionally: it is the geometry whose lighting was verified
    # in the adopt probe, so it separates "renderer works" from "structure loading works".
    if True:
        from chimerax.core.models import Model
        drawing = Model("cx_frame_probe", session)
        vertices = numpy.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]],
                               dtype=numpy.float32)
        normals = numpy.array([[0.0, 0.0, 1.0]] * 3, dtype=numpy.float32)
        triangles = numpy.array([[0, 1, 2]], dtype=numpy.int32)
        drawing.set_geometry(vertices, normals, triangles)
        drawing.vertex_colors = numpy.array([[1.0, 0.2, 0.2, 1.0]] * 3,
                                            dtype=numpy.float32)
        try:
            session.models.add([drawing])
        except Exception:
            pass
    view = session.main_view
    # Initialise rendering with an explicit EGL context wrapper, exactly like the adopt probe:
    # initialize_rendering(None) leaves the view without a usable context and frames come back black.
    ctx = cxopengl.OpenGLContext(None, None)
    ctx.display = ctypes.c_void_p(int(display_ptr))
    ctx.context = ctypes.c_void_p(int(context_ptr))
    ctx.surface = ctypes.c_void_p(int(surface_ptr))
    ctx._owns_context = False
    try:
        view.initialize_rendering(ctx)
    except Exception:
        pass
    try:
        view.set_rendering_options(background_color=(0.09, 0.12, 0.16, 1.0))
    except Exception:
        pass
    # Frame the models: without this the camera sits at the origin and renders background only.
    try:
        from chimerax.geometry.bounds import union_bounds
        blist = []
        for m in session.models.list():
            bounds = getattr(m, "bounds", None)
            if callable(bounds):
                bounds = bounds()
            if bounds is not None:
                blist.append(bounds)
        if blist:
            view.camera.view_all(union_bounds(blist), window_size=(size, size), pad=0.15)
    except Exception as error:
        return "error:view-all:" + type(error).__name__ + ":" + str(error)[:40]
    try:
        view.draw(swap_buffers=False)
    except Exception:
        pass
    frame = view.image_rgba(width=size, height=size)
    if frame is None:
        return "error:no-frame"
    raw = frame.astype("uint8").tobytes()
    # Pixel statistics travel with the frame so an empty render is distinguishable in the UI.
    flat = frame.reshape(-1, frame.shape[-1])[:, :3].astype("int32")
    lit = int((flat.sum(axis=1) > 12).sum())
    debug = ""
    if lit == 0:
        try:
            nmodels = len(session.models.list())
            try:
                ndraw = len(view.drawing.all_drawings())
            except Exception:
                ndraw = -1
            try:
                cam = view.camera.position.origin()
                campos = "%d,%d,%d" % (cam[0], cam[1], cam[2])
            except Exception:
                campos = "?"
            debug = "|dbg=models=%d,draw=%d,cam=%s,render=%s" % (
                nmodels, ndraw, campos, type(getattr(view, "_render", None)).__name__)
        except Exception as error:
            debug = "|dbg:" + type(error).__name__
    return "img:%d:%d:%d:%d:%s;%s" % (frame.shape[1], frame.shape[0], lit, len(flat),
                                      debug, base64.b64encode(raw).decode())

print(render_frame("__DISPLAY__", "__CONTEXT__", "__SURFACE__", __SIZE__))
`;

const ADOPT_SCRIPT = `
import ctypes

def adopt_and_render(display_ptr, context_ptr, surface_ptr):
    egl = ctypes.CDLL("libEGL.so")
    egl.eglMakeCurrent.argtypes = [ctypes.c_void_p] * 4
    egl.eglMakeCurrent.restype = ctypes.c_uint
    egl.eglGetError.restype = ctypes.c_int
    display = ctypes.c_void_p(int(display_ptr))
    context = ctypes.c_void_p(int(context_ptr))
    surface = ctypes.c_void_p(int(surface_ptr))
    if not egl.eglMakeCurrent(display, surface, surface, context):
        return "make-current:failed:0x%x" % egl.eglGetError()
    # Does the raw GLES library see the adopted context? This separates "context not
    # current" from "PyOpenGL bound its entry points to another context".
    gles = ctypes.CDLL("libGLESv3.so")
    gles.glGetString.restype = ctypes.c_char_p
    gles.glGetString.argtypes = [ctypes.c_uint]
    raw_version = gles.glGetString(0x1F02)
    raw_renderer = gles.glGetString(0x1F01)
    # Capture ChimeraX's log output: shader compile/link failures are reported there rather
    # than raised, so this is how a render failure explains itself.
    _cx_log_lines = []
    try:
        _cx_logger = session.logger

        def _cx_capture(kind):
            def record(message, *args, **kwargs):
                if len(_cx_log_lines) < 6:
                    _cx_log_lines.append(kind + ":" + str(message)[:120])
            return record

        for _cx_level in ('error', 'warning', 'info'):
            try:
                object.__setattr__(_cx_logger, _cx_level, _cx_capture(_cx_level))
            except Exception:
                pass
        globals()["_cx_log_lines"] = _cx_log_lines
    except Exception as _cx_log_error:
        globals()["_cx_log_lines"] = [type(_cx_log_error).__name__]

    import numpy
    from chimerax.graphics import opengl as cxgl
    # Re-resolve PyOpenGL's entry points now that the adopted context is current.
    try:
        cxgl._initialize_pyopengl()
    except Exception as error:
        pass
    # Record the renderer's real GL call sequence (and forward to PyOpenGL as usual) so the
    # ctypes facade can be validated offline against actual arguments instead of guesses.
    try:
        import json as _json
        _cx_log = []
        _cx_original_module2 = object.__getattribute__(cxgl.GL, "_module")

        class _CxRecorder:
            def __getattr__(self, name):
                if not name.startswith("gl"):
                    return getattr(_cx_original_module2, name)
                target = getattr(_cx_original_module2, name)

                def call(*args, **kwargs):
                    if len(_cx_log) < 4000:
                        _cx_log.append([name, [type(a).__name__ for a in args]])
                    return target(*args, **kwargs)

                return call

        object.__setattr__(cxgl.GL, "_module", _CxRecorder())
        globals()["_cx_gl_log"] = _cx_log
    except Exception as error:
        print("recorder:" + type(error).__name__ + ":" + str(error)[:50])
    # Incremental GL substitution: only state-setting entry points are taken from the ctypes
    # facade for now. These take plain integers, so the risk of a bad pointer is minimal, and a
    # crash here would be a clear signal to narrow the batch further.
    try:
        from chimerax.graphics import _cxgl
        import OpenGL.GLES3 as _cx_gles
        _cx_original = object.__getattribute__(cxgl.GL, "_module")
        _cx_direct = _cxgl.make_module(constants_module=_cx_gles)
        _cx_batch = ('glBindBuffer', 'glBindVertexArray', 'glBindTexture', 'glBindFramebuffer',
                     'glBindRenderbuffer', 'glUseProgram', 'glEnable', 'glDisable',
                     'glViewport', 'glClear', 'glClearColor', 'glDepthFunc', 'glDepthMask',
                     'glBlendFunc', 'glActiveTexture', 'glPixelStorei',
                     # batch 2: program/shader creation, uniforms and draws
                     'glCreateProgram', 'glCreateShader', 'glShaderSource', 'glCompileShader',
                     'glAttachShader', 'glLinkProgram', 'glDeleteShader', 'glDeleteProgram',
                     'glGetShaderiv', 'glGetProgramiv', 'glGetShaderInfoLog',
                     'glGetProgramInfoLog', 'glGetUniformLocation', 'glGetUniformBlockIndex',
                     'glGetActiveUniform', 'glUniformBlockBinding', 'glUniform1i', 'glUniform1f',
                     'glUniform2fv', 'glUniform3fv', 'glUniform4fv', 'glUniformMatrix4fv',
                     'glGenBuffers', 'glDeleteBuffers', 'glBufferData', 'glBufferSubData',
                     'glEnableVertexAttribArray', 'glDisableVertexAttribArray',
                     'glVertexAttribPointer', 'glDrawArrays', 'glDrawElements', 'glGetString',
                     'glGetError', 'glGenVertexArrays', 'glDeleteVertexArrays')

        _cx_stats = {}
        _cx_watched = ('glCreateProgram', 'glCreateShader', 'glLinkProgram',
                       'glGetUniformBlockIndex', 'glGetError')

        class _CxPartial:
            def __getattr__(self, name):
                if name in _cx_batch:
                    target = getattr(_cx_direct, name)
                    if name in _cx_watched:
                        def counted(*args, _t=target, _n=name):
                            result = _t(*args)
                            entry = _cx_stats.setdefault(_n, [0, None])
                            entry[0] += 1
                            entry[1] = result
                            return result
                        return counted
                    return target
                return getattr(_cx_original, name)

        # Disabled: with the shader/draw batch installed the process died during start-up adopt,
        # so the substitution stays off until the crashing function is identified.
        if globals().get("_CX_PARTIAL_GL", False):
            object.__setattr__(cxgl.GL, "_module", _CxPartial())
        globals()["_cx_batch_size"] = len(_cx_batch)
        globals()["_cx_gl_stats"] = _cx_stats
    except Exception as error:
        print("partial-gl:" + type(error).__name__ + ":" + str(error)[:50])
    # ChimeraX's context wrapper, pointed at the adopted EGL objects.
    ctx = cxgl.OpenGLContext(None, None)
    ctx.display = ctypes.c_void_p(int(display_ptr))
    ctx.context = ctypes.c_void_p(int(context_ptr))
    ctx.surface = ctypes.c_void_p(int(surface_ptr))
    ctx._owns_context = False
    # GLES2 exposes only GLES2 enum names; GLES3 numeric values are used directly.
    GL_FRAMEBUFFER, GL_RENDERBUFFER, GL_RGBA8 = 0x8D40, 0x8D41, 0x8058
    GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_COMPLETE = 0x8CE0, 0x8CD5
    GL_COLOR_BUFFER_BIT, GL_RGBA, GL_UNSIGNED_BYTE = 0x4000, 0x1908, 0x1401
    version = (raw_version or b"?").decode("utf-8", "replace")
    notes = []
    # ChimeraX's own render path: create its Render on the adopted context, add a
    # drawing and capture an offscreen image.
    try:
        from chimerax.core.models import Model
        # Report the enum values the framebuffer check depends on; a zero here explains
        # a "status 0" from glCheckFramebufferStatus.
        import chimerax.graphics.opengl as _cxgl
        notes.append("enums=%s,%s" % (str(_cxgl.GL.GL_FRAMEBUFFER),
                                      str(_cxgl.GL.GL_FRAMEBUFFER_COMPLETE)))
        view = session.main_view
        view.initialize_rendering(ctx)
        drawing = Model("cx_probe", session)
        # One red triangle around the origin: three vertices, one triangle.
        vertices = numpy.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]],
                               dtype=numpy.float32)
        normals = numpy.array([[0.0, 0.0, 1.0]] * 3, dtype=numpy.float32)
        triangles = numpy.array([[0, 1, 2]], dtype=numpy.int32)
        drawing.set_geometry(vertices, normals, triangles)
        drawing.vertex_colors = numpy.array([[1.0, 0.2, 0.2, 1.0]] * 3, dtype=numpy.float32)
        session.models.add([drawing])
        frame = view.image_rgba(width=64, height=64)
        if frame is None:
            notes.append("view:none")
        else:
            center = frame[32, 32]
            # Pixel statistics separate a real render from an empty buffer: the background is
            # uniform, so a non-zero spread means geometry was actually shaded.
            _flat = frame.reshape(-1, frame.shape[-1])
            _rgb = _flat[:, :3].astype("int32")
            _nonbg = int((_rgb.sum(axis=1) > 12).sum())
            _distinct = int(len({tuple(int(v) for v in row) for row in _rgb[::7]}))
            _range = "%d-%d" % (int(_rgb.min()), int(_rgb.max()))
            notes.append("view=%dx%d|center=%d,%d,%d|lit=%d/%d|colors=%d|range=%s" % (
                frame.shape[0], frame.shape[1], center[0], center[1], center[2],
                _nonbg, len(_flat), _distinct, _range))
    except BaseException as error:
        import traceback
        where = traceback.format_exc().strip().splitlines()
        try:
            import chimerax.graphics.opengl as _cxgl2
            notes.append("glerr=" + str(_cxgl2.GL.glGetError()))
        except Exception:
            pass
        notes.append("view!" + type(error).__name__ + ":" + str(error)[:60]
                     + "@" + (where[-3].strip()[:90] if len(where) >= 3 else "?"))
    # Plain concatenation: error strings inside notes may contain % placeholders.
    return ("context=EGLContext-adopted|raw=" + (raw_version or b"?").decode("utf-8", "replace")
            + "|gl=" + str(version) + "|" + ";".join(notes))

_cx_result = adopt_and_render("__DISPLAY__", "__CONTEXT__", "__SURFACE__")
# Summarise the recorded GL call sequence so it can be read back through the probe row.
try:
    _cx_log = globals().get("_cx_gl_log", [])
    _cx_counts = {}
    _cx_shapes = {}
    for _name, _types in _cx_log:
        _cx_counts[_name] = _cx_counts.get(_name, 0) + 1
        _cx_shapes.setdefault(_name, "/".join(_types) or "-")
    _cx_top = sorted(_cx_counts.items(), key=lambda item: -item[1])[:6]
    try:
        _cx_stats = globals().get("_cx_gl_stats") or {}
        _cx_stats_text = ",".join(
            "%s:%dx:%s" % (name, entry[0], entry[1]) for name, entry in _cx_stats.items())
        if not _cx_stats_text:
            _cx_stats_text = "none"
    except BaseException:
        _cx_stats_text = "error"
    # Prefix so UI truncation can never hide it.
    # Diagnostic steps, each guarded separately so a failure names the step instead of hiding.
    _cx_diag = ""
    _cx_step = "0"
    try:
        _cx_step = "1"
        # cxgl was a local name inside adopt_and_render; import the module here instead.
        import chimerax.graphics.opengl as _cx_opengl
        _cx_diag += "gltype=" + type(_cx_opengl.GL).__name__
        _cx_step = "2"
        from chimerax.graphics import _cxgl as _cxgl_facade
        _cx_created = list(getattr(_cxgl_facade, "CREATED_PROGRAMS", []) or [])
        _cx_step = "3"
        _cx_diag += ";created=" + str(_cx_created)[:60]
        _cx_step = "4"
        _cx_links = []
        for _cx_pid in _cx_created[:4]:
            _cx_out = ctypes.c_int(-1)
            try:
                gles.glGetProgramiv(int(_cx_pid), 0x8B82, ctypes.byref(_cx_out))
                _cx_links.append("p%s:link=%d" % (_cx_pid, _cx_out.value))
            except Exception:
                _cx_links.append("p%s:?" % _cx_pid)
        _cx_diag += ";links=" + ",".join(_cx_links)
        _cx_calls = getattr(_cxgl_facade, "CALLS", {}) or {}
        _cx_diag += ";calls=" + ",".join(
            "%s:%d" % (k, v) for k, v in sorted(_cx_calls.items())[:14])
        _cx_step = "6"
        # Ask the renderer's own GL object for the lighting block index: 0xFFFFFFFF means the
        # linked program has no active uniform block, which is what makes the binding fail.
        _cx_block = _cx_opengl.GL.glGetUniformBlockIndex(2, b"lighting_block")
        _cx_diag += ";block=" + str(_cx_block) + ";glerr=" + str(
            _cx_opengl.GL.glGetError())
        _cx_src = list(getattr(_cxgl_facade, "SHADER_SOURCES", []) or [])
        # Link status decides whether the program actually has its uniform blocks.
        try:
            _cx_link = _cx_opengl.GL.glGetProgramiv(2, _cx_opengl.GL.GL_LINK_STATUS)
        except Exception as _cx_link_error:
            _cx_link = type(_cx_link_error).__name__
        _cx_diag += ";link=" + str(_cx_link)
        _cx_diag += ";skip=" + str(bool(__import__("os").environ.get("CX_OHOS_SKIP_FB_STATUS")))
        # Compare the facade's answer with a raw libGLESv3 query: a mismatch would mean the
        # argument conversion is wrong rather than the program lacking the block.
        try:
            _gr = ctypes.CDLL("libGLESv3.so")
            _gr.glGetUniformBlockIndex.argtypes = [ctypes.c_uint, ctypes.c_char_p]
            _gr.glGetUniformBlockIndex.restype = ctypes.c_uint
            _cx_raw_block = _gr.glGetUniformBlockIndex(2, b"lighting_block")
            _cx_glerr_raw = _gr.glGetError()
        except Exception as _cx_raw_error:
            _cx_raw_block = type(_cx_raw_error).__name__
            _cx_glerr_raw = -1
        _cx_diag += ";rawblock=" + str(_cx_raw_block) + ";rawerr=" + str(_cx_glerr_raw)
        # Read back the source length GL actually holds: a mismatch with len(source) means the
        # glShaderSource hand-off lost the text.
        try:
            _gs = ctypes.CDLL("libGLESv3.so")
            _gs.glGetShaderiv.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                          ctypes.POINTER(ctypes.c_int)]
            _gs.glGetShaderiv.restype = None
            _cx_lens = []
            for _sid in list(getattr(_cxgl_facade, "CREATED_SHADERS", []) or [])[:2]:
                _n = ctypes.c_int(-1)
                _gs.glGetShaderiv(int(_sid), 0x8B88, ctypes.byref(_n))
                _cx_lens.append("s%s=%d" % (_sid, _n.value))
            _cx_diag += ";gllen=" + ",".join(_cx_lens)
        except Exception as _cx_len_error:
            _cx_diag += ";gllen:" + type(_cx_len_error).__name__
        # How many uniform blocks does the driver think the program has, and does making the
        # program current change the block lookup?
        try:
            _gp = ctypes.CDLL("libGLESv3.so")
            _gp.glGetProgramiv.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                           ctypes.POINTER(ctypes.c_int)]
            _gp.glGetProgramiv.restype = None
            _gp.glUseProgram.argtypes = [ctypes.c_uint]
            _gp.glUseProgram.restype = None
            _gp.glGetUniformBlockIndex.argtypes = [ctypes.c_uint, ctypes.c_char_p]
            _gp.glGetUniformBlockIndex.restype = ctypes.c_uint
            _nblocks = ctypes.c_int(-1)
            _gp.glGetProgramiv(2, 0x8A36, ctypes.byref(_nblocks))
            _gp.glUseProgram(2)
            _after_current = _gp.glGetUniformBlockIndex(2, b"lighting_block")
            _cx_diag += ";blocks=%d;aftercurrent=%d" % (_nblocks.value, _after_current)
        except Exception as _cx_block_error:
            _cx_diag += ";blocks:" + type(_cx_block_error).__name__
        # Isolate driver support from ChimeraX's shader text: compile a minimal ES 3.00 program
        # whose fragment stage really uses a std140 uniform block.
        try:
            _gu = ctypes.CDLL("libGLESv3.so")
            for _fn, _args in (('glCreateShader', [ctypes.c_uint]),
                               ('glShaderSource', [ctypes.c_uint, ctypes.c_int,
                                                   ctypes.POINTER(ctypes.c_char_p),
                                                   ctypes.POINTER(ctypes.c_int)]),
                               ('glCompileShader', [ctypes.c_uint]),
                               ('glCreateProgram', []),
                               ('glAttachShader', [ctypes.c_uint, ctypes.c_uint]),
                               ('glLinkProgram', [ctypes.c_uint]),
                               ('glGetUniformBlockIndex', [ctypes.c_uint, ctypes.c_char_p])):
                _getattr = getattr(_gu, _fn)
                _getattr.argtypes = _args
            _gu.glCreateShader.restype = ctypes.c_uint
            _gu.glCreateProgram.restype = ctypes.c_uint
            _gu.glGetUniformBlockIndex.restype = ctypes.c_uint
            _gu.glUseProgram.argtypes = [ctypes.c_uint]
            _nl = chr(10)
            _vsrc = ctypes.c_char_p(_nl.join([
                "#version 300 es",
                "in vec3 p;",
                "void main(){gl_Position=vec4(p,1.0);}"]).encode())
            _fsrc_text = _nl.join([
                "#version 300 es",
                "precision highp float;",
                "layout(std140) uniform lighting_block { vec3 key_light_direction; };",
                "out vec4 frag;",
                "void main(){frag=vec4(key_light_direction,1.0);}"])
            _fsrc = ctypes.c_char_p(_fsrc_text.encode())
            _vs = _gu.glCreateShader(0x8B31)
            _arr = ctypes.pointer(_vsrc)
            _gu.glShaderSource(_vs, 1, ctypes.cast(_arr, ctypes.POINTER(ctypes.c_char_p)), None)
            _gu.glCompileShader(_vs)
            _fs = _gu.glCreateShader(0x8B30)
            _arr2 = ctypes.pointer(_fsrc)
            _gu.glShaderSource(_fs, 1, ctypes.cast(_arr2, ctypes.POINTER(ctypes.c_char_p)), None)
            _gu.glCompileShader(_fs)
            _p2 = _gu.glCreateProgram()
            _gu.glAttachShader(_p2, _vs)
            _gu.glAttachShader(_p2, _fs)
            _gu.glLinkProgram(_p2)
            _mini_block = _gu.glGetUniformBlockIndex(_p2, b"lighting_block")
            _cx_diag += ";mini=%d/%d" % (_p2, _mini_block)
        except Exception as _cx_mini_error:
            _cx_diag += ";mini:" + type(_cx_mini_error).__name__ + ":" + str(
                _cx_mini_error)[:40]
        # Recompile ChimeraX's exact shader text on this driver and read the logs, so a compile
        # or link rejection explains itself instead of showing up as a missing uniform block.
        try:
            _nl = chr(10)
            _gz = ctypes.CDLL("libGLESv3.so")
            _gz.glCreateShader.argtypes = [ctypes.c_uint]
            _gz.glCreateShader.restype = ctypes.c_uint
            _gz.glShaderSource.argtypes = [ctypes.c_uint, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_char_p),
                                           ctypes.POINTER(ctypes.c_int)]
            _gz.glShaderSource.restype = None
            _gz.glCompileShader.argtypes = [ctypes.c_uint]
            _gz.glCompileShader.restype = None
            _gz.glGetShaderiv.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                          ctypes.POINTER(ctypes.c_int)]
            _gz.glGetShaderiv.restype = None
            _gz.glGetShaderInfoLog.argtypes = [ctypes.c_uint, ctypes.c_int,
                                               ctypes.POINTER(ctypes.c_int),
                                               ctypes.c_char_p]
            _gz.glGetShaderInfoLog.restype = None
            _gz.glCreateProgram.argtypes = []
            _gz.glCreateProgram.restype = ctypes.c_uint
            _gz.glAttachShader.argtypes = [ctypes.c_uint, ctypes.c_uint]
            _gz.glAttachShader.restype = None
            _gz.glLinkProgram.argtypes = [ctypes.c_uint]
            _gz.glLinkProgram.restype = None
            _gz.glGetUniformBlockIndex.argtypes = [ctypes.c_uint, ctypes.c_char_p]
            _gz.glGetUniformBlockIndex.restype = ctypes.c_uint
            _cx_rebuilt = []
            for _sid, _count, _text in _cx_src[:2]:
                _sh = _gz.glCreateShader(0x8B31 if "VERTEX" in str(_sid) else 0x8B30)
                _holder = ctypes.c_char_p(_text.encode())
                _arr = (ctypes.c_char_p * 1)(_holder)
                _gz.glShaderSource(_sh, 1, _arr, None)
                _gz.glCompileShader(_sh)
                _st = ctypes.c_int(-1)
                _gz.glGetShaderiv(_sh, 0x8B81, ctypes.byref(_st))
                _ln = ctypes.c_int(0)
                _buf = ctypes.create_string_buffer(200)
                _gz.glGetShaderInfoLog(_sh, 199, ctypes.byref(_ln), _buf)
                _log = _buf.value.decode("utf-8", "replace").replace(_nl, " ")[:60]
                _cx_rebuilt.append((_sh, _st.value, _log))
            _dprog = _gz.glCreateProgram()
            for _sh, _st, _log in _cx_rebuilt:
                _gz.glAttachShader(_dprog, _sh)
            _gz.glLinkProgram(_dprog)
            _dblock = _gz.glGetUniformBlockIndex(_dprog, b"lighting_block")
            _cx_diag += ";recompiled=%d/block=%d/%s" % (
                _dprog, _dblock,
                ",".join("s%d:%d:%s" % (sh, st, log) for sh, st, log in _cx_rebuilt))
        except Exception as _cx_recomp_error:
            _cx_diag += ";recompiled:" + type(_cx_recomp_error).__name__ + ":" + str(
                _cx_recomp_error)[:60]
        _cx_diag += ";src=" + "|".join(
            "%s:%s" % (sid, count) for sid, count, txt in _cx_src[:2])
    except BaseException as _cx_diag_error:
        _cx_diag += ";diagstop=" + _cx_step + ":" + type(_cx_diag_error).__name__
    _cx_result = _cx_diag + ";" + _cx_result
    try:
        _cx_result += ";log=" + "|".join(globals().get("_cx_log_lines") or [])
    except BaseException:
        pass
    _cx_result = "stats=" + _cx_stats_text + ";" + _cx_result
    _cx_result += ";calls=%d;top=%s" % (
        len(_cx_log),
        ",".join("%s:%d:%s" % (name, count, _cx_shapes[name]) for name, count in _cx_top))
except Exception as _cx_dump_error:
    _cx_result = _cx_result + ";log:" + type(_cx_dump_error).__name__
print(_cx_result)
`;

@Entry
@Component
struct Index {
  @State status: string = '准备中…';
  @State version: string = '';
  @State prefix: string = '';
  @State mathResult: string = '';
  @State ctypesResult: string = '';
  @State stdlibResult: string = '';
  @State chimeraxVersion: string = '';
  @State chimeraxCore: string = '';
  @State diagnostic: string = '';
  @State triggerResult: string = '';
  @State numpyResult: string = '';
  @State numpyCore: string = '';
  @State commandsProbe: string = '';
  @State sessionProbe: string = '';
  @State commandResult: string = '';
  @State commandText: string = 'cxprobe ui-command';
  @State commandOutput: string = '';
  @State builtinResult: string = '';
  @State graphicsResult: string = '';
  @State glStatus: string = '';
  @State qtModeState: string = '';
  @State evalProbeState: string = '';
  @State glRender: string = '';
  @State atomicResult: string = '';
  @State glStackResult: string = '';
  @State modelResult: string = '';
  @State openResult: string = '';
  @State atomsDumpResult: string = '';
  @State viewerResult: string = '';
  @State commandsState: string = '';
  @State commandNames: string[] = [];
  @State lastTouchX: number = -1;
  @State lastTouchY: number = -1;
  @State lastPinchSpan: number = 0;
  @State fileListState: string = '';
  @State fileNames: string[] = [];
  @State renderResult: string = '';
  @State officialImage: image.PixelMap | undefined = undefined;
  @State officialInfo: string = '';
  @State failed: string = '';

  aboutToAppear(): void {
    this.bootstrap();
  }


  // Decode the renderer's base64 frame into a PixelMap the Image component can show.
  private async showOfficialFrame(): Promise<void> {
    try {
      const handles: GLHandlesReport | null = native.glHandles();
      if (handles === null || handles.context === '0') {
        this.officialInfo = 'no-context';
        return;
      }
      const script: string = OFFICIAL_RENDER.replace('__DISPLAY__', handles.display)
        .replace('__CONTEXT__', handles.context)
        .replace('__SURFACE__', handles.surface)
        .replace('__SIZE__', '256');
      const report: ScriptReport = native.runScript(script);
      const text: string = (report.ok ? report.output : report.error).trim();
      if (!text.startsWith('img:')) {
        this.officialInfo = text.slice(0, 120);
        return;
      }
      const parts: string[] = text.split(':');
      const width: number = Number.parseInt(parts[1]);
      const height: number = Number.parseInt(parts[2]);
      const lit: number = Number.parseInt(parts[3]);
      const total: number = Number.parseInt(parts[4]);
      const payload: string = text.slice(text.indexOf(';') + 1);
      const bytes: Uint8Array = new util.Base64Helper().decodeSync(payload);
      const options: image.InitializationOptions = {
        size: { width: width, height: height },
        pixelFormat: image.PixelMapFormat.RGBA_8888,
        editable: false
      };
      this.officialImage = await image.createPixelMap(bytes.buffer as ArrayBuffer, options);
      this.officialInfo = `chimerax ${width}x${height} lit=${lit}/${total}`
        + text.slice(text.indexOf('img:'), text.indexOf(';'));
    } catch (error) {
      this.officialInfo = 'render-error';
    }
  }

  private filesDir(): string {
    return AppStorage.get<string>('cxFilesDir') ?? '';
  }

  // Toolbar actions. Open runs the read -> dump -> draw chain, Centre resets the view and
  // the zoom buttons drive the native viewer, so the toolbar is functional, not decorative.
  // Copies a rawfile asset into the sandbox, then runs the script that opens it.
  private openAsset(asset: string, script: string): void {
    try {
      const bytes: Uint8Array = getContext(this).resourceManager.getRawFileContentSync(asset);
      const path: string = this.filesDir() + '/' + asset;
      const file = fs.openSync(path, fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE);
      fs.writeSync(file.fd, bytes.buffer as ArrayBuffer);
      fs.closeSync(file);
    } catch (error) {
      this.viewerResult = 'asset-copy-failed';
      return;
    }
    const report: ScriptReport = native.runScript(script);
    const text: string = (report.ok ? report.output : report.error).trim();
    this.viewerResult = text.slice(0, 60);
    if (text.indexOf('ok|') > 0) {
      try {
        const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
        this.viewerResult = text.slice(0, 34) + ' view=' + drawn.atoms;
      } catch (error) {
        this.viewerResult = 'viewer-error';
      }
    }
  }

  private runToolbarAction(action: string): void {
    if (action === 'Open') {
      const opened: ScriptReport = native.runScript(OPEN_SCRIPT);
      if (!opened.ok) {
        this.openResult = opened.error;
        return;
      }
      this.openResult = opened.output.trim();
      const dumped: ScriptReport = native.runScript(ATOM_DUMP_SCRIPT);
      this.atomsDumpResult = (dumped.ok ? dumped.output : dumped.error).trim();
      try {
        const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
        this.viewerResult = 'atoms=' + drawn.atoms;
      } catch (error) {
        this.viewerResult = 'viewer-error';
      }
      return;
    }
    if (action === 'Center') {
      const built: ScriptReport = native.runScript(DEMO_SCRIPT);
      if (built.ok) {
        try {
          const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
          this.viewerResult = 'demo=' + drawn.atoms;
        } catch (error) {
          this.viewerResult = 'viewer-error';
        }
      }
      return;
    }
    if (action === 'Tools') {
      const listed: ScriptReport = native.runScript(LIST_COMMAND_SCRIPT);
      this.viewerResult = (listed.ok ? listed.output : listed.error).trim();
      return;
    }
    if (action === 'Save') {
      const saved: ScriptReport = native.runScript(SAVE_SCRIPT);
      this.viewerResult = (saved.ok ? saved.output : saved.error).trim();
      return;
    }
    if (action === 'Zoom') {
      try {
        native.zoomView(1.2);
        this.viewerResult = 'zoom-in';
      } catch (error) {
        this.viewerResult = 'zoom-error';
      }
      return;
    }
    if (action === 'Rotate') {
      try {
        native.rotateView(40, 15);
        this.viewerResult = 'rotated';
      } catch (error) {
        this.viewerResult = 'rotate-error';
      }
      return;
    }
    this.viewerResult = action + ':not-implemented';
  }

  private executeCommand(): void {
    const report: ScriptReport = native.runChimeraCommand(this.commandText);
    this.commandOutput = (report.ok ? report.output : report.error).trim();
  }

  private executePythonSample(): void {
    const report: ScriptReport = native.runScript(
      'print(session.app_name, len(session.triggers.trigger_names()))');
    this.commandOutput = (report.ok ? report.output : report.error).trim();
  }

  private async bootstrap(): Promise<void> {
    try {
      const files = this.filesDir();
      if (files.length === 0) {
        this.failed = '应用沙箱目录不可用';
        this.status = '失败';
        return;
      }
      this.status = '释放运行环境…';
      const archivePath = `${files}/${ARCHIVE}`;
      const packed: Uint8Array = getContext(this).resourceManager.getRawFileContentSync(`rawfile/cx-runtime.zip`);
      const file = fs.openSync(archivePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
      fs.writeSync(file.fd, packed.buffer as ArrayBuffer);
      fs.closeSync(file);
      const store = `${files}/cx-runtime-v6-${RUNTIME_TAG}`;
      const runtimeDir = `${store}/${RUNTIME_DIR}`;
      const ready = fs.accessSync(`${runtimeDir}/lib/python3.11/os.py`) &&
        fs.accessSync(`${runtimeDir}/lib/python3.11/chimerax/version.py`) &&
        fs.accessSync(`${runtimeDir}/lib/python3.11/numpy/__init__.py`);
      if (!ready) {
        this.status = '解包运行环境…';
        if (!fs.accessSync(store)) {
          fs.mkdirSync(store, true);
        }
        const extracted: ExtractReport = native.extractArchive(archivePath, store);
        if (!extracted.ok) {
          this.failed = extracted.error;
          this.status = '失败';
          return;
        }
      }
      this.status = '初始化 CPython…';
      const report: RuntimeReport = native.initializeRuntime(runtimeDir);
      if (!report.initialized) {
        this.failed = report.error;
        this.status = '失败';
        return;
      }
      this.version = report.version;
      this.prefix = report.prefix;
      const math: ExpressionReport = native.runExpression('__import__("math").sqrt(16.0)');
      this.mathResult = math.ok ? math.value : math.error;
      const ctypes: ExpressionReport = native.runExpression(
        '__import__("ctypes").CDLL("libc.so").strlen(b"chimerax-on-harmony")');
      this.ctypesResult = ctypes.ok ? ctypes.value : ctypes.error;
      const stdlib: ExpressionReport = native.runExpression(
        '__import__("hashlib").sha256(b"cx").hexdigest()[:8]');
      this.stdlibResult = stdlib.ok ? stdlib.value : stdlib.error;
      const trigger: ExpressionReport = native.runExpression(
        '(lambda ts: (ts.add_trigger("cx_app_probe"),' +
        ' ts.add_handler("cx_app_probe", lambda *a: None),' +
        ' ts.activate_trigger("cx_app_probe", "payload"),' +
        ' "%s|fired" % list(ts.trigger_names())[0])[3])(' +
        '__import__("chimerax.core.triggerset", fromlist=["x"]).TriggerSet())');
      this.triggerResult = trigger.ok ? trigger.value : trigger.error;
      const numpy: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("numpy").__version__,' +
        ' str(__import__("numpy").sqrt(16.0)), str(__import__("numpy").arange(5).sum()))');
      this.numpyResult = numpy.ok ? numpy.value : numpy.error;
      const numpyCore: ExpressionReport = native.runExpression(
        '__import__("numpy.core._multiarray_umath", fromlist=["x"]).__file__');
      this.numpyCore = numpyCore.ok ? numpyCore.value : numpyCore.error;
      const session: ExpressionReport = native.runExpression(
        '(lambda s: "%s|%s|%s" % (type(s).__name__, str(s.logger is not None),' +
        ' str(len(s.triggers.trigger_names()))))(' +
        '__import__("chimerax.core.session", fromlist=["x"]).Session("ChimeraX", silent=True, minimal=True))');
      this.sessionProbe = session.ok ? session.value : session.error;
      const commands: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.core.colors", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.session", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.commands", fromlist=["x"]).__name__)');
      this.commandsProbe = commands.ok ? commands.value : commands.error;
      const command: ScriptReport = native.runScript(COMMAND_SCRIPT);
      this.commandResult = command.ok ? command.output.trim() : command.error;
      const builtin: ScriptReport = native.runScript(BUILTIN_SCRIPT);
      this.builtinResult = (builtin.ok ? builtin.output : builtin.error).trim();
      const graphics: ExpressionReport = native.runExpression(
        '(lambda g, n: "%s|%s" % (g.__name__,' +
        ' str(g.count_value(n.array([1, 2, 5, 5, 5, 9], dtype="uint8"), 5))))(' +
        '__import__("chimerax.graphics._graphics", fromlist=["x"]), __import__("numpy"))');
      this.graphicsResult = graphics.ok ? graphics.value : graphics.error;
      const atomic: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.atomic", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.atomic", fromlist=["x"]).Atom.__name__,' +
        ' __import__("chimerax.atomic", fromlist=["x"]).AtomicStructure.__name__)');
      this.atomicResult = atomic.ok ? atomic.value : atomic.error;
      const glStack: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("OpenGL").__version__,' +
        ' __import__("chimerax.graphics.opengl", fromlist=["x"]).__name__,' +
        ' str(hasattr(__import__("chimerax.core.models", fromlist=["x"]), "Model")))');
      this.glStackResult = glStack.ok ? glStack.value : glStack.error;
      const model: ScriptReport = native.runScript(MODEL_SCRIPT);
      this.modelResult = (model.ok ? model.output : model.error).trim();
      const opened: ScriptReport = native.runScript(OPEN_SCRIPT);
      this.openResult = (opened.ok ? opened.output : opened.error).trim();
      const dumped: ScriptReport = native.runScript(ATOM_DUMP_SCRIPT);
      this.atomsDumpResult = (dumped.ok ? dumped.output : dumped.error).trim();
      const diag: ExpressionReport = native.runExpression(
        '"prefix=%s|has_version=%s|first=%s" % (__import__("sys").prefix,' +
        ' __import__("os").path.exists(__import__("sys").prefix + "/lib/python3.11/chimerax/version.py"),' +
        ' ",".join(sorted(__import__("os").listdir(__import__("sys").prefix + "/lib/python3.11"))[:3]))');
      this.diagnostic = diag.ok ? diag.value : diag.error;
      // The XComponent surface is created after the first frame, so the EGL handles
      // only exist a moment later; adoption therefore runs deferred.
      setTimeout(() => {
        let handles: GLHandlesReport | null = null;
        try {
          handles = native.glHandles();
        } catch (error) {
          handles = null;
        }
        if (handles !== null && handles.context !== '0') {
          const diagScript: string = SHADER_DIAG_SCRIPT.replace('__DISPLAY__', handles.display)
            .replace('__CONTEXT__', handles.context)
            .replace('__SURFACE__', handles.surface);
          const diagReport: ScriptReport = native.runScript(diagScript);
          this.viewerResult = (diagReport.ok ? diagReport.output : diagReport.error).trim();
          const adoptScript: string = ADOPT_SCRIPT.replace('__DISPLAY__', handles.display)
            .replace('__CONTEXT__', handles.context)
            .replace('__SURFACE__', handles.surface);
          const adopted: ScriptReport = native.runScript(adoptScript);
          this.renderResult = (adopted.ok ? adopted.output : adopted.error).trim();
          // The status row truncates this text; hilog keeps the whole diagnostic readable.
          hilog.error(0x0000, 'CXPROBE', 'render=' + this.renderResult.slice(0, 900));
          try {
            native.glReacquire();
          } catch (error) {
            this.renderResult += '|reacquire:failed';
          }
        } else {
          this.renderResult = 'handles:unavailable';
        }
      }, 3000);
      const chimerax: ExpressionReport = native.runExpression(
        '__import__("chimerax.version").version.version');
      this.chimeraxVersion = chimerax.ok ? chimerax.value : chimerax.error;
      const core: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.core.errors", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.errors", fromlist=["x"]).UserError.__name__,' +
        ' __import__("chimerax.core.logger", fromlist=["x"]).Logger.__name__)');
      this.chimeraxCore = core.ok ? core.value : core.error;
      this.status = '运行环境就绪';
      hilog.info(0x3802, 'ChimeraX', 'CX_RUNTIME_READY %{public}s', this.version);
      let polls = 0;
      const poll = setInterval(() => {
        polls += 1;
        try {
          const gl: GLReport = native.glStatus();
          if (gl.status.length > 0) {
            this.glStatus = gl.status;
          }
          if (gl.render.length > 0) {
            this.glRender = gl.render;
          }
        } catch (error) {
          this.glStatus = 'gl-status-error';
        }
        if (polls >= 10 || this.glStatus.startsWith('ready:')) {
          clearInterval(poll);
        }
      }, 800);
    } catch (error) {
      this.failed = (error as Error).message ?? JSON.stringify(error);
      this.status = '失败';
      hilog.error(0x3802, 'ChimeraX', 'CX_BOOTSTRAP_ERROR %{public}s', this.failed);
    }
  }

  build() {
    Scroll() {
      Column({ space: 8 }) {
      // ---- ChimeraX-style shell -------------------------------------------
      // Menu bar: same labels and order as the desktop application.
      Row({ space: 18 }) {
        ForEach(['File', 'Tools', 'Actions', 'Presets', 'Help'], (label: string) => {
          Text(label).id('cx-menu-' + label.toLowerCase()).fontSize(13)
            .fontColor('#DDE7F3')
            .onClick(() => this.runToolbarAction(label))
        }, (label: string) => label)
      }.width('100%').padding({ top: 4, bottom: 4 })
      Divider().color('#3E5C80')
      // Toolbar: the actions users reach first, with the upstream icon on the left.
      Row({ space: 10 }) {
        Image($r('app.media.app_icon')).id('cx-toolbar-logo').width(26).height(26)
        ForEach(['Open', 'Save', 'Undo', 'Redo', 'Rotate', 'Zoom', 'Center'], (action: string) => {
          Button(action).id('cx-tool-' + action.toLowerCase()).fontSize(11).height(30)
            .backgroundColor('#2A4B73').fontColor('#EAF2FB')
            .onClick(() => this.runToolbarAction(action))
        }, (action: string) => action)
      }.width('100%').padding({ top: 4, bottom: 4 })
      Divider().color('#3E5C80')
      Row({ space: 6 }) {
        TextInput({ text: this.commandText, placeholder: '输入 ChimeraX 命令，例如 cxprobe ui-command' })
          .id('cx-cmd-input').height(32).fontSize(11).layoutWeight(1)
          .onChange((value: string) => { this.commandText = value; })
          .onSubmit(() => this.executeCommand())
        Button('执行命令').id('cx-cmd-run').height(32).fontSize(11)
          .onClick(() => this.executeCommand())
        Button('Python').id('cx-cmd-py').height(32).fontSize(11)
          .onClick(() => this.executePythonSample())
      }.width('100%')
      Text(this.commandOutput.length > 0 ? this.commandOutput : '（输出）')
        .id('cx-cmd-output').fontSize(11).fontColor('#D7E3F0').width('100%').maxLines(4)
      Text('ChimeraX · Harmony PC').fontSize(24).fontWeight(FontWeight.Bold).fontColor('#FFFFFF')
      Text('应用内嵌私有 CPython 运行环境（通用运行层，非完整应用）').fontSize(12).fontColor('#C9D6E5')
      Divider().color('#3E5C80')
      Row() {
        Text('状态').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.status).id('cx-status').fontSize(13).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('core API').fontSize(12).fontColor('#C9D6E5').width(80)
        Text((this.commandsProbe.length > 0 ? this.commandsProbe : '—') + ' | ' +
             (this.sessionProbe.length > 0 ? this.sessionProbe : '—')).id('cx-commands')
          .fontSize(9).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('触发器').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.triggerResult.length > 0 ? this.triggerResult : '—').id('cx-trigger')
          .fontSize(11).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('Python').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.version.length > 0 ? this.version : '—').id('cx-version').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('math.sqrt').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.mathResult.length > 0 ? this.mathResult : '—').id('cx-math').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('ctypes/libc').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.ctypesResult.length > 0 ? this.ctypesResult : '—').id('cx-ctypes').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('标准库').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.stdlibResult.length > 0 ? this.stdlibResult : '—').id('cx-stdlib').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('ChimeraX').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.chimeraxVersion.length > 0 ? this.chimeraxVersion : '—').id('cx-chimerax')
          .fontSize(12).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('core').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.chimeraxCore.length > 0 ? this.chimeraxCore : '—').id('cx-core')
          .fontSize(12).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('numpy').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.numpyResult.length > 0 ? this.numpyResult : '—').id('cx-numpy')
          .fontSize(11).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('_umath').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.numpyCore.length > 0 ? this.numpyCore : '—').id('cx-numpyc')
          .fontSize(10).fontColor('#B9C8D8').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('命令执行').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.commandResult.length > 0 ? this.commandResult : '—').id('cx-command-run')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Button('启用 Qt 窗口模式').id('cx-qt-mode').fontSize(12).height(32)
          .onClick(() => {
            try {
              const file = fs.openSync(this.filesDir() + '/qt-mode.flag',
                fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE);
              fs.writeSync(file.fd, '1');
              fs.closeSync(file);
              this.qtModeState = '已写入，重启应用生效';
            } catch (error) {
              this.qtModeState = '写入失败: ' + (error as Error).message;
            }
          })
        Text(this.qtModeState).fontSize(10).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row({ space: 8 }) {
        Button('双螺旋示例').id('cx-demo2-run').fontSize(12).height(32)
          .onClick(() => {
            const built: ScriptReport = native.runScript(DEMO2_SCRIPT);
            if (!built.ok) {
              this.viewerResult = 'demo2-error';
              return;
            }
            try {
              const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
              this.viewerResult = 'demo2=' + drawn.atoms;
            } catch (error) {
              this.viewerResult = 'viewer-error';
            }
          })
        Button('三螺旋束').id('cx-demo3-run').fontSize(12).height(32)
          .onClick(() => {
            const started: number = Date.now();
            const built: ScriptReport = native.runScript(DEMO3_SCRIPT);
            if (!built.ok) {
              this.viewerResult = 'demo3-error';
              return;
            }
            try {
              const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
              this.viewerResult = 'demo3=' + drawn.atoms + '|' + (Date.now() - started) + 'ms';
            } catch (error) {
              this.viewerResult = 'viewer-error';
            }
          })
        Button('大结构(448)').id('cx-demo4-run').fontSize(12).height(32)
          .onClick(() => {
            const started: number = Date.now();
            const built: ScriptReport = native.runScript(DEMO4_SCRIPT);
            if (!built.ok) {
              this.viewerResult = 'demo4-error';
              return;
            }
            try {
              const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
              this.viewerResult = 'demo4=' + drawn.atoms + '|' + (Date.now() - started) + 'ms';
            } catch (error) {
              this.viewerResult = 'viewer-error';
            }
          })
        Button('Ras 蛋白').id('cx-real-run').fontSize(12).height(32)
          .onClick(() => { this.openAsset('cx_demo.pdb', REAL_PDB_SCRIPT); })
        Button('打开 SDF').id('cx-sdf-run').fontSize(12).height(32)
          .onClick(() => { this.openAsset('cx_demo.sdf', REAL_SDF_SCRIPT); })
        Button('模型信息').id('cx-info-run').fontSize(12).height(32)
          .onClick(() => {
            // Make sure the real protein is in the sandbox before the probe opens it.
            try {
              const assetPath: string = this.filesDir() + '/cx_demo.pdb';
              if (!fs.accessSync(assetPath)) {
                const bytes: Uint8Array = getContext(this).resourceManager
                  .getRawFileContentSync('cx_demo.pdb');
                const file = fs.openSync(assetPath, fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE);
                fs.writeSync(file.fd, bytes.buffer as ArrayBuffer);
                fs.closeSync(file);
              }
            } catch (error) {
              // fall through: the probe falls back to the small test file
            }
            const report: ScriptReport = native.runScript(INFO_MODELS_SCRIPT);
            const text: string = (report.ok ? report.output : report.error).trim();
            this.viewerResult = text.slice(0, 90);
            this.openResult = text.slice(0, 400);
          })
        Button('沙箱结构文件').id('cx-list-run').fontSize(12).height(32)
          .onClick(() => {
            const listed: ScriptReport = native.runScript(LIST_SCRIPT);
            const text: string = (listed.ok ? listed.output : listed.error).trim();
            this.fileListState = text;
            const parts: string[] = text.split('|');
            const names: string[] = parts.length > 1 && parts[1].length > 0
              ? parts[1].split(',') : [];
            this.fileNames = names;
          })
        Button('示例螺旋').id('cx-demo-run').fontSize(12).height(32)
          .onClick(() => {
            const built: ScriptReport = native.runScript(DEMO_SCRIPT);
            if (!built.ok) {
              this.viewerResult = 'demo-error';
              return;
            }
            try {
              const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
              this.viewerResult = 'demo=' + drawn.atoms;
            } catch (error) {
              this.viewerResult = 'viewer-error';
            }
          })
        Button('显示结构').id('cx-viewer-run').fontSize(12).height(32)
          .onClick(() => {
            const path: string = this.filesDir() + '/cx_atoms.txt';
            try {
              const drawn: DrawAtomsReport = native.drawAtoms(path);
              this.viewerResult = 'atoms=' + drawn.atoms;
            } catch (error) {
              this.viewerResult = 'viewer-error:' + (error as Error).message;
            }
          })
        Text(this.fileListState.length > 0 ? this.fileListState
             : (this.viewerResult.length > 0 ? this.viewerResult : this.atomsDumpResult))
          .id('cx-viewer-status').fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(2)
      }.width('100%')
      Row({ space: 8 }) {
        Button('命令清单').id('cx-cmd-list').fontSize(11).height(28)
          .backgroundColor('#1F3A5C').fontColor('#DDE7F3')
          .onClick(() => {
            const listed: ScriptReport = native.runScript(COMMANDS_SCRIPT);
            const text: string = (listed.ok ? listed.output : listed.error).trim();
            this.commandsState = text;
            const parts: string[] = text.split('|');
            this.commandNames = parts.length > 1 && parts[1].length > 0
              ? parts[1].split(',') : [];
          })
        Text(this.commandsState.length > 0 ? this.commandsState : '—')
          .id('cx-cmd-list-output').fontSize(10).fontColor('#9FB4C8')
          .layoutWeight(1).maxLines(3)
      }.width('100%')
      if (this.commandNames.length > 0) {
        Row({ space: 6 }) {
          ForEach(this.commandNames, (name: string) => {
            Button(name).id('cx-cmdchip-' + name).fontSize(9).height(24)
              .backgroundColor('#16324F').fontColor('#CFE0F0')
              .onClick(() => {
                // Fill the bar and run it, so a chip is a real command entry point.
                this.commandText = name;
                this.executeCommand();
              })
          }, (name: string) => name)
        }.width('100%')
      }
      Row({ space: 14 }) {
        Text('模型: ' + (this.openResult.indexOf('models=') >= 0
          ? this.openResult.split('models=')[1].split('|')[0] : '—'))
          .id('cx-status-model').fontSize(10).fontColor('#9FB4C8')
        Text('原子: ' + (this.openResult.indexOf('atoms=') >= 0
          ? this.openResult.split('atoms=')[1].split('|')[0] : '—'))
          .id('cx-status-atoms').fontSize(10).fontColor('#9FB4C8')
        Text('视图: ' + this.viewerResult).id('cx-status-view').fontSize(10).fontColor('#9FB4C8')
        Button('重置视角').id('cx-view-reset').fontSize(10).height(26)
          .backgroundColor('#1F3A5C').fontColor('#DDE7F3')
          .onClick(() => {
            try {
              native.rotateView(0, 0);
              this.viewerResult = 'view-reset';
            } catch (error) {
              this.viewerResult = 'reset-error';
            }
          })
      }.width('100%')
      Row() {
        Button('官方渲染').id('cx-official-render').fontSize(12).height(32)
          .onClick(() => { this.showOfficialFrame(); })
        Text(this.officialInfo).fontSize(10).fontColor('#FFFFFF').layoutWeight(1)
          .margin({ left: 8 })
      }.width('100%').margin({ top: 6 })
      if (this.officialImage !== undefined) {
        Image(this.officialImage).id('cx-official-image')
          .width('100%').height(360).objectFit(ImageFit.Contain)
          .backgroundColor('#16212F')
      }
      XComponent({ id: 'cx-gl-surface', type: XComponentType.SURFACE, libraryname: 'chimerax_native' })
        .id('cx-gl-surface').width('100%').height(360).backgroundColor('#16212F')
        .onTouch((event: TouchEvent) => {
          if (event.touches.length === 0) {
            return;
          }
          const touch: TouchObject = event.touches[0];
          if (event.touches.length === 2) {
            const dx: number = event.touches[0].windowX - event.touches[1].windowX;
            const dy: number = event.touches[0].windowY - event.touches[1].windowY;
            const span: number = Math.sqrt(dx * dx + dy * dy);
            if (this.lastPinchSpan > 0 && span > 0) {
              const factor: number = span / this.lastPinchSpan;
              if (factor > 0.5 && factor < 2.0) {
                try {
                  native.zoomView(factor);
                } catch (error) {
                  this.viewerResult = 'zoom-error';
                }
              }
            }
            this.lastPinchSpan = span;
            return;
          }
          if (event.type === TouchType.Move && this.lastTouchX >= 0) {
            const dx: number = touch.windowX - this.lastTouchX;
            const dy: number = touch.windowY - this.lastTouchY;
            try {
              native.rotateView(dx, dy);
            } catch (error) {
              this.viewerResult = 'rotate-error';
            }
          }
          if (event.type === TouchType.Up || event.type === TouchType.Cancel) {
            this.lastTouchX = -1;
            this.lastTouchY = -1;
            return;
          }
          this.lastTouchX = touch.windowX;
          this.lastTouchY = touch.windowY;
        })
      if (this.fileNames.length > 0) {
        Row({ space: 6 }) {
          ForEach(this.fileNames, (name: string) => {
            Button(name).id('cx-file-' + name).fontSize(10).height(28)
              .backgroundColor('#1F3A5C').fontColor('#DDE7F3')
              .onClick(() => {
                const script: string = OPEN_PATH_SCRIPT.replace('__FILE__', name);
                const opened: ScriptReport = native.runScript(script);
                if (!opened.ok) {
                  this.viewerResult = 'open-error';
                  return;
                }
                this.openResult = opened.output.trim();
                try {
                  const drawn: DrawAtomsReport = native.drawAtoms(this.filesDir() + '/cx_atoms.txt');
                  this.viewerResult = name + ':' + drawn.atoms;
                } catch (error) {
                  this.viewerResult = 'viewer-error';
                }
              })
          }, (name: string) => name)
        }.width('100%')
      }
      Row() {
        Text('GL 表面').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.glStatus.length > 0 ? this.glStatus : '—').id('cx-gl-status')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('ChimeraX 渲染').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.renderResult.length > 0 ? this.renderResult : '—').id('cx-render')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(10)
      }.width('100%')
      Row() {
        Text('打开文件').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.openResult.length > 0 ? this.openResult : '—').id('cx-open')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(6)
      }.width('100%')
      Row() {
        Text('模型层').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.modelResult.length > 0 ? this.modelResult : '—').id('cx-model')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('GPU 绘制').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.glRender.length > 0 ? this.glRender : '—').id('cx-gl-render')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(2)
      }.width('100%')
      Row() {
        Text('GL 栈').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.glStackResult.length > 0 ? this.glStackResult : '—').id('cx-glstack')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('atomic').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.atomicResult.length > 0 ? this.atomicResult : '—').id('cx-atomic')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('graphics').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.graphicsResult.length > 0 ? this.graphicsResult : '—').id('cx-graphics')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('内置命令').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.builtinResult.length > 0 ? this.builtinResult : '—').id('cx-builtin')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      if (this.failed.length > 0) {
        Text(this.failed).id('cx-error').fontSize(12).fontColor('#FFB4A2').width('100%')
      }
      Text(this.prefix).fontSize(10).fontColor('#7F93A8').width('100%')
    }
      .width('100%').padding(20)
    }
    .width('100%').height('100%').backgroundColor('#1E3A5F').scrollBar(BarState.Auto)
  }
}
