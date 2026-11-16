/* Standalone generic runtime check. No application code, files or data loaded. */
#include <dlfcn.h>
#include <stdio.h>
#include <sys/utsname.h>

static void json_string(const char *s) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 0x20) { printf("\\u%04x", *p); }
        else { putchar(*p); }
    }
    putchar('"');
}

int main(void) {
    const char *libraries[] = {
        "libc.so.6", "libEGL.so", "libGLESv3.so", "libGL.so.1",
        "libpython3.11.so", "libpython3.11.so.1.0",
        "libQt6Core.so", "libQt6Core.so.6", "libQt6Gui.so", "libQt6Gui.so.6",
        "libQt6Widgets.so", "libQt6Widgets.so.6",
        "libQt6WebEngineCore.so", "libQt6WebEngineCore.so.6"
    };
    struct utsname info;
    if (uname(&info) != 0) { perror("uname"); return 2; }
    printf("{\"schema_version\":1,\"purpose\":\"generic_native_loader_probe\",");
    printf("\"upstream_app_launched\":false,\"port_validated\":false,\"kernel\":");
    json_string(info.sysname);
    printf(",\"architecture\":"); json_string(info.machine);
    printf(",\"libraries\":[");
    for (size_t i = 0; i < sizeof(libraries) / sizeof(libraries[0]); ++i) {
        if (i) { putchar(','); }
        dlerror();
        void *handle = dlopen(libraries[i], RTLD_NOW | RTLD_LOCAL);
        const char *error = handle ? NULL : dlerror();
        printf("{\"name\":"); json_string(libraries[i]);
        printf(",\"loaded\":%s,\"error\":", handle ? "true" : "false");
        if (error) { json_string(error); } else { printf("null"); }
        putchar('}');
        if (handle) { dlclose(handle); }
    }
    printf("],\"scope_note\":\"Default loader namespace only; private app runtimes are not inspected. EGL/GLES loading is not desktop OpenGL or window validation.\"}\n");
    return 0;
}
