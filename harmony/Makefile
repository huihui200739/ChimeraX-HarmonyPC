# Local build only. No simulator, deployment, installation or device target.
CX_HARMONY_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ifdef HARMONY_NATIVE_SDK
CX_SDK_ARG = --sdk "$(HARMONY_NATIVE_SDK)"
endif
.PHONY: all
all:
	python3 "$(CX_HARMONY_DIR)../tools/build_harmony_local.py" $(CX_SDK_ARG)
