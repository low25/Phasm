import random
import math

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QPixmap, QLinearGradient
from core.config import config
from ui.theme import get_theme_colors


class Starfield(QWidget):
    """Quiet animated space backdrop that stays behind the launcher UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.accent = QColor("#7c3aed")
        self.background_mode = "hero_full"
        self.background_pixmap = None
        self.background_path = None
        self._scaled_background = None
        self._scaled_background_size = None
        self.stars = []
        for _ in range(150):
            self.stars.append({
                "x": random.random(),
                "y": random.random(),
                "depth": random.uniform(0.25, 1.0),
                "twinkle": random.random() * 6.28,
            })
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._advance)
        # Hero Full is static; do not run the old starfield animation.

    def set_background_mode(self, mode):
        self.background_mode = "hero_full"
        if self.timer.isActive():
            self.timer.stop()
        self.update()

    def set_background_image(self, path):
        if path == self.background_path:
            return
        self.background_path = path
        self.background_pixmap = None
        self._scaled_background = None
        self._scaled_background_size = None
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.background_pixmap = pixmap
        self.update()

    def set_accent(self, color):
        self.accent = QColor(color)
        self.update()

    def _advance(self):
        for star in self.stars:
            star["x"] -= 0.0007 * star["depth"]
            star["twinkle"] += 0.045
            if star["x"] < -0.02:
                star["x"] = 1.02
                star["y"] = random.random()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = get_theme_colors()
        painter.fillRect(self.rect(), QColor(theme["BG"]))

        if self.background_mode != "stars" and self.background_pixmap:
            painter.save()
            painter.setOpacity(0.42)
            if self.background_mode == "hero_full":
                size = self.size()
                if self._scaled_background is None or self._scaled_background_size != size:
                    self._scaled_background = self.background_pixmap.scaled(
                        size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
                    self._scaled_background_size = size
                image = self._scaled_background
                painter.drawPixmap((self.width() - image.width()) // 2, (self.height() - image.height()) // 2, image)
            painter.setOpacity(1.0)
            overlay = QLinearGradient(0, 0, 0, self.height())
            overlay.setColorAt(0.0, QColor(5, 5, 12, 120))
            overlay.setColorAt(0.58, QColor(5, 5, 12, 165))
            overlay.setColorAt(1.0, QColor(5, 5, 12, 235))
            painter.fillRect(self.rect(), overlay)
            painter.restore()
            painter.end()
            return

        nebula = QRadialGradient(self.width() * 0.72, self.height() * 0.18, max(self.width(), self.height()) * 0.72)
        configured_accent = get_theme_colors(accent_name=config.settings.get("accent", "Violet"))["ACCENT"]
        nebula_color = QColor(configured_accent)
        nebula_color.setAlpha(52)
        nebula.setColorAt(0.0, nebula_color)
        nebula.setColorAt(0.55, QColor(16, 22, 54, 22))
        nebula.setColorAt(1.0, QColor(7, 8, 18, 0))
        painter.fillRect(self.rect(), nebula)

        for star in self.stars:
            pulse = (1.0 + math.sin(star["twinkle"])) * 0.5
            alpha = int(55 + 150 * star["depth"] * (0.65 + pulse * 0.35))
            radius = 0.6 + star["depth"] * 1.8
            painter.setPen(Qt.NoPen)
            star_color = QColor("#ffffff")
            star_color.setAlpha(alpha)
            painter.setBrush(star_color)
            painter.drawEllipse(QPointF(star["x"] * self.width(), star["y"] * self.height()), radius, radius)
        painter.end()
