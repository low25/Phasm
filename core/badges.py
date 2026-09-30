from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap

from core.config import config


BUILTIN_BADGE_LOGOS = {
    "PC": config.project_root / "assets" / "UI" / "pc_badge.svg",
    "PS2": config.project_root / "assets" / "Emus" / "ps2-logo.png",
    "PS3": config.project_root / "assets" / "Emus" / "ps3-logo.png",
    "SWITCH": config.project_root / "assets" / "Emus" / "switch-logo.png",
}

_BADGE_CACHE = {}


def badge_pixmap(platform: str, size: QSize | None = None) -> QPixmap:
    """Load a configured badge logo, falling back to Phasm's built-in logo."""
    platform_key = str(platform or "").upper()
    custom_path = config.settings.get("badge_icons", {}).get(platform_key, "")
    path = Path(custom_path).expanduser() if custom_path else BUILTIN_BADGE_LOGOS.get(platform_key)
    size_key = (platform_key, size.width(), size.height()) if size else (platform_key, 0, 0)
    cached = _BADGE_CACHE.get(size_key)
    if cached is not None:
        return cached
    pixmap = QPixmap(str(path)) if path else QPixmap()

    if pixmap.isNull() and path != BUILTIN_BADGE_LOGOS.get(platform_key):
        fallback = BUILTIN_BADGE_LOGOS.get(platform_key)
        pixmap = QPixmap(str(fallback)) if fallback else QPixmap()

    if size and not pixmap.isNull():
        pixmap = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _BADGE_CACHE[size_key] = pixmap
    return pixmap
