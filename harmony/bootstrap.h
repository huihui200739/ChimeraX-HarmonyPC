#ifndef CX_HARMONY_BOOTSTRAP_H
#define CX_HARMONY_BOOTSTRAP_H

/* Call once per process, on the application's designated main thread.
 * root must be a private unpacked runtime, not a host Python installation.
 * argv contains the original executable name and application arguments.
 * runtime_check runs only a standard-library-only interpreter check.
 * This interface does not implement a HarmonyOS Ability or Qt event lifecycle.
 */
#if defined(__GNUC__)
#define CX_HARMONY_API __attribute__((visibility("default")))
#else
#define CX_HARMONY_API
#endif
#ifdef __cplusplus
extern "C" {
#endif
CX_HARMONY_API int cx_harmony_bootstrap(const char *root, int argc,
                                       char *const argv[], int runtime_check);
#ifdef __cplusplus
}
#endif
#endif
