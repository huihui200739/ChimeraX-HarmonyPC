#!/usr/bin/env python3
"""Standalone empty Qt window. No ChimeraX import, data loading or research functions."""
from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from pathlib import Path


def save(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", choices=("PyQt6", "PySide6"), default="PyQt6")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--quit-after", type=float, default=0,
                        help="Seconds; 0 waits for manual close. At least 3 seconds otherwise.")
    parser.add_argument("--opengl", action="store_true", help="Try an empty OpenGL 3.3 core widget")
    args = parser.parse_args(argv)
    if args.quit_after and args.quit_after < 3:
        parser.error("--quit-after must be 0 or at least 3")
    report = {"schema_version": 1, "status": "initializing", "binding": args.binding,
              "host_system": platform.system(), "architecture": platform.machine(),
              "upstream_app_launched": False, "port_validated": False,
              "automatic_checks": {},
              "manual_checks_pending": ["Chinese IME", "high-DPI and multi-monitor behavior",
                                        "file-dialog selection and cancel", "keyboard and mouse",
                                        "real HarmonyOS PC packaging and launch"]}
    # Save before Qt initializes: an aborted native plugin load must not leave a pass report.
    save(args.report, report)
    try:
        core = importlib.import_module(f"{args.binding}.QtCore")
        gui = importlib.import_module(f"{args.binding}.QtGui")
        widgets = importlib.import_module(f"{args.binding}.QtWidgets")
        test = importlib.import_module(f"{args.binding}.QtTest")
        gl_widget = None
        if args.opengl:
            gl_widget = importlib.import_module(f"{args.binding}.QtOpenGLWidgets").QOpenGLWidget
            surface = gui.QSurfaceFormat()
            surface.setVersion(3, 3)
            surface.setProfile(gui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            surface.setRenderableType(gui.QSurfaceFormat.RenderableType.OpenGL)
            gui.QSurfaceFormat.setDefaultFormat(surface)
    except (ImportError, OSError) as exc:
        report.update(status="blocked_missing_runtime", error=str(exc))
        save(args.report, report)
        print(f"Qt runtime unavailable: {exc}", file=sys.stderr)
        return 2

    app = widgets.QApplication([sys.argv[0]])
    app.setApplicationName("Generic desktop compatibility probe")
    window = widgets.QMainWindow()
    window.setWindowTitle("通用桌面兼容性检查 — 非 ChimeraX 应用")
    central = widgets.QWidget()
    layout = widgets.QVBoxLayout(central)
    layout.addWidget(widgets.QLabel("仅测试空白窗口、通用控件与显示环境，不加载任何项目数据。"))
    text = widgets.QLineEdit()
    text.setPlaceholderText("请手动检查中文输入法与键盘操作")
    layout.addWidget(text)
    button = widgets.QPushButton("手动检查文件选择器（不读取文件）")
    layout.addWidget(button)
    layout.addWidget(widgets.QComboBox())
    central.findChild(widgets.QComboBox).addItems(["100%", "150%", "200%"])
    surface_widget = gl_widget() if gl_widget else None
    if surface_widget:
        layout.addWidget(surface_widget)
    window.setCentralWidget(central)
    window.menuBar().addMenu("菜单测试").addAction("关闭", window.close)
    window.statusBar().showMessage("此窗口不是完整应用，也不是鸿蒙适配成功证明")
    window.resize(900, 600)

    def choose_file() -> None:
        # User-initiated native dialog only. Returned paths and file contents are not saved/read.
        widgets.QFileDialog.getOpenFileName(window, "通用文件选择器", "", "All files (*)")

    button.clicked.connect(choose_file)
    report["qt_version"] = core.qVersion()
    report["platform_plugin"] = app.platformName()
    report["interactive_plugin"] = app.platformName().lower() not in ("offscreen", "minimal", "minimalegl")
    screen = app.primaryScreen()
    if screen:
        report["screen"] = {"width": screen.size().width(), "height": screen.size().height(),
                            "device_pixel_ratio": screen.devicePixelRatio(),
                            "logical_dpi": screen.logicalDotsPerInch()}
    report["status"] = "window_pending_checks"
    save(args.report, report)

    def check_window() -> None:
        try:
            checks = report["automatic_checks"]
            checks["window_visible"] = window.isVisible()
            checks["nonzero_size"] = window.width() > 0 and window.height() > 0
            text.setText("")
            text.setFocus()
            test.QTest.keyClicks(text, "generic-ui-test")
            checks["synthetic_ascii_key_events"] = text.text() == "generic-ui-test"
            text.clear()
            if surface_widget:
                context = surface_widget.context()
                checks["opengl_context_valid"] = bool(context and context.isValid())
                if context:
                    fmt = context.format()
                    report["opengl"] = {"major": fmt.majorVersion(), "minor": fmt.minorVersion(),
                                        "is_es": context.isOpenGLES()}
                    checks["desktop_opengl_3_3_or_newer"] = (
                        context.isValid() and not context.isOpenGLES()
                        and (fmt.majorVersion(), fmt.minorVersion()) >= (3, 3))
            report["status"] = ("automatic_checks_passed_manual_pending"
                                if all(checks.values()) and report["interactive_plugin"]
                                else "automatic_checks_failed_or_headless")
        except Exception as exc:
            report.update(status="check_error", error=str(exc))
        save(args.report, report)

    window.show()
    core.QTimer.singleShot(1200, check_window)
    if args.quit_after:
        core.QTimer.singleShot(int(args.quit_after * 1000), app.quit)
    app.exec()
    save(args.report, report)
    return 0 if report["status"] == "automatic_checks_passed_manual_pending" else 2


if __name__ == "__main__":
    raise SystemExit(main())
