// Embeds the private CPython runtime inside the HarmonyOS application sandbox.
// Only public CPython 3.11 entry points are used; no host Python is linked.
#include <napi/native_api.h>
#include <hilog/log.h>
#include <Python.h>

#include <dlfcn.h>

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
  const std::string bootstrap = std::string("import sys\n")
      + "sys.dont_write_bytecode = True\n"
      + "sys.path = [p for p in sys.path if not p.endswith('lib-dynload')]\n"
      + "sys.path.insert(0, " + PyReprString(lib_dir) + ")\n";
  PyRun_SimpleString(bootstrap.c_str());
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

napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"initializeRuntime", nullptr, Initialize, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"runExpression", nullptr, EvaluateExpression, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"finalizeRuntime", nullptr, Finalize, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
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
