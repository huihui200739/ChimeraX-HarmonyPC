// HarmonyOS window integration: an XComponent surface is turned into an EGL/GLES3
// context so the private runtime can render into a real window. EGL displays are
// only available inside an application process, never from the CLI launcher.
#include <ace/xcomponent/native_interface_xcomponent.h>
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <hilog/log.h>
#include <napi/native_api.h>

#include <cstring>
#include <string>


// Draws one triangle through a real GLSL program into the window surface and reads
// a pixel back. This proves the device GPU accepts our shaders, which is the same
// requirement the ChimeraX renderer has.
namespace {

const char* kVertexShader = R"(#version 300 es
layout(location = 0) in vec2 position;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
}
)";

const char* kFragmentShader = R"(#version 300 es
precision mediump float;
out vec4 color;
void main() {
    color = vec4(0.95, 0.55, 0.15, 1.0);
}
)";

GLuint CompileShader(GLenum type, const char* source, std::string& error) {
  GLuint shader = glCreateShader(type);
  glShaderSource(shader, 1, &source, nullptr);
  glCompileShader(shader);
  GLint ok = GL_FALSE;
  glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
  if (ok != GL_TRUE) {
    char log[512] = {0};
    glGetShaderInfoLog(shader, sizeof(log) - 1, nullptr, log);
    error = log;
    glDeleteShader(shader);
    return 0;
  }
  return shader;
}

std::string RenderTriangle(int width, int height) {
  std::string error;
  GLuint vertex = CompileShader(GL_VERTEX_SHADER, kVertexShader, error);
  if (vertex == 0) {
    return "vertex-shader:" + error;
  }
  GLuint fragment = CompileShader(GL_FRAGMENT_SHADER, kFragmentShader, error);
  if (fragment == 0) {
    glDeleteShader(vertex);
    return "fragment-shader:" + error;
  }
  GLuint program = glCreateProgram();
  glAttachShader(program, vertex);
  glAttachShader(program, fragment);
  glLinkProgram(program);
  GLint linked = GL_FALSE;
  glGetProgramiv(program, GL_LINK_STATUS, &linked);
  if (linked != GL_TRUE) {
    char log[512] = {0};
    glGetProgramInfoLog(program, sizeof(log) - 1, nullptr, log);
    glDeleteProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    return std::string("link:") + log;
  }
  const GLfloat vertices[] = {0.0f, 0.6f, -0.6f, -0.6f, 0.6f, -0.6f};
  GLuint buffer = 0;
  glGenBuffers(1, &buffer);
  glBindBuffer(GL_ARRAY_BUFFER, buffer);
  glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);
  glEnableVertexAttribArray(0);
  glViewport(0, 0, width, height);
  glClearColor(0.02f, 0.03f, 0.05f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);
  glUseProgram(program);
  glDrawArrays(GL_TRIANGLES, 0, 3);
  glFinish();
  unsigned char pixel[4] = {0, 0, 0, 0};
  glReadPixels(width / 2, height / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
  glDeleteBuffers(1, &buffer);
  glDeleteProgram(program);
  glDeleteShader(vertex);
  glDeleteShader(fragment);
  char summary[96];
  snprintf(summary, sizeof(summary), "triangle:%d,%d,%d,%d", pixel[0], pixel[1], pixel[2], pixel[3]);
  return summary;
}

std::string g_render_status = "not-run";

}  // namespace

namespace {

constexpr const char* kTag = "ChimeraXGL";
EGLDisplay g_display = EGL_NO_DISPLAY;
EGLSurface g_surface = EGL_NO_SURFACE;
EGLContext g_context = EGL_NO_CONTEXT;
std::string g_status = "not-initialised";

void SetStatus(const std::string& status) {
  g_status = status;
  OH_LOG_Print(LOG_APP, LOG_INFO, 0x3803, kTag, "surface: %{public}s", status.c_str());
}

void OnSurfaceCreatedCB(OH_NativeXComponent* component, void* window) {
  if (!component || !window) {
    SetStatus("surface-created:missing-window");
    return;
  }
  auto* nativeWindow = static_cast<OHNativeWindow*>(window);
  uint64_t width = 0, height = 0;
  OH_NativeXComponent_GetXComponentSize(component, window, &width, &height);

  g_display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
  if (g_display == EGL_NO_DISPLAY) {
    SetStatus("egl:no-display");
    return;
  }
  EGLint major = 0, minor = 0;
  if (!eglInitialize(g_display, &major, &minor)) {
    SetStatus("egl:initialize-failed");
    return;
  }
  const EGLint configAttribs[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE,
                                  EGL_OPENGL_ES3_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
                                  EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
  EGLConfig config = nullptr;
  EGLint numConfigs = 0;
  if (!eglChooseConfig(g_display, configAttribs, &config, 1, &numConfigs) || numConfigs < 1) {
    SetStatus("egl:no-config");
    return;
  }
  g_surface = eglCreateWindowSurface(g_display, config,
                                     reinterpret_cast<EGLNativeWindowType>(nativeWindow), nullptr);
  if (g_surface == EGL_NO_SURFACE) {
    SetStatus("egl:no-surface");
    return;
  }
  const EGLint contextAttribs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
  g_context = eglCreateContext(g_display, config, EGL_NO_CONTEXT, contextAttribs);
  if (g_context == EGL_NO_CONTEXT) {
    SetStatus("egl:no-context");
    return;
  }
  if (!eglMakeCurrent(g_display, g_surface, g_surface, g_context)) {
    SetStatus("egl:make-current-failed");
    return;
  }
  const char* version = reinterpret_cast<const char*>(glGetString(GL_VERSION));
  const char* renderer = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
  SetStatus(std::string("ready:") + (version ? version : "?") + ":" +
            (renderer ? renderer : "?") + ":" + std::to_string(width) + "x" +
            std::to_string(height));
  // First frame: draw a triangle through GLSL, read it back, then show the
  // ChimeraX background colour.
  g_render_status = RenderTriangle(static_cast<int>(width), static_cast<int>(height));
  OH_LOG_Print(LOG_APP, LOG_INFO, 0x3803, kTag, "render: %{public}s", g_render_status.c_str());
  glViewport(0, 0, static_cast<GLint>(width), static_cast<GLint>(height));
  glClearColor(0.09f, 0.13f, 0.20f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);
  eglSwapBuffers(g_display, g_surface);
}

void OnSurfaceChangedCB(OH_NativeXComponent* component, void* window) {
  uint64_t width = 0, height = 0;
  OH_NativeXComponent_GetXComponentSize(component, window, &width, &height);
  if (g_display != EGL_NO_DISPLAY) {
    glViewport(0, 0, static_cast<GLint>(width), static_cast<GLint>(height));
    glClearColor(0.09f, 0.13f, 0.20f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    if (g_surface != EGL_NO_SURFACE) {
      eglSwapBuffers(g_display, g_surface);
    }
  }
  SetStatus("resized:" + std::to_string(width) + "x" + std::to_string(height));
}

void OnSurfaceDestroyedCB(OH_NativeXComponent* component, void* window) {
  if (g_display != EGL_NO_DISPLAY) {
    eglMakeCurrent(g_display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (g_context != EGL_NO_CONTEXT) {
      eglDestroyContext(g_display, g_context);
      g_context = EGL_NO_CONTEXT;
    }
    if (g_surface != EGL_NO_SURFACE) {
      eglDestroySurface(g_display, g_surface);
      g_surface = EGL_NO_SURFACE;
    }
    eglTerminate(g_display);
    g_display = EGL_NO_DISPLAY;
  }
  SetStatus("destroyed");
}

OH_NativeXComponent_Callback g_callback = {
    .OnSurfaceCreated = OnSurfaceCreatedCB,
    .OnSurfaceChanged = OnSurfaceChangedCB,
    .OnSurfaceDestroyed = OnSurfaceDestroyedCB,
    .DispatchTouchEvent = nullptr,
};

}  // namespace

extern "C" void RegisterChimeraXGLSurface(napi_env env, void* exports) {
  napi_value exportInstance = nullptr;
  if (napi_get_named_property(env, static_cast<napi_value>(exports), OH_NATIVE_XCOMPONENT_OBJ,
                              &exportInstance) != napi_ok) {
    SetStatus("xcomponent:no-export");
    return;
  }
  OH_NativeXComponent* component = nullptr;
  if (napi_unwrap(env, exportInstance, reinterpret_cast<void**>(&component)) != napi_ok || !component) {
    SetStatus("xcomponent:no-instance");
    return;
  }
  OH_NativeXComponent_RegisterCallback(component, &g_callback);
  SetStatus("xcomponent:registered");
}

extern "C" const char* ChimeraXGLStatus() { return g_status.c_str(); }

extern "C" const char* ChimeraXGLRender() { return g_render_status.c_str(); }

extern "C" void* ChimeraXGLDisplay() { return reinterpret_cast<void*>(g_display); }
extern "C" void* ChimeraXGLContext() { return reinterpret_cast<void*>(g_context); }
extern "C" void* ChimeraXGLSurface() { return reinterpret_cast<void*>(g_surface); }

// Hands the context to another thread (the interpreter thread) for offscreen work.
// EGL keeps a context current on at most one thread, so the render thread releases
// it before Python adopts it.
extern "C" int ChimeraXGLRelease() {
  if (g_display == EGL_NO_DISPLAY) {
    return 0;
  }
  return eglMakeCurrent(g_display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT) ? 1 : 0;
}

extern "C" int ChimeraXGLReacquire() {
  if (g_display == EGL_NO_DISPLAY || g_context == EGL_NO_CONTEXT) {
    return 0;
  }
  return eglMakeCurrent(g_display, g_surface, g_surface, g_context) ? 1 : 0;
}
