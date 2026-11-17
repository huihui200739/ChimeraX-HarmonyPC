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
    os.makedirs(chimerax.app_data_dir, exist_ok=True)
    os.makedirs(chimerax.app_lib_dir, exist_ok=True)
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
    _cx_state = "session-ready"
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

napi_value GLStatus(napi_env env, napi_callback_info info) {
  napi_value out = nullptr;
  napi_create_object(env, &out);
  const char* status = ChimeraXGLStatus();
  napi_set_named_property(env, out, "status",
                          MakeString(env, status ? status : ""));
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
