// Embeds the private CPython runtime inside the HarmonyOS application sandbox.
// Only public CPython 3.11 entry points are used; no host Python is linked.
#include <napi/native_api.h>
#include <hilog/log.h>
#include <Python.h>

#include <dlfcn.h>
#include <zlib.h>
#include <sys/stat.h>
#include <cstdio>
#include <cstring>

#include <string>
#include <vector>

namespace {

constexpr const char* kTag = "ChimeraXNative";
bool g_initialized = false;
std::string g_error;

napi_value MakeString(napi_env env, const std::string& text) {
  napi_value out = nullptr;
  napi_create_string_utf8(env, text.c_str(), text.size(), &out);
  return out;
}

std::string Narrow(const wchar_t* text) {
  if (!text) {
    return {};
  }
  std::string out;
  for (const wchar_t* cursor = text; *cursor; ++cursor) {
    const unsigned long value = static_cast<unsigned long>(*cursor);
    if (value < 0x80) {
      out.push_back(static_cast<char>(value));
    } else {
      out.push_back('?');
    }
  }
  return out;
}

std::string ReadString(napi_env env, napi_value value) {
  size_t length = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &length) != napi_ok) {
    return {};
  }
  std::vector<char> buffer(length + 1, 0);
  if (napi_get_value_string_utf8(env, value, buffer.data(), buffer.size(), &length) != napi_ok) {
    return {};
  }
  return std::string(buffer.data(), length);
}


// --- Minimal ZIP extractor ---------------------------------------------------
// @ohos.zlib.decompressFile did not place every entry of the runtime archive on
// the target, so the archive is unpacked here with zlib only: local headers are
// walked through the central directory, deflate streams are inflated and the
// files are written with POSIX calls inside the app sandbox.

namespace {

uint32_t ReadLE32(const unsigned char* p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
uint16_t ReadLE16(const unsigned char* p) {
  return static_cast<uint16_t>(p[0] | (p[1] << 8));
}

bool MakeDirs(const std::string& path) {
  std::string current;
  for (size_t i = 0; i < path.size(); ++i) {
    current.push_back(path[i]);
    if (path[i] == '/' && current.size() > 1) {
      ::mkdir(current.c_str(), 0755);
    }
  }
  if (!current.empty() && current.back() != '/') {
    ::mkdir(current.c_str(), 0755);
  }
  return true;
}

std::string ReadFile(const std::string& path, bool* ok) {
  std::FILE* file = std::fopen(path.c_str(), "rb");
  if (!file) {
    *ok = false;
    return {};
  }
  std::fseek(file, 0, SEEK_END);
  const long size = std::ftell(file);
  std::fseek(file, 0, SEEK_SET);
  std::string data(static_cast<size_t>(size), '\0');
  const size_t read = std::fread(data.data(), 1, data.size(), file);
  std::fclose(file);
  *ok = read == data.size();
  return data;
}

}  // namespace

struct ExtractSummary {
  bool ok = false;
  int files = 0;
  int skipped = 0;
  std::string error;
};

ExtractSummary ExtractZip(const std::string& archive, const std::string& destination) {
  ExtractSummary summary;
  bool read_ok = false;
  const std::string blob = ReadFile(archive, &read_ok);
  if (!read_ok || blob.size() < 22) {
    summary.error = "archive is not readable";
    return summary;
  }
  const auto* bytes = reinterpret_cast<const unsigned char*>(blob.data());
  long eocd = -1;
  for (long i = static_cast<long>(blob.size()) - 22; i >= 0; --i) {
    if (ReadLE32(bytes + i) == 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) {
    summary.error = "end of central directory not found";
    return summary;
  }
  const uint32_t count = ReadLE16(bytes + eocd + 10);
  const uint32_t directory_offset = ReadLE32(bytes + eocd + 16);
  size_t cursor = directory_offset;
  MakeDirs(destination + "/x");
  for (uint32_t index = 0; index < count; ++index) {
    if (cursor + 46 > blob.size() || ReadLE32(bytes + cursor) != 0x02014b50) {
      summary.error = "central directory entry is invalid";
      return summary;
    }
    const uint16_t method = ReadLE16(bytes + cursor + 10);
    const uint32_t compressed = ReadLE32(bytes + cursor + 20);
    const uint32_t uncompressed = ReadLE32(bytes + cursor + 24);
    const uint16_t name_length = ReadLE16(bytes + cursor + 28);
    const uint16_t extra_length = ReadLE16(bytes + cursor + 30);
    const uint16_t comment_length = ReadLE16(bytes + cursor + 32);
    const uint32_t local_offset = ReadLE32(bytes + cursor + 42);
    const std::string name(blob.data() + cursor + 46, name_length);
    cursor += 46 + name_length + extra_length + comment_length;
    if (name.empty() || name.back() == '/') {
      MakeDirs(destination + "/" + name);
      continue;
    }
    if (local_offset + 30 > blob.size() || ReadLE32(bytes + local_offset) != 0x04034b50) {
      summary.error = "local header is invalid for " + name;
      return summary;
    }
    const uint16_t local_name = ReadLE16(bytes + local_offset + 26);
    const uint16_t local_extra = ReadLE16(bytes + local_offset + 28);
    const size_t data_start = local_offset + 30 + local_name + local_extra;
    if (data_start + compressed > blob.size()) {
      summary.error = "truncated data for " + name;
      return summary;
    }
    const std::string target = destination + "/" + name;
    const auto slash = target.rfind('/');
    if (slash != std::string::npos) {
      MakeDirs(target.substr(0, slash));
    }
    std::string output;
    if (method == 0) {
      output.assign(blob.data() + data_start, compressed);
    } else if (method == 8) {
      output.assign(uncompressed, '\0');
      z_stream stream{};
      stream.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(blob.data() + data_start));
      stream.avail_in = compressed;
      stream.next_out = reinterpret_cast<Bytef*>(output.data());
      stream.avail_out = uncompressed;
      if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) {
        summary.error = "inflateInit failed";
        return summary;
      }
      const int status = inflate(&stream, Z_FINISH);
      inflateEnd(&stream);
      if (status != Z_STREAM_END) {
        summary.error = "inflate failed for " + name;
        return summary;
      }
      output.resize(stream.total_out);
    } else {
      ++summary.skipped;
      continue;
    }
    std::FILE* file = std::fopen(target.c_str(), "wb");
    if (!file) {
      summary.error = "cannot write " + target;
      return summary;
    }
    std::fwrite(output.data(), 1, output.size(), file);
    std::fclose(file);
    ++summary.files;
  }
  summary.ok = true;
  return summary;
}

struct EvaluationResult {
  bool ok = false;
  std::string text;
};

// Evaluates one expression and returns its repr(); errors are returned as text.
EvaluationResult Evaluate(const std::string& expression) {
  PyObject* main = PyImport_AddModule("__main__");
  PyObject* globals = main ? PyModule_GetDict(main) : nullptr;
  if (!globals) {
    return {false, "no __main__ globals"};
  }
  PyObject* result = PyRun_String(expression.c_str(), Py_eval_input, globals, globals);
  if (!result) {
    PyObject *type = nullptr, *value = nullptr, *trace = nullptr;
    PyErr_Fetch(&type, &value, &trace);
    std::string message = "python error";
    if (value) {
      PyObject* text = PyObject_Str(value);
      if (text) {
        message = PyUnicode_AsUTF8(text);
        Py_DECREF(text);
      }
    }
    Py_XDECREF(type); Py_XDECREF(value); Py_XDECREF(trace);
    return {false, message};
  }
  PyObject* repr = PyObject_Str(result);
  const char* text = repr ? PyUnicode_AsUTF8(repr) : nullptr;
  std::string out = text ? text : "";
  Py_XDECREF(repr);
  Py_DECREF(result);
  return {true, out};
}

std::string PyReprString(const std::string& value) {
  std::string out = "'";
  for (char c : value) {
    if (c == '\\' || c == '\'') { out.push_back('\\'); }
    out.push_back(c);
  }
  out.push_back('\'');
  return out;
}

std::string OwnLibDir() {
  Dl_info info{};
  if (dladdr(reinterpret_cast<void*>(&OwnLibDir), &info) == 0 || !info.dli_fname) {
    return {};
  }
  std::string path(info.dli_fname);
  const auto slash = path.rfind('/');
  return slash == std::string::npos ? std::string() : path.substr(0, slash);
}

napi_value Initialize(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  const std::string home = argc >= 1 ? ReadString(env, argv[0]) : std::string();
  auto setBool = [&](const char* key, bool value) {
    napi_value flag = nullptr;
    napi_get_boolean(env, value, &flag);
    napi_set_named_property(env, out, key, flag);
  };
  auto setText = [&](const char* key, const std::string& value) {
    napi_set_named_property(env, out, key, MakeString(env, value));
  };
  if (g_initialized) {
    setBool("initialized", true);
    setText("version", std::string(Py_GetVersion()));
    setText("prefix", Narrow(Py_GetPrefix()));
    setText("home", home);
    return out;
  }
  if (home.empty()) {
    setBool("initialized", false);
    setText("error", "runtime home is required");
    return out;
  }
  static std::wstring wide_home;
  wide_home.assign(home.begin(), home.end());
  Py_SetPythonHome(wide_home.c_str());
  Py_InitializeEx(0);
  if (!Py_IsInitialized()) {
    setBool("initialized", false);
    setText("error", "Py_InitializeEx failed");
    return out;
  }
  const std::string lib_dir = OwnLibDir();
  // Extension modules are packaged as application native libraries; the copies
  // extracted next to the standard library cannot be dlopen'ed, so that path is
  // replaced instead of appended.
  // Extensions live in the application native library directory (the loader
  // refuses ELF objects extracted next to the standard library), while Python
  // packages come from the runtime tree. A small finder maps submodule names to
  // the native library copies so numpy/ctypes style packages keep working.
  const std::string bootstrap = std::string("import sys, os, importlib.machinery, importlib.util\n")
      + "sys.dont_write_bytecode = True\n"
      + "sys.path = [p for p in sys.path if not p.endswith('lib-dynload')]\n"
      + "sys.path.insert(0, " + PyReprString(lib_dir) + ")\n"
      + "os.environ['CX_NATIVE_LIB_DIR'] = " + PyReprString(lib_dir) + "\n"
      // PyOpenGL defaults to GLX/X11 on Linux; HarmonyOS exposes EGL + GLES only.
      + "os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')\n"
      // The GLES entry point for the completeness query returns 0 without a GL error here.
      + "os.environ.setdefault('CX_OHOS_SKIP_FB_STATUS', '1')\n"
      + "class _CxNativeFinder:\n"
      + "    _dir = " + PyReprString(lib_dir) + "\n"
      + "    @classmethod\n"
      + "    def find_spec(cls, fullname, path=None, target=None):\n"
      + "        rel = fullname.replace('.', os.sep)\n"
      + "        for suffix in importlib.machinery.EXTENSION_SUFFIXES:\n"
      + "            candidate = os.path.join(cls._dir, rel + suffix)\n"
      + "            if os.path.exists(candidate):\n"
      + "                return importlib.util.spec_from_file_location(fullname, candidate)\n"
      + "        return None\n"
      + "sys.meta_path.insert(0, _CxNativeFinder)\n";
  PyRun_SimpleString(bootstrap.c_str());
  // A persistent minimal Session and a registered probe command make the app a
  // usable command channel: user input runs against the same interpreter state.
  {
    const std::string home_env = std::string("CX_RUNTIME_HOME") + "=" + home;
    setenv("CX_RUNTIME_HOME", home.c_str(), 1);
  }
  PyRun_SimpleString(R"PY(
import os, sys
try:
    _cx_home = os.environ.get("CX_RUNTIME_HOME") or os.getcwd()
    os.environ["HOME"] = _cx_home
    import appdirs, chimerax
    chimerax.app_dirs = appdirs.AppDirs("ChimeraX", appauthor="RBVI", version="1.11")
    chimerax.app_dirs_unversioned = appdirs.AppDirs("ChimeraX", appauthor="RBVI")
    _cx_root = os.path.dirname(os.path.dirname(os.path.abspath(chimerax.__file__)))
    chimerax.app_data_dir = os.path.join(_cx_root, "share")
    chimerax.app_lib_dir = os.path.join(_cx_root, "lib")
    # Full start-up also exposes app_bin_dir; some bundle code (add_charge) looks tools up there.
    chimerax.app_bin_dir = os.path.join(_cx_root, "bin")
    os.makedirs(chimerax.app_data_dir, exist_ok=True)
    os.makedirs(chimerax.app_lib_dir, exist_ok=True)
    os.makedirs(chimerax.app_bin_dir, exist_ok=True)
    # chimerax.amber_info raises at import time unless an amberXX directory exists under bin.
    # Amber itself is not shipped, but the placeholder lets the module import so that command
    # paths which do not need Amber (the default charge methods) can run.
    os.makedirs(os.path.join(chimerax.app_bin_dir, "amber18", "bin"), exist_ok=True)
    from chimerax.core.session import Session
    from chimerax.core import core_settings
    from chimerax.core.commands import CmdDesc, StringArg, register

    class _NullUI:
        is_gui = False
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    session = Session("ChimeraX", silent=True, minimal=True)
    session.ui = _NullUI()
    core_settings.init(session)
    from chimerax.core.tools import Tools
    session.tools = Tools(session)
    try:
        from chimerax.core.models import Models
        session.models = Models(session)
    except Exception as _cx_models_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("models:" + type(_cx_models_error).__name__
                          + ":" + str(_cx_models_error)[:70])
    # Commands that colour or measure selections need the selection manager, which a full
    # start-up creates via the core bundle.
    try:
        from chimerax.core.selection import Selection
        session.selection = Selection(session)
    except Exception as _cx_selection_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("selection:" + type(_cx_selection_error).__name__
                          + ":" + str(_cx_selection_error)[:40])
    # Full-startup step for the atomic layer: sets up its settings object and residue templates,
    # which bundle commands (e.g. coulombic) rely on.
    try:
        from chimerax.atomic import initialize_atomic as _cx_init_atomic
        _cx_init_atomic(session)
    except Exception as _cx_atomic_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("atomic-init:" + type(_cx_atomic_error).__name__
                          + ":" + str(_cx_atomic_error)[:40])
    # Commands that record undo state (any modelling command) need the undo manager, which a full
    # start-up creates in the core bundle.
    try:
        from chimerax.core import undo as _cx_undo
        session.undo = _cx_undo.Undo(session, first=True)
    except Exception as _cx_undo_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("undo:" + type(_cx_undo_error).__name__
                          + ":" + str(_cx_undo_error)[:40])
    # Structure readers attach handlers to triggers that a full start-up registers while
    # importing bundles. This runs after Models(), which declares the model triggers itself,
    # so the calls below only fill in what is still missing.
    for _cx_trigger in ('model position changed', 'new frame', 'scene begin', 'scene end',
                        'frame drawn', 'graphics update'):
        try:
            session.triggers.add_trigger(_cx_trigger)
        except Exception:
            pass
    # The main view is what offscreen rendering captures from; the minimal session does
    # not create one on its own.
    try:
        from chimerax.graphics.view import View
        session.main_view = View(session.models.scene_root_model,
                                 window_size=(256, 256), trigger_set=session.triggers)
    except Exception as _cx_view_error:
        _cx_state = "view-failed:" + type(_cx_view_error).__name__ + ":" + str(_cx_view_error)[:80]
    from chimerax.core import toolshed as _cx_toolshed
    _cx_toolshed.init(session.logger, check_remote=False, check_available=False, session=session)
    session.toolshed = _cx_toolshed.get_toolshed()
    from chimerax.core import session as _cx_session_mod
    _cx_session_mod.register_misc_commands(session)
    _cx_calls = []

    def _cx_probe(session, value):
        _cx_calls.append(value)
        return "cxprobe:" + value

    try:
        register("cxprobe", CmdDesc(required=[("value", StringArg)],
                                    synopsis="harmony adaptation probe command"), _cx_probe)
    except Exception:
        pass  # already registered in this interpreter
    # Bundle-provided commands have to be registered explicitly: this minimal session
    # never runs the toolshed bundle discovery that a normal start-up performs.
    # Register the bundle command that works on this runtime: "list models" from list_info.
    # Managers that bundle commands depend on. Each is created once, before registration.
    for _cx_module, _cx_attr, _cx_name in (
            ("chimerax.data_formats", "_FormatsBundleAPI", "data formats"),
            ("chimerax.open_command", "_OpenBundleAPI", "open command")):
        try:
            _cx_api = getattr(__import__(_cx_module, fromlist=["_cx"]), _cx_attr)
            _cx_api.init_manager(session, None, _cx_name)
        except Exception as _cx_manager_error:
            _cx_state = ("manager:" + _cx_name + ":" + type(_cx_manager_error).__name__
                         + ":" + str(_cx_manager_error)[:40])

    # Session attributes a full start-up creates; command code (color, etc.) reads them directly.
    try:
        from chimerax.core import colors as _cx_colors
        session.user_colors = _cx_colors.UserColors()
    except Exception as _cx_colors_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("user_colors:" + type(_cx_colors_error).__name__)
    # The save manager normally comes from save_command's init_manager; the save command reads it
    # off the session.
    try:
        from chimerax.save_command import manager as _cx_save_manager
        session.save_command = _cx_save_manager.SaveManager(session, "save")
        # The tool shed normally feeds the savers from each bundle's bundle_info.xml
        # <Providers manager="save command">; do that by hand for the two structure formats.
        # Data-format providers live on session.data_formats; the save command looks formats up
        # there before asking the save manager for the writer.
        try:
            from chimerax.data_formats.manager import FormatsManager as _cx_formats
            session.data_formats = _cx_formats(session, "data formats")
        except Exception as _cx_df_error:
            _cx_errors = globals().setdefault("_cx_errors", [])
            _cx_errors.append("data-formats:" + type(_cx_df_error).__name__)
        for _cx_bundle, _cx_format, _cx_suffixes in (
                ("ChimeraX-PDB", "PDB", ["pdb", "ent"]),
                ("ChimeraX-mmCIF", "mmCIF", ["cif", "mmcif"])):
            try:
                _cx_bi = session.toolshed.find_bundle(_cx_bundle, session.logger)
                if _cx_bi is None:
                    # The bundle tree is staged, not installed through the tool shed, so there is no
                    # BundleInfo object to hand to the managers; record it and move on.
                    _cx_errors = globals().setdefault("_cx_errors", [])
                    _cx_errors.append("no-bundle-info:" + _cx_bundle)
                    continue
                session.data_formats.add_provider(_cx_bi, _cx_format,
                                                  category="Molecular structure",
                                                  suffixes=_cx_suffixes)
                session.save_command.add_provider(_cx_bi, _cx_format, compression_okay=False)
            except Exception as _cx_fmt_error:
                _cx_errors = globals().setdefault("_cx_errors", [])
                _cx_errors.append("saver-" + _cx_format + ":"
                                  + type(_cx_fmt_error).__name__ + ":"
                                  + str(_cx_fmt_error)[:30])
    except Exception as _cx_save_error:
        _cx_errors = globals().setdefault("_cx_errors", [])
        _cx_errors.append("save-mgr:" + type(_cx_save_error).__name__
                          + ":" + str(_cx_save_error)[:40])
    # The core command set (select/color/style/coordset/view/turn/zoom/... about sixty commands)
    # is normally registered by the std_commands bundle during start-up. Registering it unlocks
    # the commands that bundle code calls internally, e.g. morph's coordset.
    try:
        import chimerax.std_commands as _cx_std
        _cx_std.register_commands(session)
        _cx_notes = globals().setdefault("_cx_notes", [])
        from chimerax.core.commands.cli import registered_commands as _cx_reg
        _cx_notes.append("std-commands=" + str(len([n for n in _cx_reg() if " " not in n])))
    except Exception as _cx_std_error:
        _cx_notes = globals().setdefault("_cx_notes", [])
        _cx_notes.append("std-commands:" + type(_cx_std_error).__name__
                         + ":" + str(_cx_std_error)[:50])
    # Bundle commands verified to work on this runtime.
    for _cx_module, _cx_attr, _cx_cmds in (
            ("chimerax.list_info", "_InfoAPI", ("list",)),
            ("chimerax.open_command", "_OpenBundleAPI", ("open",)),
            ("chimerax.zone", "_ZoneBundleAPI", ("zone",)),
            ("chimerax.mlp", "_MyAPI", ("mlp",)),
            ("chimerax.coulombic", "_CoulombicBundle", ("coulombic",)),
            ("chimerax.morph", "_MorphAPI", ("morph",)),
            ("chimerax.mask", "_MaskBundleAPI", ("mask",)),
            ("chimerax.segment", "_SegmentBundle", ("segmentation",)),
            ("chimerax.save_command", "_OpenBundleAPI", ("save",))):
        try:
            _cx_api = getattr(__import__(_cx_module, fromlist=["_cx"]), _cx_attr)
            if _cx_module == "chimerax.zone":
                # zone needs its mouse mode object before the command can run.
                try:
                    _cx_api.initialize(session, None)
                except Exception as _cx_zone_error:
                    _cx_errors = globals().setdefault("_cx_errors", [])
                    _cx_errors.append("zone-init:" + type(_cx_zone_error).__name__
                                      + ":" + str(_cx_zone_error)[:50])
            for _cx_cmd in _cx_cmds:
                try:
                    _cx_api.register_command(_cx_cmd, session.logger)
                except Exception as _cx_one:
                    _cx_notes = globals().setdefault("_cx_notes", [])
                    _cx_notes.append(_cx_cmd + ":" + type(_cx_one).__name__
                                     + ":" + str(_cx_one)[:40])
        except Exception as _cx_bundle_error:
            _cx_notes = globals().setdefault("_cx_notes", [])
            _cx_notes.append(_cx_module.rsplit(".", 1)[-1] + ":"
                             + type(_cx_bundle_error).__name__)
    _cx_state = globals().get("_cx_state", "session-ready")
    if globals().get("_cx_errors"):
        _cx_state = ";".join(globals()["_cx_errors"])[:160]
    _cx_notes = globals().get("_cx_notes") or []
except Exception as _cx_error:
    _cx_state = "session-error:" + str(_cx_error)[:200]
)PY");
  g_initialized = true;
  setBool("initialized", true);
  setText("version", std::string(Py_GetVersion()));
  setText("prefix", Narrow(Py_GetPrefix()));
  setText("home", home);
  setText("libDir", lib_dir);
  OH_LOG_Print(LOG_APP, LOG_INFO, 0x3802, kTag, "runtime ready: %{public}s", Py_GetVersion());
  return out;
}

napi_value EvaluateExpression(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  auto setText = [&](const char* key, const std::string& value) {
    napi_set_named_property(env, out, key, MakeString(env, value));
  };
  auto setBool = [&](const char* key, bool value) {
    napi_value flag = nullptr;
    napi_get_boolean(env, value, &flag);
    napi_set_named_property(env, out, key, flag);
  };
  if (!g_initialized) {
    setBool("ok", false);
    setText("error", "runtime is not initialized");
    return out;
  }
  const std::string expression = argc >= 1 ? ReadString(env, argv[0]) : std::string();
  if (expression.empty()) {
    setBool("ok", false);
    setText("error", "expression is required");
    return out;
  }
  PyGILState_STATE gil = PyGILState_Ensure();
  const EvaluationResult evaluated = Evaluate(expression);
  PyGILState_Release(gil);
  setBool("ok", evaluated.ok);
  setText("value", evaluated.text);
  setText("error", evaluated.ok ? std::string() : evaluated.text);
  return out;
}

napi_value Finalize(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  if (g_initialized) {
    PyGILState_STATE gil = PyGILState_Ensure();
    Py_FinalizeEx();
    (void)gil;
    g_initialized = false;
  }
  napi_value flag = nullptr;
  napi_get_boolean(env, true, &flag);
  napi_set_named_property(env, out, "finalized", flag);
  return out;
}


napi_value ExtractArchive(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  size_t argc = 2;
  napi_value argv[2] = {nullptr, nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  auto setBool = [&](const char* key, bool value) {
    napi_value flag = nullptr;
    napi_get_boolean(env, value, &flag);
    napi_set_named_property(env, out, key, flag);
  };
  auto setNumber = [&](const char* key, int value) {
    napi_value number = nullptr;
    napi_create_int32(env, value, &number);
    napi_set_named_property(env, out, key, number);
  };
  auto setText = [&](const char* key, const std::string& value) {
    napi_set_named_property(env, out, key, MakeString(env, value));
  };
  const std::string archive = argc >= 1 ? ReadString(env, argv[0]) : std::string();
  const std::string destination = argc >= 2 ? ReadString(env, argv[1]) : std::string();
  if (archive.empty() || destination.empty()) {
    setBool("ok", false);
    setText("error", "archive and destination are required");
    return out;
  }
  const ExtractSummary summary = ExtractZip(archive, destination);
  setBool("ok", summary.ok);
  setNumber("files", summary.files);
  setNumber("skipped", summary.skipped);
  setText("error", summary.error);
  return out;
}

// Runs a multi-line Python script inside the private runtime and returns whatever
// it printed; the app uses this for real ChimeraX command execution.

// Quotes a string so it can be embedded in generated Python source.
std::string PyLiteral(const std::string& value) {
  std::string out = "'";
  for (char c : value) {
    if (c == '\\' || c == '\'') {
      out.push_back('\\');
    }
    if (c == '\n') {
      continue;
    }
    out.push_back(c);
  }
  out.push_back('\'');
  return out;
}

struct ScriptOutcome {
  bool ok = false;
  std::string output;
};

// Runs code in __main__ with stdout captured; shared by the script and command
// entry points so both behave the same way.
ScriptOutcome ExecuteScript(const std::string& code) {
  ScriptOutcome outcome;
  if (!g_initialized || code.empty()) {
    outcome.output = g_initialized ? "script is required" : "runtime is not initialized";
    return outcome;
  }
  PyGILState_STATE gil = PyGILState_Ensure();
  PyObject* main = PyImport_AddModule("__main__");
  PyObject* globals = main ? PyModule_GetDict(main) : nullptr;
  if (globals) {
    PyRun_SimpleString("import io as _cx_io, sys as _cx_sys\n"
                       "_cx_buf = _cx_io.StringIO()\n"
                       "_cx_real_stdout = _cx_sys.stdout\n"
                       "_cx_sys.stdout = _cx_buf\n");
    PyObject* result = PyRun_String(code.c_str(), Py_file_input, globals, globals);
    PyRun_SimpleString("_cx_sys.stdout = _cx_real_stdout\n");
    // Resolve the interpreter state before touching the capture buffer: a pending
    // exception would otherwise make getvalue() report "exception set".
    if (result) {
      Py_DECREF(result);
      outcome.ok = true;
    } else {
      PyObject *type = nullptr, *value = nullptr, *trace = nullptr;
      PyErr_Fetch(&type, &value, &trace);
      if (value) {
        PyObject* text = PyObject_Str(value);
        if (text) {
          const char* message = PyUnicode_AsUTF8(text);
          if (message) {
            outcome.output += std::string(message);
          }
          Py_DECREF(text);
        }
      }
      Py_XDECREF(type); Py_XDECREF(value); Py_XDECREF(trace);
    }
    PyErr_Clear();
    PyObject* buffer = PyDict_GetItemString(globals, "_cx_buf");
    if (buffer) {
      PyObject* text = PyObject_CallMethod(buffer, "getvalue", nullptr);
      if (text) {
        const char* value = PyUnicode_AsUTF8(text);
        if (value) {
          outcome.output = std::string(value) + outcome.output;
        }
        Py_DECREF(text);
      } else {
        PyErr_Clear();
      }
    }
  }
  PyGILState_Release(gil);
  return outcome;
}

napi_value RunScript(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  auto setBool = [&](const char* key, bool value) {
    napi_value flag = nullptr;
    napi_get_boolean(env, value, &flag);
    napi_set_named_property(env, out, key, flag);
  };
  auto setText = [&](const char* key, const std::string& value) {
    napi_set_named_property(env, out, key, MakeString(env, value));
  };
  const std::string code = argc >= 1 ? ReadString(env, argv[0]) : std::string();
  const ScriptOutcome outcome = ExecuteScript(code);
  setBool("ok", outcome.ok);
  setText("output", outcome.output);
  setText("error", outcome.ok ? std::string() : outcome.output);
  return out;
}

// Executes ChimeraX command syntax through the real command interpreter.
napi_value RunChimeraCommand(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  auto setBool = [&](const char* key, bool value) {
    napi_value flag = nullptr;
    napi_get_boolean(env, value, &flag);
    napi_set_named_property(env, out, key, flag);
  };
  auto setText = [&](const char* key, const std::string& value) {
    napi_set_named_property(env, out, key, MakeString(env, value));
  };
  if (!g_initialized) {
    setBool("ok", false);
    setText("error", "runtime is not initialized");
    return out;
  }
  const std::string text = argc >= 1 ? ReadString(env, argv[0]) : std::string();
  if (text.empty()) {
    setBool("ok", false);
    setText("error", "command is required");
    return out;
  }
  const std::string code = "print(__import__('chimerax.core.commands', fromlist=['run']).run(session, "
      + PyLiteral(text) + "))";
  const ScriptOutcome outcome = ExecuteScript(code);
  setBool("ok", outcome.ok);
  setText("output", outcome.output);
  setText("error", outcome.ok ? std::string() : outcome.output);
  return out;
}

extern "C" void RegisterChimeraXGLSurface(napi_env env, void* exports);
extern "C" const char* ChimeraXGLStatus();
extern "C" const char* ChimeraXGLRender();
extern "C" void* ChimeraXGLDisplay();
extern "C" void* ChimeraXGLContext();
extern "C" void* ChimeraXGLSurface();
extern "C" int ChimeraXGLRelease();
extern "C" int ChimeraXGLReacquire();
extern "C" int ChimeraXGLDrawAtoms(const char* path);
extern "C" int ChimeraXGLRotate(float dx, float dy);
extern "C" int ChimeraXGLZoom(float factor);

// Exposes the EGL handles so the interpreter can adopt the same context; pointers
// travel as decimal strings because napi has no 64-bit integer type.
napi_value GLHandles(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  const std::string values[3] = {
      std::to_string(reinterpret_cast<uintptr_t>(ChimeraXGLDisplay())),
      std::to_string(reinterpret_cast<uintptr_t>(ChimeraXGLContext())),
      std::to_string(reinterpret_cast<uintptr_t>(ChimeraXGLSurface()))};
  const char* names[3] = {"display", "context", "surface"};
  for (int index = 0; index < 3; ++index) {
    napi_set_named_property(env, out, names[index], MakeString(env, values[index]));
  }
  napi_value released = nullptr;
  napi_get_boolean(env, ChimeraXGLRelease() != 0, &released);
  napi_set_named_property(env, out, "released", released);
  return out;
}

// Renders an atom list produced by the Python side into the XComponent surface.
napi_value DrawAtoms(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  std::string path;
  if (argc >= 1) {
    char buffer[1024] = {0};
    size_t length = 0;
    if (napi_get_value_string_utf8(env, argv[0], buffer, sizeof(buffer), &length) == napi_ok) {
      path.assign(buffer, length);
    }
  }
  napi_value out = nullptr;
  napi_create_object(env, &out);
  const int drawn = path.empty() ? -10 : ChimeraXGLDrawAtoms(path.c_str());
  napi_value count = nullptr;
  napi_create_int32(env, drawn, &count);
  napi_set_named_property(env, out, "atoms", count);
  return out;
}

// Touch-driven view updates for the structure viewer.
napi_value RotateView(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2] = {nullptr, nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  double dx = 0, dy = 0;
  if (argc >= 1) napi_get_value_double(env, argv[0], &dx);
  if (argc >= 2) napi_get_value_double(env, argv[1], &dy);
  napi_value out = nullptr;
  napi_get_boolean(env, ChimeraXGLRotate(static_cast<float>(dx), static_cast<float>(dy)) != 0, &out);
  return out;
}

napi_value ZoomView(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  double factor = 1.0;
  if (argc >= 1) napi_get_value_double(env, argv[0], &factor);
  napi_value out = nullptr;
  napi_get_boolean(env, ChimeraXGLZoom(static_cast<float>(factor)) != 0, &out);
  return out;
}

napi_value GLReacquire(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_get_boolean(env, ChimeraXGLReacquire() != 0, &out);
  return out;
}

napi_value GLStatus(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  const char* status = ChimeraXGLStatus();
  napi_set_named_property(env, out, "status",
                          MakeString(env, status ? status : ""));
  const char* render = ChimeraXGLRender();
  napi_set_named_property(env, out, "render",
                          MakeString(env, render ? render : ""));
  return out;
}


// Runs an expression through napi_run_script so the page can learn which forms the
// ArkTS runtime accepts. Qt's OHOS plugin relies on this mechanism for LocalStorage.
napi_value EvalProbe(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  napi_value out = nullptr;
  napi_create_object(env, &out);
  if (argc < 1) {
    napi_set_named_property(env, out, "error", MakeString(env, "no expression"));
    return out;
  }
  napi_value result = nullptr;
  napi_status status = napi_run_script(env, argv[0], &result);
  napi_value okValue = nullptr;
  napi_get_boolean(env, status == napi_ok, &okValue);
  napi_set_named_property(env, out, "ok", okValue);
  if (status == napi_ok && result != nullptr) {
    napi_valuetype type = napi_undefined;
    if (napi_typeof(env, result, &type) == napi_ok) {
      napi_value typeName = nullptr;
      napi_create_int32(env, static_cast<int32_t>(type), &typeName);
      napi_set_named_property(env, out, "typeName", typeName);
    }
  } else {
    bool pending = false;
    napi_is_exception_pending(env, &pending);
    if (pending) {
      napi_value error = nullptr;
      napi_get_and_clear_last_exception(env, &error);
      napi_value message = nullptr;
      if (napi_coerce_to_string(env, error, &message) == napi_ok) {
        napi_set_named_property(env, out, "error", message);
      }
    }
  }
  return out;
}

napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"initializeRuntime", nullptr, Initialize, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"runExpression", nullptr, EvaluateExpression, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"finalizeRuntime", nullptr, Finalize, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"extractArchive", nullptr, ExtractArchive, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"runScript", nullptr, RunScript, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"runChimeraCommand", nullptr, RunChimeraCommand, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"glStatus", nullptr, GLStatus, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"glHandles", nullptr, GLHandles, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"glReacquire", nullptr, GLReacquire, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"drawAtoms", nullptr, DrawAtoms, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"rotateView", nullptr, RotateView, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"zoomView", nullptr, ZoomView, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"evalProbe", nullptr, EvalProbe, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports,
                         sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
  RegisterChimeraXGLSurface(env, exports);
  return exports;
}

}  // namespace

static napi_module chimeraxModule = {
    .nm_version = 1,
    .nm_flags = 0,
    .nm_filename = nullptr,
    .nm_register_func = Init,
    .nm_modname = "chimerax_native",
    .nm_priv = nullptr,
    .reserved = {0},
};

extern "C" __attribute__((constructor)) void RegisterChimeraXNative() {
  napi_module_register(&chimeraxModule);
}
