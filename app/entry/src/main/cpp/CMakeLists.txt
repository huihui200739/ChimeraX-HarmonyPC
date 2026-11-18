cmake_minimum_required(VERSION 3.24)
project(chimerax_harmony_native LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The private CPython shared library ships as a packaging input (libs/arm64-v8a)
# and is produced by tools/build_cpython_harmony.py; it is not a prebuilt host lib.
set(CX_PYTHON_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/arm64-v8a")

add_library(chimerax_native SHARED chimerax_native.cpp gl_surface.cpp)
target_include_directories(chimerax_native PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/python-include")
target_link_directories(chimerax_native PRIVATE "${CX_PYTHON_LIB_DIR}")
target_link_libraries(chimerax_native PRIVATE python3.11 ace_napi.z ace_ndk.z hilog_ndk.z native_window EGL GLESv3 z dl)
target_link_options(chimerax_native PRIVATE -Wl,--no-undefined)
set_target_properties(chimerax_native PROPERTIES OUTPUT_NAME chimerax_native)

# snippets/qt-ohos/CMakeLists.append.cmake
#
# 把这段追加到 app/entry/src/main/cpp/CMakeLists.txt 末尾。
# 产物 entry/libs/arm64-v8a/libchimeraxqt.so —— 与 QAbilityStage.ets 的
# APP_LIBRARY_NAME 必须逐字相同, 否则 qohosjsmain.cpp:288 的 dlopen 直接 abort。

add_library(chimeraxqt SHARED qt_launcher.cpp)

# 复用现有 CPython 头(libchimerax_native 已用同一份 python-include)。
target_include_directories(chimeraxqt PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/python-include")

# CX_PYTHON_LIB_DIR 在现有 CMakeLists.txt 顶部已定义为
# ${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/arm64-v8a, 此处直接复用。
target_link_directories(chimeraxqt PRIVATE "${CX_PYTHON_LIB_DIR}")
target_link_libraries(chimeraxqt PRIVATE
    python3.11
    hilog_ndk.z
    dl)

# 故意不链 Qt6Core/Gui/Widgets:
#   1) 进程里 Qt 已由 libqohos.so 加载, 再链一份会把 Qt 全局状态分成两份
#      (两个 QCoreApplication 视图/两套 qpa), 表现为 "QWidget: Must construct a
#      QApplication before a QWidget" 或直接段错误;
#   2) Python 侧 PySide6 自己 dlopen libQt6Core.so。
# 需要 Qt 的只有 libchimeraxqt 内嵌的 Python 解释器, 它通过 PySide6 拿到同一份 Qt。

# main 必须是导出符号(dlsym "main"), extern "C" 已在源码里; 编译器仍会抱怨
# 'main' should not be 'extern "C"', 这是预期警告。
target_compile_options(chimeraxqt PRIVATE -Wno-main)
target_link_options(chimeraxqt PRIVATE -Wl,--no-undefined)

set_target_properties(chimeraxqt PROPERTIES OUTPUT_NAME chimeraxqt)
