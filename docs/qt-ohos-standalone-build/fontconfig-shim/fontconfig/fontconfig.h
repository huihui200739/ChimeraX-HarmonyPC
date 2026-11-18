/* Minimal fontconfig declarations, only for compiling the QOhos platform plugin.
 *
 * Neither the OHOS SDK nor the HarmonyOS prebuilt Qt ships fontconfig headers
 * (the official Qt for HarmonyOS build links fontconfig statically into
 * libQt6Gui.so). libQt6Gui.so exports the Fc* symbols with version Qt_6, so the
 * plugin only needs declarations, not a link-time dependency.
 */
#ifndef FONTCONFIG_SHIM_FONTCONFIG_H
#define FONTCONFIG_SHIM_FONTCONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

typedef int FcBool;
typedef unsigned char FcChar8;
typedef struct _FcConfig FcConfig;

/* Value of the FONTCONFIG_VERSION macro is irrelevant to the plugin; keep it
 * defined so that any QT_CONFIG() based probe header stays happy. */
#define FONTCONFIG_VERSION "2.15.0-shim"

FcBool FcInit(void);
FcConfig *FcConfigGetCurrent(void);
FcBool FcConfigAppFontAddDir(FcConfig *config, const FcChar8 *dir);
FcBool FcConfigBuildFonts(FcConfig *config);

#ifdef __cplusplus
}
#endif

#endif /* FONTCONFIG_SHIM_FONTCONFIG_H */
