import sys
import argparse
import os
import subprocess
from pathlib import Path

def main():
    # Prefer the discrete NVIDIA GPU for Phasm when PRIME/offload is
    # available. These are process-local, so launching the app does not alter
    # the user's system-wide GPU policy. Keep explicit caller values intact.
    nvidia_env = {
        "__NV_PRIME_RENDER_OFFLOAD": "1",
        "__NV_PRIME_RENDER_OFFLOAD_PROVIDER": "NVIDIA-G0",
        "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
        "__VK_LAYER_NV_optimus": "NVIDIA_only",
        "DRI_PRIME": "1",
    }
    for name, value in nvidia_env.items():
        os.environ.setdefault(name, value)

    parser = argparse.ArgumentParser(description="Phasm")
    parser.add_argument("--check", action="store_true", help="Check initialization and exit")
    parser.add_argument("--buildapp", action="store_true", help="Build the Phasm AppImage and exit")
    args, unknown = parser.parse_known_args()

    if args.buildapp:
        project_root = Path(__file__).resolve().parent
        build_script = project_root / "packaging" / "build-appimage.sh"
        if not build_script.exists():
            parser.error(f"AppImage build script not found: {build_script}")
        raise SystemExit(subprocess.run(["bash", str(build_script)], cwd=project_root).returncode)

    if args.check:
        print("[INIT] Running check mode")
        # Just import and load configs
        from core.config import config
        print("[INIT] Config loaded successfully")
        sys.exit(0)

    # Set attributes before creating QApplication
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"
    
    from PySide6.QtWidgets import QApplication, QStyleFactory
    from PySide6.QtCore import Qt
    
    # Qt6: HiDPI is enabled by default — no setAttribute needed
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    fusion_style = QStyleFactory.create("Fusion")
    if fusion_style:
        app.setStyle(fusion_style)

    from PySide6.QtGui import QFontDatabase, QFont, QIcon, QPalette, QColor

    # Keep Qt controls independent from desktop/Matugen palette colors.
    fixed_palette = QPalette()
    fixed_palette.setColor(QPalette.Window, QColor("#0a0a0f"))
    fixed_palette.setColor(QPalette.WindowText, QColor("#e2e8f0"))
    fixed_palette.setColor(QPalette.Base, QColor("#12121a"))
    fixed_palette.setColor(QPalette.AlternateBase, QColor("#0e0d17"))
    fixed_palette.setColor(QPalette.Text, QColor("#e2e8f0"))
    fixed_palette.setColor(QPalette.Button, QColor("#12121a"))
    fixed_palette.setColor(QPalette.ButtonText, QColor("#e2e8f0"))
    fixed_palette.setColor(QPalette.ToolTipBase, QColor("#12121a"))
    fixed_palette.setColor(QPalette.ToolTipText, QColor("#e2e8f0"))
    fixed_palette.setColor(QPalette.Highlight, QColor("#7c3aed"))
    fixed_palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    fixed_palette.setColor(QPalette.Link, QColor("#c084fc"))
    fixed_palette.setColor(QPalette.PlaceholderText, QColor("#64748b"))
    fixed_palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#64748b"))
    fixed_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#64748b"))
    app.setPalette(fixed_palette)
    
    app.setApplicationName("Phasm")
    app.setApplicationDisplayName("Phasm")
    app.setOrganizationName("Phasm")
    # Match the embedded desktop entry so Wayland/X11 and the dock treat the
    # running window as the pinned Phasm application, not python3.
    app.setDesktopFileName("Phasm")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "icon.svg")))
    font = QFont("Segoe UI", 12)
    app.setFont(font)

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
