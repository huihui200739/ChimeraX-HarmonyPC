#!/usr/bin/env python3
"""Qt 6 for OpenHarmony cross-configuration probe (host-only, no device access).

Purpose: collect reproducible, host-side evidence about what blocks a Qt 6
cross build for aarch64-linux-ohos with the DevEco/OpenHarmony native SDK:
toolchain sanity, QPA dependency header/library surface, a real cross-compile
smoke test, and the real configure() failure of qtbase.

Nothing here talks to a device, emulator or hdc. All artifacts stay under
build/qt/ (sources, logs, probe scratch) and the JSON report goes to reports/.

Usage:
  python3 tools/qt_ohos_probe.py --report reports/qt-ohos-probe-2026-11-17.json
  python3 tools/qt_ohos_probe.py --jobs env,headers,smoke,configure,prebuilt
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_QT = PROJECT_ROOT / "build" / "qt"
SCRATCH = BUILD_QT / "probe"
LOGS = BUILD_QT / "logs"
DEFAULT_SDK_CANDIDATES = [
    Path("/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony"),
    Path.home() / "Library/OpenHarmony/Sdk/latest/openharmony",
    Path("/opt/ohos-sdk/openharmony"),
]

# Qt 6.12.0 src/plugins/platforms/ohos/CMakeLists.txt target_link_libraries().
QPA_LINK_LIBS = [
    "EGL", "GLESv3",
    "ace_napi.z", "ace_ndk.z", "hiappevent_ndk.z", "hilog_ndk.z",
    "native_display_manager", "native_vsync", "native_window",
    "native_window_manager", "ohfileshare", "ohfileuri", "ohhicollie",
    "ohinput", "pasteboard", "pixelmap", "qos", "udmf", "ohinputmethod",
]

# Header surface the OHOS QPA needs, with the paths that actually exist in the
# OpenHarmony 6.1.1.125 (API 24) SDK. Alternatives are tried in order; the
# first existing path wins, and a glob fallback catches future SDK shuffles.
QPA_HEADERS = [
    ("ArkUI native node (window/embedded node)", ["arkui/native_node.h", "ace/xcomponent/native_interface_xcomponent.h"]),
    ("ArkUI native type", ["arkui/native_type.h"]),
    ("ArkUI native interface", ["arkui/native_interface.h"]),
    ("ArkUI native key event", ["arkui/native_key_event.h"]),
    ("ArkUI native animate", ["arkui/native_animate.h"]),
    ("EGL", ["EGL/egl.h", "EGL/eglext.h"]),
    ("GLES3", ["GLES3/gl3.h"]),
    ("GLES2", ["GLES2/gl2.h"]),
    ("native window", ["native_window/external_window.h"]),
    ("native window buffer", ["native_buffer/native_buffer.h"]),
    ("native vsync", ["native_vsync/native_vsync.h"]),
    ("display manager", ["window_manager/oh_display_manager.h", "native_display_manager/native_display_manager.h"]),
    ("window manager", ["window_manager/oh_window.h", "native_window_manager/native_window_manager.h"]),
    ("UDMF (drag and drop)", ["database/udmf/udmf.h"]),
    ("pasteboard (clipboard)", ["database/pasteboard/oh_pasteboard.h"]),
    ("inputmethod controller", ["inputmethod/inputmethod_controller_capi.h"]),
    ("inputmethod text editor proxy", ["inputmethod/inputmethod_text_editor_proxy_capi.h"]),
    ("multimodal input (key/mouse/touch)", ["multimodalinput/oh_input_manager.h", "ohinput/oh_input_manager.h"]),
    ("pixelmap", ["multimedia/image_framework/image/pixelmap_native.h", "image/pixelmap_native.h"]),
    ("hicollie (watchdog)", ["hicollie/hicollie.h"]),
    ("hiappevent", ["hiappevent/hiappevent.h"]),
    ("hilog", ["hilog/log.h"]),
    ("file share", ["filemanagement/fileshare/oh_file_share.h", "filemanagement/oh_file_share.h"]),
    ("file uri", ["filemanagement/file_uri/oh_file_uri.h"]),
    ("qos", ["qos/qos.h"]),
]

CONFIGURE_ERROR_RE = re.compile(
    r"(CMake Error.*|ERROR:.*|error:.*|Fatal error.*|\*\*\*.*|"
    r".*not found.*|.*No such file.*|.*Cannot find.*)", re.IGNORECASE)


# ----------------------------------------------------------------- utilities
def run(cmd: list[str], cwd: Path | None, timeout: int = 300,
        env: dict | None = None) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                             capture_output=True, text=True, timeout=timeout,
                             env=env, errors="replace")
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc = "timeout"
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    except FileNotFoundError as exc:
        rc, out, err = "missing", "", str(exc)
    return {"cmd": cmd, "cwd": str(cwd) if cwd else None, "returncode": rc,
            "duration_s": round(time.time() - started, 2),
            "stdout_tail": out[-8000:], "stderr_tail": err[-8000:],
            "stdout_lines": len(out.splitlines())}


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def which(names: list[str]) -> dict:
    return {n: shutil.which(n) for n in names}


def find_host_qt() -> dict:
    """Look for an existing Qt 6 host build (needed by -qt-host-path)."""
    found: dict = {"candidates": [], "usable": None, "qt_version": None}
    env_host = os.environ.get("QT_HOST_PATH") or os.environ.get("HOST_QT_PATH")
    if env_host:
        found["candidates"].append({"source": "env", "path": env_host, "exists": Path(env_host).exists()})
    probes = which(["qmake", "qmake6", "qtpaths", "qtpaths6", "moc"])
    found["path_lookup"] = probes
    dirs = [Path.home() / "Qt", Path("/opt/homebrew/opt"), Path("/usr/local/opt"), Path("/usr/local/Qt")]
    for base in dirs:
        if not base.is_dir():
            continue
        for child in sorted(base.glob("*"))[:40]:
            name = child.name.lower()
            if "qt" not in name:
                continue
            for cand in (child / "bin" / "moc", child / "libexec" / "moc", child / "macos" / "bin" / "moc"):
                found["candidates"].append({"source": str(base), "path": str(cand), "exists": cand.exists()})
                if cand.exists():
                    found["usable"] = str(cand.parent.parent)
    if probes.get("moc"):
        found["usable"] = found["usable"] or str(Path(probes["moc"]).parent.parent)
    return found


def sdk_identity(sdk_root: Path) -> dict:
    native = sdk_root / "native"
    info = read_json(native / "oh-uni-package.json") or {}
    ets = read_json(sdk_root / "ets" / "oh-uni-package.json") or {}
    return {"sdk_root": str(sdk_root), "native_package": info,
            "ets_package": ets,
            "components": sorted(p.name for p in sdk_root.iterdir()) if sdk_root.is_dir() else []}


# ------------------------------------------------------------------- jobs
def job_env(args) -> dict:
    sdk_root = Path(args.sdk).expanduser() if args.sdk else None
    if sdk_root is None or not (sdk_root / "native").is_dir():
        for cand in DEFAULT_SDK_CANDIDATES:
            if (cand / "native").is_dir():
                sdk_root = cand
                break
    result: dict = {
        "host": {"system": platform.system(), "release": platform.release(),
                 "machine": platform.machine(), "python": sys.version.split()[0]},
        "sdk": sdk_identity(sdk_root) if sdk_root else {"error": "no SDK with native/ found"},
        "tools": which(["git", "cmake", "ninja", "ninja-build", "python3", "clang", "llvm-readelf"]),
    }
    if sdk_root:
        clang = sdk_root / "native" / "llvm" / "bin" / "clang"
        cxx = sdk_root / "native" / "llvm" / "bin" / "clang++"
        result["sdk_tools"] = {
            "clang": str(clang), "clang_exists": clang.exists(),
            "clang++_exists": cxx.exists(),
            "cmake_in_sdk": str(sdk_root / "native/build-tools/cmake/bin/cmake"),
            "cmake_in_sdk_exists": (sdk_root / "native/build-tools/cmake/bin/cmake").exists(),
            "ninja_in_sdk_exists": (sdk_root / "native/build-tools/cmake/bin/ninja").exists(),
            "toolchain_file": str(sdk_root / "native/build/cmake/ohos.toolchain.cmake"),
            "toolchain_file_exists": (sdk_root / "native/build/cmake/ohos.toolchain.cmake").exists(),
            "libcxx_headers": str(sdk_root / "native/llvm/include/c++/v1"),
            "libcxx_headers_exist": (sdk_root / "native/llvm/include/c++/v1").is_dir(),
            "libcxx_static": str(sdk_root / "native/llvm/lib/aarch64-linux-ohos/libc++_static.a"),
            "libcxx_static_exists": (sdk_root / "native/llvm/lib/aarch64-linux-ohos/libc++_static.a").exists(),
        }
        v = run([str(clang), "--version"], None, 60)
        result["clang_version"] = v["stdout_tail"].strip().splitlines()[:2]
        devnull = {"returncode": 0}
        verdict = (result["sdk_tools"]["toolchain_file_exists"]
                   and result["sdk_tools"]["clang_exists"]
                   and result["sdk_tools"]["libcxx_static_exists"])
        result["verdict"] = "sdk_ready_for_cross_compile" if verdict else "sdk_incomplete"
    result["host_qt"] = find_host_qt()
    usage = shutil.disk_usage(PROJECT_ROOT)
    result["disk"] = {"free_gib": round(usage.free / 2**30, 1)}
    return result


def job_headers(env_result: dict) -> dict:
    sdk_root = Path(env_result["sdk"]["sdk_root"])
    include = sdk_root / "native/sysroot/usr/include"
    libdir = sdk_root / "native/sysroot/usr/lib/aarch64-linux-ohos"
    headers, missing = {}, []
    for label, cands in QPA_HEADERS:
        hit = next((include / c for c in cands if (include / c).is_file()), None)
        headers[label] = str(hit.relative_to(include)) if hit else None
        if not hit:
            missing.append(label)
    libs, missing_libs = {}, []
    for lib in QPA_LINK_LIBS:
        hit = next((libdir / f"lib{lib}{ext}" for ext in (".so", ".a") if (libdir / f"lib{lib}{ext}").exists()), None)
        libs[lib] = str(hit.relative_to(libdir)) if hit else None
        if not hit:
            missing_libs.append(lib)
    total = len(QPA_HEADERS) + len(QPA_LINK_LIBS)
    return {"include_dir": str(include), "lib_dir": str(libdir),
            "headers": headers, "libs": libs,
            "missing_headers": missing, "missing_libs": missing_libs,
            "coverage": f"{total - len(missing) - len(missing_libs)}/{total}",
            "verdict": "qpa_surface_complete" if not missing and not missing_libs
                       else "qpa_surface_has_gaps"}


SMOKE_PURE = r"""
#include <cstdio>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <unordered_map>
#include <cstdint>

int main() {
    std::filesystem::path p("/tmp/qt-ohos-probe");
    std::mutex m; std::unordered_map<std::string, int> hits;
    std::thread t([&]{ std::lock_guard<std::mutex> g(m); hits["thread"] = 1; });
    t.join();
    std::vector<double> v{1.0, 2.0, 3.0};
    double s = 0; for (double x : v) s += std::sqrt(x);
    std::printf("cpp17 ok %s %.3f %zu\n", p.string().c_str(), s, hits.size());
    return 0;
}
"""

SMOKE_OHOS = r"""
// Compile-only check of the OpenHarmony header surface the Qt OHOS QPA uses.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <arkui/native_node.h>
#include <arkui/native_type.h>
#include <arkui/native_interface.h>
#include <hilog/log.h>
#include <database/udmf/udmf.h>
#include <database/pasteboard/oh_pasteboard.h>
#include <native_window/external_window.h>
#include <native_buffer/native_buffer.h>
#include <native_vsync/native_vsync.h>
#include <window_manager/oh_display_manager.h>
#include <inputmethod/inputmethod_controller_capi.h>
#include <inputmethod/inputmethod_text_editor_proxy_capi.h>
#include <inputmethod/inputmethod_attach_options_capi.h>

// Types only: this TU proves the headers parse under C++17, nothing is called.
struct ProbeSurface {
    EGLDisplay dpy = EGL_NO_DISPLAY;
    ArkUI_NodeHandle node = nullptr;
    OHNativeWindow *win = nullptr;
    OH_Pasteboard *board = nullptr;
    OH_UdmfData *data = nullptr;
    OH_NativeVSync *vsync = nullptr;
    uint64_t display_id = 0;
    InputMethod_TextEditorProxy *proxy = nullptr;
    InputMethod_AttachOptions *attach = nullptr;
};
int probe_surface_size() { return static_cast<int>(sizeof(ProbeSurface)); }
"""

SMOKE_LINK = r"""
// Link check: EGL + GLES3 + hilog, the minimum a Qt OHOS platform plugin needs.
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <hilog/log.h>

extern "C" int probe_link_smoke() {
    EGLDisplay dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    GLuint sh = glCreateShader(GL_VERTEX_SHADER);
    OH_LOG_Print(LOG_APP, LOG_INFO, 0, "qtprobe", "probe %{public}d", (int)sh);
    return (dpy == EGL_NO_DISPLAY) ? 1 : 0;
}
"""


def _sdk_flags(sdk_root: Path, arch: str) -> dict:
    native = sdk_root / "native"
    triple = {"arm64-v8a": "aarch64-linux-ohos", "x86_64": "x86_64-linux-ohos",
              "armeabi-v7a": "arm-linux-ohos"}[arch]
    return {"native": native, "triple": triple,
            "sysroot": native / "sysroot",
            "llvm": native / "llvm"}


def job_smoke(env_result: dict, arch: str) -> dict:
    sdk_root = Path(env_result["sdk"]["sdk_root"])
    f = _sdk_flags(sdk_root, arch)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    clang = f["llvm"] / "bin" / "clang"
    base = ["--sysroot=" + str(f["sysroot"]), "--target=" + f["triple"],
            "-std=c++17", "-fPIC", "-O1", "-Wall"]
    out: dict = {}
    # Step 1: plain C++17 stdlib (libc++ + musl) object.
    src = SCRATCH / "smoke_pure.cpp"
    src.write_text(SMOKE_PURE, encoding="utf-8")
    obj = SCRATCH / "smoke_pure.o"
    out["pure_cxx17"] = run([str(clang), *base, "-c", str(src), "-o", str(obj)], SCRATCH, 300)
    out["pure_cxx17"]["object_written"] = obj.exists()
    if obj.exists():
        out["pure_cxx17"]["elf"] = _elf_info(f["llvm"], obj)
    # Step 2: compile-only TU over the OHOS header surface the QPA includes.
    src2 = SCRATCH / "smoke_ohos.cpp"
    src2.write_text(SMOKE_OHOS, encoding="utf-8")
    obj2 = SCRATCH / "smoke_ohos.o"
    out["ohos_headers_compile"] = run([str(clang), *base, "-c", str(src2), "-o", str(obj2)], SCRATCH, 300)
    out["ohos_headers_compile"]["object_written"] = obj2.exists()
    # Step 3: link check against EGL/GLES3/hilog only (no unstable symbol names).
    src3 = SCRATCH / "smoke_link.cpp"
    src3.write_text(SMOKE_LINK, encoding="utf-8")
    so = SCRATCH / "libsmoke_ohos.so"
    libdir = f["sysroot"] / "usr/lib" / f["triple"]
    links = ["-L" + str(libdir), "-lEGL", "-lGLESv3", "-lhilog_ndk.z",
             "-lunwind", "-shared", "-Wl,--no-undefined"]
    out["ohos_link"] = run([str(clang), *base, str(src3), "-o", str(so), *links], SCRATCH, 300)
    out["ohos_link"]["built"] = so.exists()
    if so.exists():
        out["ohos_link"]["elf"] = _elf_info(f["llvm"], so)
    ok = (out["pure_cxx17"].get("returncode") == 0
          and out["ohos_headers_compile"].get("object_written")
          and out["ohos_link"].get("built"))
    out["verdict"] = "cross_toolchain_works" if ok else "cross_toolchain_blocked"
    out["log_dir"] = str(LOGS)
    return out


def _elf_info(llvm: Path, path: Path) -> dict:
    readelf = llvm / "bin" / "llvm-readelf"
    if not readelf.exists():
        return {"error": "llvm-readelf missing"}
    r = run([str(readelf), "-h", str(path)], path.parent, 60)
    info = {}
    for line in r["stdout_tail"].splitlines():
        if "Machine:" in line or "Class:" in line or "Type:" in line:
            info[line.split(":")[0].strip()] = line.split(":", 1)[1].strip()
    return info


def job_configure(env_result: dict, qtbase: Path, arch: str, timeout: int) -> dict:
    configure = qtbase / "configure"
    if not configure.exists():
        return {"status": "skipped", "reason": f"{configure} not found (source not fetched yet)"}
    sdk_root = Path(env_result["sdk"]["sdk_root"])
    build_dir = BUILD_QT / "build-configure-probe"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    common = ["-ohos-sdk", str(sdk_root), "-ohos-arch", arch,
              "-nomake", "examples", "-nomake", "tests",
              "-no-dbus", "-no-openssl", "-no-cups",
              "-prefix", str(BUILD_QT / "install-probe")]
    runs = {}
    ascii_prefix = "/tmp/qt-ohos-install-probe"
    prebuilt = BUILD_QT / "prebuilt" / "harmonyos-arm64"
    variants = {
        # 1. host PATH as-is; cmake is not on it on this machine.
        "bare_path": (common + ["-prefix", ascii_prefix], False),
        # 2. the SDK's bundled cmake/ninja is put on PATH.
        "sdk_cmake_on_path": (common + ["-prefix", ascii_prefix], True),
        # 3. same, but a prefix path that contains CJK characters.
        "cjk_prefix": (common + ["-prefix", str(BUILD_QT / "install-probe")], True),
        # 4. -qt-host-path pointing at the OHOS target prebuilt (wrong arch on purpose).
        "host_qt_ohos_prebuilt": (common + ["-prefix", ascii_prefix, "-qt-host-path", str(prebuilt)], True),
    }
    host = env_result.get("host_qt", {}).get("usable")
    if host:
        variants["with_host_qt"] = (common + ["-prefix", ascii_prefix, "-qt-host-path", host], True)
    for name, (opts, augment_path) in variants.items():
        cmd = [str(configure), *opts]
        run_dir = build_dir / name
        run_dir.mkdir(parents=True, exist_ok=True)
        log = LOGS / f"configure-{name}.log"
        env = dict(os.environ)
        if augment_path:
            extra = [str(sdk_root / "native/build-tools/cmake/bin")]
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        started = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(run_dir), capture_output=True,
                                  text=True, timeout=timeout, errors="replace", env=env)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            rc = "timeout"
            out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
            err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        log.write_text(f"$ {' '.join(cmd)}\n\n=== stdout ===\n{out}\n=== stderr ===\n{err}\n", encoding="utf-8")
        errors = [ln.strip() for ln in (out + "\n" + err).splitlines() if CONFIGURE_ERROR_RE.match(ln.strip())]
        runs[name] = {"cmd": cmd, "cwd": str(run_dir), "returncode": rc,
                      "sdk_cmake_on_path": augment_path,
                      "duration_s": round(time.time() - started, 2),
                      "log": str(log.relative_to(PROJECT_ROOT)),
                      "error_lines": errors[:25],
                      "stdout_tail": out[-4000:], "stderr_tail": err[-4000:]}
    return {"status": "executed", "qtbase": str(qtbase), "variants": runs,
            "verdict": "configure_failed" if all(r["returncode"] != 0 for r in runs.values())
                       else "configure_succeeded"}


def job_prebuilt(env_result: dict) -> dict:
    root = BUILD_QT / "prebuilt" / "harmonyos-arm64"
    libs = sorted(root.rglob("libqohos.so")) + sorted(root.rglob("libQt6Gui.so"))
    sdk_root = Path(env_result["sdk"]["sdk_root"]) if env_result.get("sdk", {}).get("sdk_root") else None
    syslib = sdk_root / "native/sysroot/usr/lib/aarch64-linux-ohos" if sdk_root else None
    sdk_llvm_lib = sdk_root / "native/llvm/lib/aarch64-linux-ohos" if sdk_root else None
    llvm = sdk_root / "native/llvm/bin" if sdk_root else None
    if not root.is_dir():
        return {"status": "skipped", "reason": "no prebuilt tree under build/qt/prebuilt/harmonyos-arm64"}
    result: dict = {"path": str(root), "libraries": {}}
    for lib in libs:
        entry: dict = {"size": lib.stat().st_size}
        if llvm and (llvm / "llvm-readelf").exists():
            hdr = run([str(llvm / "llvm-readelf"), "-h", str(lib)], lib.parent, 60)
            entry["header_lines"] = [ln for ln in hdr["stdout_tail"].splitlines()
                                     if "Machine:" in ln or "Class:" in ln or "Type:" in ln]
            dyn = run([str(llvm / "llvm-readelf"), "-d", str(lib)], lib.parent, 60)
            needed = re.findall(r"NEEDED\).*\[([^\]]+)\]", dyn["stdout_tail"])
            soname = re.findall(r"SONAME\).*\[([^\]]+)\]", dyn["stdout_tail"])
            entry["needed"] = needed
            entry["soname"] = soname
            entry["needed_resolution"] = {
                n: _resolve_needed(n, root, syslib, sdk_llvm_lib) for n in needed}
        result["libraries"][lib.name] = entry
    unresolved = {lib: [n for n, v in e.get("needed_resolution", {}).items() if v is None]
                  for lib, e in result["libraries"].items()}
    by_class: dict[str, list[str]] = {}
    for e in result["libraries"].values():
        for name, where in e.get("needed_resolution", {}).items():
            if where:
                by_class.setdefault(where.split(":")[0], []).append(name)
    result["unresolved_needed"] = {k: v for k, v in unresolved.items() if v}
    result["resolution_classes"] = {k: sorted(set(v)) for k, v in by_class.items()}
    result["verdict"] = "prebuilt_loadable_against_sdk" if not result["unresolved_needed"] else "prebuilt_has_unresolved_deps"
    return result


def _resolve_needed(name: str, root: Path, syslib: Path | None,
                    sdk_llvm_lib: Path | None = None) -> str | None:
    """Where does a NEEDED entry come from? system_ndk / app_side / prebuilt_qt."""
    if syslib:
        for cand in (syslib / name, syslib / (name + ".so")):
            if cand.exists():
                return "system_ndk:" + str(cand)
    if sdk_llvm_lib:
        for cand in (sdk_llvm_lib / name, sdk_llvm_lib / "c++" / name):
            if cand.exists():
                return "app_side:" + str(cand)
    for cand in root.rglob(name):
        return "prebuilt_qt:" + str(cand)
    return None


# ------------------------------------------------------------------- driver
JOBS = {
    "env": lambda a, e: job_env(a),
    "headers": lambda a, e: job_headers(e),
    "smoke": lambda a, e: job_smoke(e, a.arch),
    "configure": lambda a, e: job_configure(e, Path(a.qtbase), a.arch, a.configure_timeout),
    "prebuilt": lambda a, e: job_prebuilt(e),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report", type=Path, default=PROJECT_ROOT / "reports/qt-ohos-probe-2026-11-17.json")
    p.add_argument("--jobs", default="env,headers,smoke,configure,prebuilt")
    p.add_argument("--sdk", default=None, help="OpenHarmony SDK root containing native/")
    p.add_argument("--qtbase", default=str(BUILD_QT / "src" / "qtbase"))
    p.add_argument("--arch", default="arm64-v8a", choices=["arm64-v8a", "x86_64", "armeabi-v7a"])
    p.add_argument("--configure-timeout", type=int, default=1500)
    args = p.parse_args(argv)

    selected = [j.strip() for j in args.jobs.split(",") if j.strip()]
    unknown = [j for j in selected if j not in JOBS]
    if unknown:
        p.error(f"unknown job(s): {', '.join(unknown)}")
    BUILD_QT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "host-side evidence for Qt 6 on OpenHarmony cross build feasibility",
        "scope": "no device, emulator or hdc access; sources and logs under build/qt/",
        "arch": args.arch,
        "jobs_run": selected,
        "results": {},
    }
    env_result = None
    for name in selected:
        if name == "env" or env_result is None:
            if name == "env":
                env_result = job_env(args)
                report["results"]["env"] = env_result
                continue
            env_result = job_env(args)
            report["results"]["env"] = env_result
        report["results"][name] = JOBS[name](args, env_result)
        _save(args.report, report)
    report["conclusions"] = _conclusions(report)
    _save(args.report, report)
    print(json.dumps(report["conclusions"], ensure_ascii=False, indent=2))
    return 0


def _conclusions(report: dict) -> list[str]:
    r = report["results"]
    out = []
    env = r.get("env", {})
    if env:
        out.append(f"SDK: {env.get('sdk', {}).get('sdk_root')} "
                   f"(native {env.get('sdk', {}).get('native_package', {}).get('version')}, "
                   f"API {env.get('sdk', {}).get('native_package', {}).get('apiVersion')})")
        out.append(f"host Qt for -qt-host-path: {env.get('host_qt', {}).get('usable') or 'NOT FOUND'}")
    if "headers" in r:
        h = r["headers"]
        out.append(f"QPA 依赖面覆盖: {h.get('coverage')} "
                   f"(缺头文件 {h.get('missing_headers')}, 缺库 {h.get('missing_libs')})")
    if "smoke" in r:
        out.append(f"交叉编译冒烟: {r['smoke'].get('verdict')}")
    if "configure" in r:
        c = r["configure"]
        if c.get("status") == "executed":
            for name, runinfo in c["variants"].items():
                first = (runinfo["error_lines"][0] if runinfo["error_lines"] else "no error lines captured")
                out.append(f"configure[{name}] exit={runinfo['returncode']} → {first}")
        else:
            out.append(f"configure: {c.get('reason')}")
    if "prebuilt" in r:
        out.append(f"预编译包: {r['prebuilt'].get('verdict')}")
    return out


def _save(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
