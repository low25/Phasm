from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage


_ACCENT_CACHE = {}


def dominant_accent(path, fallback="#7c3aed"):
    """Return a readable saturated accent sampled from cached artwork."""
    if not path:
        return fallback
    path = str(path)
    cached = _ACCENT_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        image = QImage(path)
        if image.isNull():
            _ACCENT_CACHE[path] = fallback
            return fallback
        image = image.scaled(32, 32, Qt.KeepAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_RGBA8888)
        colors = []
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                saturation = color.saturationF()
                value = color.valueF()
                if saturation < 0.22 or value < 0.16 or value > 0.97:
                    continue
                # Saturated midtones make better focus colors than black,
                # white, or gray background pixels.
                weight = saturation * (1.0 - abs(value - 0.55))
                colors.append((color, weight))
        if not colors:
            _ACCENT_CACHE[path] = fallback
            return fallback
        total = sum(weight for _color, weight in colors)
        red = sum(color.red() * weight for color, weight in colors) / total
        green = sum(color.green() * weight for color, weight in colors) / total
        blue = sum(color.blue() * weight for color, weight in colors) / total
        result = QColor.fromRgb(int(red), int(green), int(blue))
        result = result.lighter(125)
        result = result.name()
        _ACCENT_CACHE[path] = result
        return result
    except Exception:
        _ACCENT_CACHE[path] = fallback
        return fallback
