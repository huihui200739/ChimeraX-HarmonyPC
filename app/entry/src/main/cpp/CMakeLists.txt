cmake_minimum_required(VERSION 3.24)
project(chimerax_harmony_native LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The private CPython shared library ships as a packaging input (libs/arm64-v8a)
# and is produced by tools/build_cpython_harmony.py; it is not a prebuilt host lib.
set(CX_PYTHON_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/arm64-v8a")

add_library(chimerax_native SHARED chimerax_native.cpp)
target_include_directories(chimerax_native PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/python-include")
target_link_directories(chimerax_native PRIVATE "${CX_PYTHON_LIB_DIR}")
target_link_libraries(chimerax_native PRIVATE python3.11 ace_napi.z hilog_ndk.z dl)
target_link_options(chimerax_native PRIVATE -Wl,--no-undefined)
set_target_properties(chimerax_native PROPERTIES OUTPUT_NAME chimerax_native)
