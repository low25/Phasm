from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QPointF, Signal, QPoint
from PySide6.QtGui import QPainter, QPixmap, QColor, QLinearGradient, QPainterPath, QFont
from core import userdata
from datetime import datetime
import math
import random
import time
from core.config import config
from ui.theme import get_theme_colors

class HeroBanner(QWidget):
    width_dragged = Signal(int)
    width_drag_finished = Signal(int)
    _pixmap_cache = {}
    _scaled_pixmap_cache = {}

    @classmethod
    def invalidate_artwork(cls, *paths):
        paths = {str(path) for path in paths if path}
        old_keys = {
            int(cls._pixmap_cache[path].cacheKey())
            for path in paths
            if path in cls._pixmap_cache and cls._pixmap_cache[path] is not None
        }
        for path in paths:
            cls._pixmap_cache.pop(path, None)
        if old_keys:
            cls._scaled_pixmap_cache = {
                key: value for key, value in cls._scaled_pixmap_cache.items()
                if key[0] not in old_keys
            }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.current_hero_path = None
        self.current_cover_path = None
        self.current_title = ""
        self.current_description = ""
        self.current_developer = ""
        self.current_year = ""
        self.current_playtime = ""
        self.current_last_played = ""
        self.current_logo_path = None
        self.platform = ""
        self.orientation = "vertical"
        self._dragging_width = False
        self._drag_start_global_x = 0
        self._drag_start_right_x = 0
        self.setMouseTracking(True)

        self.old_pixmap = None
        self.new_pixmap = None
        self.cover_pixmap = None
        self.logo_pixmap = None

        self.fade_progress = 1.0  # 0.0 to 1.0

        self.fade_timer = QTimer(self)
        self.fade_timer.setInterval(16)
        self.fade_timer.timeout.connect(self._update_fade)

        self.scanline_offset = 0
        self.scanline_timer = QTimer(self)
        self.scanline_timer.setInterval(32)
        self.scanline_timer.timeout.connect(self._update_scanline)
        self.scanline_timer.start()

        self.particles = []
        for _ in range(20):
            self.particles.append({
                "x": random.uniform(0, 2000),
                "y": random.uniform(0, 200),
                "speed": random.uniform(0.5, 2.0),
                "size": random.uniform(2, 5)
            })

    def set_game(self, game_dict, force_artwork=False):
        hero_path = game_dict.get("hero_path")
        cover_path = game_dict.get("cover_path")
        logo_path = game_dict.get("logo_path")
        self.platform = game_dict.get("platform", "")
        self.current_title = game_dict.get("title", "")
        self.current_description = game_dict.get("description", "")
        self.current_developer = game_dict.get("developer", "")
        self.current_year = game_dict.get("year", "")
        total_minutes = userdata.get_playtime(game_dict.get("key", "")) // 60
        self.current_playtime = f"{total_minutes // 60}h {total_minutes % 60}m" if total_minutes >= 60 else f"{total_minutes}m"
        last_played = userdata.get_last_played(game_dict.get("key", ""))
        self.current_last_played = datetime.fromtimestamp(last_played).strftime("%d %b %Y") if last_played else "Never"

        if force_artwork or cover_path != self.current_cover_path:
            self.cover_pixmap = self._cached_pixmap(cover_path)
            self.current_cover_path = cover_path
        
        if force_artwork or hero_path != self.current_hero_path:
            self.old_pixmap = self.new_pixmap
            if hero_path:
                self.new_pixmap = self._cached_pixmap(hero_path)
            else:
                self.new_pixmap = None
                
            self.current_hero_path = hero_path
            self.fade_progress = 0.0
            self.fade_timer.start()

        if force_artwork or logo_path != self.current_logo_path:
            if logo_path:
                self.logo_pixmap = self._cached_pixmap(logo_path)
            else:
                self.logo_pixmap = None
            self.current_logo_path = logo_path
            
        self.update()

    @classmethod
    def _cached_pixmap(cls, path):
        if not path:
            return None
        if path not in cls._pixmap_cache:
            pix = QPixmap(path)
            cls._pixmap_cache[path] = pix if not pix.isNull() else None
        return cls._pixmap_cache[path]

    @classmethod
    def _scaled_pixmap(cls, pixmap, width, height, mode=Qt.KeepAspectRatio):
        if not pixmap:
            return None
        width, height = max(1, int(width)), max(1, int(height))
        key = (int(pixmap.cacheKey()), width, height, mode)
        scaled = cls._scaled_pixmap_cache.get(key)
        if scaled is None:
            scaled = pixmap.scaled(width, height, mode, Qt.SmoothTransformation)
            if len(cls._scaled_pixmap_cache) >= 96:
                cls._scaled_pixmap_cache.pop(next(iter(cls._scaled_pixmap_cache)))
            cls._scaled_pixmap_cache[key] = scaled
        return scaled

    def set_orientation(self, orientation):
        self.orientation = "horizontal" if orientation == "horizontal" else "vertical"
        self.update()

    def mouseMoveEvent(self, event):
        if self.orientation != "vertical":
            self.setCursor(Qt.ArrowCursor)
            return super().mouseMoveEvent(event)
        x = event.position().x()
        if self._dragging_width:
            global_x = self.mapToGlobal(QPoint(int(x), 0)).x()
            width = self._drag_start_right_x - global_x
            width = max(240, min(640, int(width)))
            self.setCursor(Qt.ClosedHandCursor)
            self.width_dragged.emit(width)
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor if x <= 14 else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.orientation == "vertical" and event.button() == Qt.LeftButton and event.position().x() <= 14:
            self._dragging_width = True
            self._drag_start_global_x = self.mapToGlobal(event.position().toPoint()).x()
            self._drag_start_right_x = self.mapToGlobal(QPoint(self.width(), 0)).x()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_width and event.button() == Qt.LeftButton:
            self._dragging_width = False
            self.setCursor(Qt.OpenHandCursor if event.position().x() <= 14 else Qt.ArrowCursor)
            self.width_drag_finished.emit(self.width())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_fade(self):
        self.fade_progress += 0.05
        if self.fade_progress >= 1.0:
            self.fade_progress = 1.0
            self.fade_timer.stop()
            self.old_pixmap = None
        self.update()

    def _update_scanline(self):
        self.scanline_offset = (self.scanline_offset + 1) % 4
        
        # update particles
        for p in self.particles:
            p["x"] -= p["speed"]
            if p["x"] < -10:
                p["x"] = self.width() + 10
                p["y"] = random.uniform(0, self.height())
        
        self.update()

    def _draw_pixmap_scaled(self, painter, pixmap, opacity):
        if not pixmap: return
        painter.setOpacity(opacity)
        # Keep aspect ratio by expanding, crop center
        scaled = self._scaled_pixmap(
            pixmap, self.width(), self.height(), Qt.KeepAspectRatioByExpanding
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # The foreground cover is rotated after it is scaled. Without this
        # hint Qt uses a fast pixel transform for that final draw, which makes
        # high-resolution cover art look noticeably softer than the source.
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        # Rotated art and labels must never paint outside the responsive panel.
        painter.setClipRect(self.rect())

        # Fallback background
        if not self.new_pixmap or self.fade_progress < 1.0:
            if self.platform == "PS2": bg_color = QColor("#003087")
            elif self.platform == "PS3": bg_color = QColor("#00439C")
            elif self.platform == "PS4": bg_color = QColor("#003791")
            elif self.platform == "Switch": bg_color = QColor("#E60012")
            else: bg_color = QColor("#222222")

            painter.fillRect(self.rect(), bg_color.darker(200))
            
            # Particles
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 40))
            for p in self.particles:
                painter.drawEllipse(QPointF(p["x"], p["y"]), p["size"]/2, p["size"]/2)

        # Draw the fetched hero as a subdued atmospheric background. Landscape
        # hero art stays readable without being forced into a tall crop.
        if self.old_pixmap and self.fade_progress < 1.0:
            self._draw_pixmap_scaled(painter, self.old_pixmap, 0.22 * (1.0 - self.fade_progress))
            
        if self.new_pixmap:
            opacity = 0.72 + 0.18 * self.fade_progress if self.orientation == "horizontal" else 0.24 + 0.16 * self.fade_progress
            self._draw_pixmap_scaled(painter, self.new_pixmap, opacity)

        # Vertical heroes place the game logo above the cover. Horizontal
        # heroes intentionally use the logo as the primary foreground instead.
        vertical_logo_height = 0
        vertical_logo = None
        vertical_logo_top = 15
        if self.orientation == "vertical" and self.logo_pixmap:
            vertical_logo = self._scaled_pixmap(
                self.logo_pixmap, max(160, self.width() - 24), 108, Qt.KeepAspectRatio
            )
            vertical_logo_height = vertical_logo.height() + 20
            vertical_logo_top = 15

        # Cover art is naturally portrait shaped, so it becomes the crisp
        # centerpiece of the vertical hero. A tiny rotation makes it bridge
        # into the card rail instead of looking like another rigid rectangle.
        foreground = None if self.orientation == "horizontal" else (self.cover_pixmap or self.new_pixmap)
        if foreground:
            cover_top_limit = vertical_logo_top + vertical_logo_height if vertical_logo else 18
            cover_bottom = max(cover_top_limit + 120, self.height() - 132)
            card = self._scaled_pixmap(
                foreground,
                max(160, self.width() - 42),
                max(120, cover_bottom - cover_top_limit),
                Qt.KeepAspectRatio,
            )
            # Keep the cover visually centered as the draggable hero changes
            # width. Its top may rise only as far as the logo clearance; once
            # it reaches that boundary, additional growth extends downward.
            center_y = (cover_top_limit + cover_bottom) * 0.5
            draw_top = max(cover_top_limit, int(center_y - card.height() * 0.5))
            # A slow sinusoidal swing naturally eases at both ends of the
            # left-to-right motion, keeping the artwork calm rather than busy.
            tilt = 1.6 * math.sin((time.monotonic() / 16.0) * math.tau)
            painter.save()
            painter.translate(self.width() * 0.50, draw_top + card.height() * 0.50)
            painter.rotate(tilt)
            painter.setOpacity(0.96)
            painter.drawPixmap(-card.width() // 2, -card.height() // 2, card)
            painter.restore()
            
        painter.setOpacity(1.0)

        # Overlay gradient at bottom
        # Horizontal banners need a longer fade so the title area blends into
        # the dark content bar below instead of forming a hard black strip.
        fade_start = int(self.height() * (0.34 if self.orientation == "horizontal" else 0.52))
        grad = QLinearGradient(0, fade_start, 0, self.height())
        grad.setColorAt(0.0, QColor(10, 10, 15, 0))
        grad.setColorAt(0.55, QColor(10, 10, 15, 145 if self.orientation == "horizontal" else 125))
        grad.setColorAt(1.0, QColor(10, 10, 15, 255))
        painter.fillRect(self.rect(), grad)

        # Paint the vertical logo after the cover and gradient so it is always
        # the topmost foreground element and can never be hidden by the cover.
        if self.orientation == "vertical" and vertical_logo:
            painter.setOpacity(0.98)
            painter.drawPixmap(
                (self.width() - vertical_logo.width()) // 2,
                vertical_logo_top,
                vertical_logo,
            )
            painter.setOpacity(1.0)

        # The cover art is tilted; keep the textual metadata level and clean.
        if self.orientation == "horizontal" and self.logo_pixmap:
            logo = self._scaled_pixmap(
                self.logo_pixmap,
                min(self.width() // 2, 420),
                max(80, self.height() - 72),
                Qt.KeepAspectRatio,
            )
            painter.setOpacity(0.98)
            painter.drawPixmap((self.width() - logo.width()) // 2, (self.height() - logo.height()) // 2 - 8, logo)
            painter.setOpacity(1.0)

        if self.current_title:
            palette = get_theme_colors(accent_name=config.settings.get("accent"))
            title_font = QFont("Segoe UI", 13, QFont.Bold)
            title_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
            text_left = 14
            text_width = self.width() - 28
            text_top = self.height() - 112
            painter.setOpacity(0.96)
            painter.setFont(title_font)
            painter.setPen(QColor(255, 255, 255, 235))
            painter.drawText(QRect(text_left, text_top, text_width, 26),
                             Qt.AlignLeft | Qt.AlignVCenter, self.current_title.upper())
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            metadata_color = QColor(palette["ACCENT2"])
            metadata_color.setAlpha(225)
            painter.setPen(metadata_color)
            metadata = f"{self.current_year or 'YEAR UNKNOWN'}  •  {self.current_developer or 'DEVELOPER UNKNOWN'}  •  PLAYTIME {self.current_playtime}  •  LAST PLAYED {self.current_last_played}"
            painter.drawText(QRect(text_left, text_top + 30, text_width, 22),
                             Qt.AlignLeft | Qt.AlignVCenter, metadata)
        painter.end()
