cmake_minimum_required(VERSION 3.25)

project(qohos_plugin_standalone LANGUAGES CXX)

# Standalone rebuild of the Qt for HarmonyOS QPA plugin against the official
# prebuilt HarmonyOS Qt 6.12.0 package, so that no full qtbase build is needed.
#
# Required cache variables:
#   QOHOS_SRC        - patched copy of qtbase/src/plugins/platforms/ohos
#   QT_HOST_PATH     - host Qt 6.12.0 (moc/uic/rcc)
#   CMAKE_PREFIX_PATH- prebuilt HarmonyOS Qt 6.12.0
#   NODE_ADDON_API_ROOT - directory containing node-addon-api/napi.h

if(NOT DEFINED QOHOS_SRC)
    message(FATAL_ERROR "QOHOS_SRC must point at the patched ohos platform plugin sources")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# The OHOS toolchain pins CMAKE_FIND_ROOT_PATH_MODE_* to ONLY and roots every
# search in the SDK sysroot, which hides the prebuilt Qt package. Re-open the
# search paths for the prefixes we explicitly pass in.
foreach(prefix IN LISTS CMAKE_PREFIX_PATH)
    list(APPEND CMAKE_FIND_ROOT_PATH "${prefix}")
endforeach()
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)

find_package(Qt6 6.12 REQUIRED COMPONENTS Core Gui OpenGL)
find_package(Qt6CorePrivate REQUIRED)
find_package(Qt6GuiPrivate REQUIRED)
find_package(Qt6OpenGLPrivate REQUIRED)

# napi.h (node-addon-api) is not shipped by the OHOS SDK nor by the prebuilt Qt.
find_package(NodeAddonApi REQUIRED)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOMOC_MACRO_NAMES "Q_OBJECT;Q_GADGET;Q_NAMESPACE;Q_NAMESPACE_EXPORT;Q_PLUGIN_METADATA")

include(${CMAKE_CURRENT_LIST_DIR}/sources.cmake)

set(OHOS_STUB_DIR "${OHOS_SDK_NATIVE}/sysroot/usr/lib/aarch64-linux-ohos")

add_library(qohos MODULE ${QOHOS_PLUGIN_SOURCES})

set_target_properties(qohos PROPERTIES
    PREFIX "lib"
    OUTPUT_NAME "qohos"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
    SKIP_BUILD_RPATH TRUE
    BUILD_WITH_INSTALL_RPATH FALSE
    INSTALL_RPATH ""
)

target_include_directories(qohos PRIVATE
    ${QOHOS_SRC}
    ${NodeAddonApi_INCLUDE_DIR}
    # Minimal <fontconfig/fontconfig.h>: the OHOS SDK and the prebuilt Qt ship no
    # fontconfig headers, and libQt6Gui.so already provides (and exports) the Fc*
    # symbols of its statically linked fontconfig.
    ${CMAKE_CURRENT_LIST_DIR}/fontconfig-shim
)

target_compile_definitions(qohos PRIVATE
    NODE_ADDON_API_ENABLE_TYPE_CHECK_ON_AS
    NAPI_CPP_EXCEPTIONS
    QT_NO_CAST_FROM_ASCII
    QT_NO_DYNAMIC_CAST
    VK_USE_PLATFORM_OHOS=1
)

target_link_libraries(qohos PRIVATE
    Qt6::Core Qt6::CorePrivate
    Qt6::Gui Qt6::GuiPrivate
    Qt6::OpenGL Qt6::OpenGLPrivate
)

# Match the official prebuilt plugin: the SDK toolchain default (full RELRO with
# immediate binding) is exactly what the prebuilt libqohos.so uses as well, so no
# binding-flag override is applied here.

# OHOS NDK stub libraries. They stay unresolved at link time on device and are
# resolved by the system at load time; linking them keeps NEEDED identical to the
# official prebuilt plugin.
set(OHOS_STUBS
    EGL
    GLESv3
    ace_napi.z
    ace_ndk.z
    hiappevent_ndk.z
    hilog_ndk.z
    native_display_manager
    native_vsync
    native_window
    native_window_manager
    ohfileshare
    ohfileuri
    ohhicollie
    ohinput
    pasteboard
    pixelmap
    qos
    udmf
    ohinputmethod
)
foreach(stub IN LISTS OHOS_STUBS)
    target_link_libraries(qohos PRIVATE "${OHOS_STUB_DIR}/lib${stub}.so")
endforeach()
