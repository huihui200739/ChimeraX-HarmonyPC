# Generic cross-target configuration. It does not enable a full application build.
ifndef HARMONY_NATIVE_SDK
$(error HARMONY_NATIVE_SDK must name an installed native SDK)
endif
ifeq (,$(wildcard $(HARMONY_NATIVE_SDK)/llvm/bin/clang))
$(error Native SDK compiler not found in HARMONY_NATIVE_SDK)
endif
HARMONY_TARGET_TRIPLE = aarch64-linux-ohos
HARMONY_SYSROOT = $(HARMONY_NATIVE_SDK)/sysroot
# Internal build identifier, NOT a claim of a supported Python wheel platform.
BIN_PLATFORM = harmony_aarch64
OBJ_EXT = o
LIB_EXT = a
SHLIB_EXT = so
PYMOD_EXT = so
PROG_EXT =
CC = "$(HARMONY_NATIVE_SDK)/llvm/bin/clang" --target=$(HARMONY_TARGET_TRIPLE) --sysroot="$(HARMONY_SYSROOT)" -fPIC -std=gnu99
CXX = "$(HARMONY_NATIVE_SDK)/llvm/bin/clang++" --target=$(HARMONY_TARGET_TRIPLE) --sysroot="$(HARMONY_SYSROOT)" -fPIC -std=c++11
LOADER = $(CXX)
LIB_LINK = "$(HARMONY_NATIVE_SDK)/llvm/bin/llvm-ar" rcs $(LIBRARY) $(OBJS)
RANLIB = "$(HARMONY_NATIVE_SDK)/llvm/bin/llvm-ranlib"
SHLIB_LINK = $(LOADER) $(LDFLAGS) -shared -Wl,--no-undefined -o $(SHLIB) $(OBJS) $(LIBS)
PYMOD_LINK = $(LOADER) $(LDFLAGS) -shared -o $(PYMOD) $(OBJS) $(LIBS) $(PYTHON_LIB)
PROG_LINK = $(LOADER) $(LDFLAGS) -Wl,--no-undefined -o $(PROG) $(OBJS) $(LIBS)
OPT = -O2 -Wall -Wextra -fstack-protector-strong
INCS = -I"$(includedir)"
LIBS = -L"$(libdir)"
PYTHON_LIB = -L"$(libdir)" -lpython$(PYTHON_VERSION)$(PYTHON_ABI)
# Desktop OpenGL is not replaced by GLES. Supply a validated backend separately.
OPENGL_LIBS = $(HARMONY_OPENGL_LIBS)
LDFLAGS += -Wl,-z,relro,-z,now
NO_PREBUILT = 1
# Upstream full-build recipes execute target interpreters and fetch dependencies.
# Do not silently run those recipes on the development host as a cross-build.
ifneq (,$(filter install build-minimal uv-build uv-install install-rbvi test pytest,$(MAKECMDGOALS)))
$(error Full upstream cross-build is not enabled; use the standalone harmony startup-adapter build)
endif
