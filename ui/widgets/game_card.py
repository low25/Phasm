from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QVariantAnimation, QRect, QEasingCurve, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QRadialGradient, QFont, QPainterPath, QPen
import time
import math

from core import userdata
from core.library import game_is_installed
from core.config import config
from ui.theme import get_theme_colors
from core.artwork_color import dominant_accent

# Per-platform badge config: (label, gradient_start, gradient_end, text_color)
PLATFORM_BADGE_CFG = {
    "PC": ("PC", "#ffffff", "#ffffff", "#17456b"),
    "PS2": ("PS2", "#001a5e", "#0050d0", "#dbeafe"),
    "PS3": ("PS3", "#001060", "#003fc7", "#dbeafe"),
    "PS4": ("PS4", "#00185a", "#0044bb", "#dbeafe"),
    "Switch": ("SWITCH", "#6b0000", "#cc0010", "#000000"),
}
PLATFORM_BADGE_ICONS = {
    "PC": "▣",
    "PS2": "◈", "PS3": "◈", "PS4": "◈", "Switch": "◇"
}
PLATFORM_BADGE_LOGOS = {
    "PC": QPixmap(str(config.project_root / "assets" / "UI" / "pc_badge.svg")),
    "PS2": QPixmap(str(config.project_root / "assets" / "Emus" / "ps2-logo.png")),
    "PS3": QPixmap(str(config.project_root / "assets" / "Emus" / "ps3-logo.png")),
    "Switch": QPixmap(str(config.project_root / "assets" / "Emus" / "switch-logo.png")),
}

# Fallback solid color for unknown platforms
PLATFORM_COLORS = {
    "PC": "#1b75bb",
    "PS2": "#003087",
    "PS3": "#003791",
    "PS4": "#00439C",
    "Switch": "#E60012",
}


class InnerCard(QWidget):
    """Inner paintable surface so shadow/geometry animation works correctly."""
    def __init__(self, parent):
        super().__init__(parent)
        self.game_card = parent
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.game_card.draw_inner(painter, self.rect())
        painter.end()

    def mouseMoveEvent(self, event):
        width, height = self.width(), self.height()
        self.game_card.set_glint_position(event.position())
        heart = QRect(width - 48, 8, 40, 34)
        play = QRect(width - 54, height - 54, 44, 44)
        self.game_card.set_favorite_hovered(heart.contains(event.position().toPoint()))
        self.game_card.set_action_hovered(play.contains(event.position().toPoint()))
        cursor = Qt.PointingHandCursor if heart.contains(event.position().toPoint()) or play.contains(event.position().toPoint()) else Qt.ArrowCursor
        self.setCursor(cursor)
        self.game_card.setCursor(cursor)
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        self.game_card.set_hovered(True)
        if not self.game_card.hasFocus():
            self.game_card.setFocus()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.game_card.set_hovered(False)
        self.game_card.set_favorite_hovered(False)
        self.game_card.set_action_hovered(False)
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        self.game_card.setFocus()
        self.game_card.context_requested.emit(self.game_card.game_dict)
        event.accept()

class GameCard(QWidget):
    card_clicked = Signal(dict)
    card_clicked_with_modifiers = Signal(dict, object)
    card_focused = Signal(dict)
    favorite_toggled = Signal(dict)
    play_requested = Signal(dict)
    install_requested = Signal(dict)
    context_requested = Signal(dict)

    # Container size — must be bigger than both _NORMAL and _FOCUSED
    # so the scale-up animation has room without clipping
    _W, _H = 260, 380

    # Inner card rects within the container
    _NORMAL  = QRect(30, 40, 200, 300)   # centered, dim when unfocused
    _FOCUSED = QRect(14, 14, 232, 352)   # expands with shadow breathing room
    _cover_cache = {}
    _scaled_cover_cache = {}

    def __init__(self, game_dict, parent=None):
        super().__init__(parent)
        self.game_dict = game_dict
        self.setFixedSize(self._W, self._H)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self.is_focused = False
        self.is_hovered = False
        self.is_selected = False
        self._action_hovered = False
        self._action_icon_color = QColor("#ffffff")
        self._favorite_hovered = False
        self._favorite_icon_color = QColor("#cbd5e1")
        self._pressed_action = None
        self._normal_rect = self._NORMAL
        self._focused_rect = self._FOCUSED
        self.cover_pixmap = None
        self._load_cover(game_dict.get("cover_path"))
        self._installed = None
        self._playtime_seconds = userdata.get_playtime(game_dict.get("key", ""))
        self.accent_color = dominant_accent(
            game_dict.get("cover_path") or game_dict.get("hero_path")
        )

        self.inner = InnerCard(self)
        self.inner.setGeometry(self._NORMAL)

        self.anim = QPropertyAnimation(self.inner, b"geometry")
        self.anim.setDuration(70)
        self.anim.setEasingCurve(QEasingCurve.OutQuad)

        self._action_color_animation = QVariantAnimation(self)
        self._action_color_animation.setDuration(140)
        self._action_color_animation.setStartValue(self._action_icon_color)
        self._action_color_animation.setEndValue(QColor("#4ade80"))
        self._action_color_animation.valueChanged.connect(self._set_action_icon_color)
        self._favorite_color_animation = QVariantAnimation(self)
        self._favorite_color_animation.setDuration(120)
        self._favorite_color_animation.setStartValue(self._favorite_icon_color)
        self._favorite_color_animation.setEndValue(QColor("#a855f7"))
        self._favorite_color_animation.valueChanged.connect(self._set_favorite_icon_color)

        # The highlight is driven by the pointer, not by a clock.
        self.glint_position = QPointF(-1, -1)

    def set_card_size(self, width):
        """Resize the card while preserving its portrait proportions."""
        width = max(150, int(width))
        height = int(round(width * self._H / self._W))
        scale_x = width / self._W
        scale_y = height / self._H
        normal = QRect(
            round(self._NORMAL.x() * scale_x),
            round(self._NORMAL.y() * scale_y),
            round(self._NORMAL.width() * scale_x),
            round(self._NORMAL.height() * scale_y),
        )
        focused = QRect(
            round(self._FOCUSED.x() * scale_x),
            round(self._FOCUSED.y() * scale_y),
            round(self._FOCUSED.width() * scale_x),
            round(self._FOCUSED.height() * scale_y),
        )
        self._normal_rect = normal
        self._focused_rect = focused
        self.setFixedSize(width, height)
        self.inner.setGeometry(focused if self.is_focused else normal)

    def set_cover(self, cover_path):
        if cover_path:
            # A custom artwork selection can overwrite the same cache path;
            # discard the old decoded pixmap before loading it again.
            self._cover_cache.pop(cover_path, None)
            self._scaled_cover_cache = {
                key: pix for key, pix in self._scaled_cover_cache.items()
                if key[0] != cover_path
            }
        self._load_cover(cover_path)
        self.game_dict["cover_path"] = cover_path
        self.accent_color = dominant_accent(cover_path or self.game_dict.get("hero_path"))
        self.inner.update()
        
    def set_playing(self, playing: bool):
        self.game_dict['is_playing'] = playing
        self.inner.update()

    def refresh_cached_state(self):
        self._installed = None
        self._playtime_seconds = userdata.get_playtime(self.game_dict.get("key", ""))

    def _load_cover(self, path):
        if path:
            pix = self._cover_cache.get(path)
            if pix is None:
                pix = QPixmap(path)
                if not pix.isNull():
                    self._cover_cache[path] = pix
            self.cover_pixmap = pix if not pix.isNull() else None
        else:
            self.cover_pixmap = None

    def paintEvent(self, event):
        pass

    def enterEvent(self, event):
        # Hover selects the card and updates the hero immediately.
        self.set_hovered(True)
        if not self.hasFocus():
            self.setFocus()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_hovered(False)
        super().leaveEvent(event)

    def set_hovered(self, hovered):
        self.is_hovered = hovered
        if not hovered:
            self.glint_position = QPointF(-1, -1)
        self.inner.update()

    def set_selected(self, selected):
        self.is_selected = bool(selected)
        self.inner.update()

    def set_glint_position(self, position):
        self.glint_position = QPointF(position)
        self.inner.update()

    def _set_action_icon_color(self, color):
        self._action_icon_color = QColor(color)
        self.inner.update()

    def set_action_hovered(self, hovered):
        hovered = bool(hovered)
        if hovered == self._action_hovered:
            return
        self._action_hovered = hovered
        start = self._action_icon_color
        end = QColor("#4ade80") if hovered else QColor("#ffffff")
        self._action_color_animation.stop()
        self._action_color_animation.setStartValue(start)
        self._action_color_animation.setEndValue(end)
        self._action_color_animation.start()

    def _set_favorite_icon_color(self, color):
        self._favorite_icon_color = QColor(color)
        self.inner.update()

    def set_favorite_hovered(self, hovered):
        hovered = bool(hovered)
        if hovered == self._favorite_hovered:
            return
        self._favorite_hovered = hovered
        accent = get_theme_colors(accent_name=config.settings.get("accent"))["ACCENT"]
        start = self._favorite_icon_color
        end = QColor(accent) if hovered or self.game_dict.get("is_favorite") else QColor("#cbd5e1")
        self._favorite_color_animation.stop()
        self._favorite_color_animation.setStartValue(start)
        self._favorite_color_animation.setEndValue(end)
        self._favorite_color_animation.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            local = event.position().toPoint() - self.inner.pos()
            heart_rect = QRect(self.inner.width() - 48, 8, 40, 34)
            if self.inner.rect().contains(local) and heart_rect.contains(local):
                self._pressed_action = "favorite"
                return
            play_rect = QRect(self.inner.width() - 54, self.inner.height() - 54, 44, 44)
            if self.inner.rect().contains(local) and play_rect.contains(local):
                if self.game_dict.get("platform") == "PC" and self._installed is None:
                    self._installed = game_is_installed(self.game_dict)
                self._pressed_action = "install" if (
                    self.game_dict.get("platform") == "PC" and not self._installed
                ) else "play"
                return
            self._pressed_action = "card"
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            local = event.position().toPoint() - self.inner.pos()
            heart_rect = QRect(self.inner.width() - 48, 8, 40, 34)
            play_rect = QRect(self.inner.width() - 54, self.inner.height() - 54, 44, 44)
            action = self._pressed_action
            self._pressed_action = None
            if action == "favorite" and heart_rect.contains(local):
                key = self.game_dict.get("key", "")
                userdata.toggle_favorite(key)
                self.game_dict["is_favorite"] = userdata.is_favorite(key)
                self.set_favorite_hovered(self._favorite_hovered)
                self.favorite_toggled.emit(self.game_dict)
                self.inner.update()
            elif action == "install" and play_rect.contains(local):
                self.install_requested.emit(self.game_dict)
            elif action == "play" and play_rect.contains(local):
                self.play_requested.emit(self.game_dict)
            elif action == "card" and self.inner.rect().contains(local):
                self.card_clicked_with_modifiers.emit(self.game_dict, event.modifiers())
                self.card_clicked.emit(self.game_dict)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        self.set_glint_position(event.position())
        local = event.position().toPoint() - self.inner.pos()
        button_areas = (
            QRect(self.inner.width() - 48, 8, 40, 34),
            QRect(self.inner.width() - 54, self.inner.height() - 54, 44, 44),
        )
        self.setCursor(Qt.PointingHandCursor if any(area.contains(local) for area in button_areas) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def focusInEvent(self, event):
        self.is_focused = True
        self.anim.stop()
        self.anim.setStartValue(self.inner.geometry())
        self.anim.setEndValue(self._focused_rect)
        self.anim.start()
        self.card_focused.emit(self.game_dict)
        self.inner.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.is_focused = False
        self.anim.stop()
        self.anim.setStartValue(self.inner.geometry())
        self.anim.setEndValue(self._normal_rect)
        self.anim.start()
        self.inner.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Menu:
            self.context_requested.emit(self.game_dict)
            event.accept()
        else:
            event.ignore()

    def contextMenuEvent(self, event):
        self.setFocus()
        self.context_requested.emit(self.game_dict)
        event.accept()

    def draw_inner(self, painter, rect):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        path = QPainterPath()
        path.addRoundedRect(0, 0, rect.width(), rect.height(), 10, 10)
        painter.setClipPath(path)

        platform = self.game_dict.get("platform", "")
        p_color = QColor(PLATFORM_COLORS.get(platform, "#1e1e2e"))
        badge_label, badge_start, badge_end, badge_text_color = PLATFORM_BADGE_CFG.get(
            platform, (platform.upper() or "GAME", "#27223d", "#514078", "#eee8ff")
        )
        badge_icon = PLATFORM_BADGE_ICONS.get(platform, "✦")

        if self.cover_pixmap:
            cover_key = (self.game_dict.get("cover_path", ""), rect.width(), rect.height())
            scaled = self._scaled_cover_cache.get(cover_key)
            if scaled is None:
                scaled = self.cover_pixmap.scaled(
                    rect.width(), rect.height(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                self._scaled_cover_cache[cover_key] = scaled
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            opacity = 1.0 if self.is_focused or self.is_hovered else 0.78
            if platform == "PC" and self._installed is None:
                self._installed = game_is_installed(self.game_dict)
            if platform == "PC" and not self._installed:
                opacity *= 0.42
            painter.setOpacity(opacity)
            painter.drawPixmap(x, y, scaled)
            painter.setOpacity(1.0)
            if platform == "PC" and self._installed is None:
                self._installed = game_is_installed(self.game_dict)
            if platform == "PC" and not self._installed:
                painter.fillPath(path, QColor(80, 80, 90, 105))
        else:
            grad = QLinearGradient(0, 0, 0, rect.height())
            grad.setColorAt(0, p_color.darker(130))
            grad.setColorAt(0.5, p_color.darker(200))
            grad.setColorAt(1, QColor("#0a0a0f"))
            painter.fillPath(path, grad)

            if platform == "PC" and not game_is_installed(self.game_dict):
                painter.fillPath(path, QColor(80, 80, 90, 130))

            painter.setPen(QColor(255, 255, 255, 12))
            ghost_font = QFont("Courier New", 60, QFont.Bold)
            painter.setFont(ghost_font)
            painter.drawText(rect, Qt.AlignCenter, "👻")

        overlay = QLinearGradient(0, rect.height() * 0.55, 0, rect.height())
        overlay.setColorAt(0, QColor(0, 0, 0, 0))
        overlay.setColorAt(1, QColor(0, 0, 0, 230))
        painter.fillRect(0, 0, rect.width(), rect.height(), overlay)

        painter.setClipping(False)
        badge_font = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(badge_font)
        badge_logo = PLATFORM_BADGE_LOGOS.get(platform)
        badge = QRect(10, 10, 34, 34)
        badge_grad = QLinearGradient(badge.topLeft(), badge.bottomRight())
        if platform == "PC":
            badge_grad.setColorAt(0.00, QColor(badge_start))
            badge_grad.setColorAt(1.00, QColor(badge_start))
        elif platform == "Switch":
            badge_grad.setColorAt(0.00, QColor("#ffffff"))
            badge_grad.setColorAt(1.00, QColor("#ffffff"))
        else:
            badge_grad.setColorAt(0, QColor(badge_start))
            badge_grad.setColorAt(1, QColor(badge_end))
        painter.setBrush(badge_grad)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        painter.drawEllipse(badge)
        painter.setPen(QColor(badge_text_color))
        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        if badge_logo and not badge_logo.isNull():
            logo = badge_logo.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(badge.x() + (badge.width() - logo.width()) // 2,
                               badge.y() + (badge.height() - logo.height()) // 2, logo)
        else:
            painter.drawText(badge, Qt.AlignCenter, badge_icon)
        
        if self.game_dict.get('is_playing'):
            playing_badge = QRect(rect.width() - 80, 10, 24, 24)
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
            painter.drawEllipse(playing_badge)
            
            t = time.monotonic()
            pulse = (math.sin(t * 5) + 1) / 2
            dot_color = QColor(34, 197, 94, int(170 + 85 * pulse))
            painter.setBrush(dot_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(playing_badge.adjusted(7, 7, -7, -7))

        # Favorite toggle lives on the card itself and remains visible while
        # browsing, without competing with the platform badge.
        heart_rect = QRect(rect.width() - 48, 10, 38, 28)
        painter.setBrush(QColor(10, 10, 15, 180))
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.drawRoundedRect(heart_rect, 14, 14)
        painter.setFont(QFont("Segoe UI Symbol", 15, QFont.Bold))
        # The theme is stable while a card is painting; avoid rebuilding the
        # palette for every repaint during focus animation.
        favorite_color = getattr(self, "_favorite_accent", None)
        if favorite_color is None:
            favorite_color = get_theme_colors(
                accent_name=config.settings.get("accent", "Violet")
            )["ACCENT"]
            self._favorite_accent = favorite_color
        if self.game_dict.get("is_favorite") and self._favorite_icon_color != QColor(favorite_color):
            self._favorite_icon_color = QColor(favorite_color)
        painter.setPen(self._favorite_icon_color)
        painter.drawText(heart_rect, Qt.AlignCenter, "♥" if self.game_dict.get("is_favorite") else "♡")

        if self.is_focused or self.is_hovered:
            painter.setClipPath(path)
            pen_color = QColor(self.accent_color)
            pen_color.setAlpha(200 if self.is_focused else 140)
            painter.setPen(QPen(pen_color, 3 if self.is_focused else 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(1, 1, rect.width() - 2, rect.height() - 2, 10, 10)
            painter.setClipping(False)

        if self.is_hovered and self.glint_position.x() >= 0:
            w, h = rect.width(), rect.height()
            radius = max(w, h) * 0.72
            glint_grad = QRadialGradient(self.glint_position, radius)
            glint_grad.setColorAt(0.0, QColor(255, 255, 255, 92))
            glint_grad.setColorAt(0.18, QColor(255, 255, 255, 38))
            glint_grad.setColorAt(0.58, QColor(255, 255, 255, 10))
            glint_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setClipPath(path)
            painter.fillRect(0, 0, w, h, glint_grad)
            painter.setClipping(False)
            
        game_key = self.game_dict.get("key", "")
        pt_seconds = self._playtime_seconds
        
        y_offset = rect.height() - 12
        if pt_seconds > 0:
            minutes = pt_seconds // 60
            if minutes < 1:
                pt_str = "▶ <1m"
            elif minutes < 60:
                pt_str = f"▶ {minutes}m"
            else:
                h = minutes // 60
                m = minutes % 60
                if m == 0:
                    pt_str = f"▶ {h}h"
                else:
                    pt_str = f"▶ {h}h {m}m"
                    
            pt_font = QFont("Segoe UI", 9, QFont.Bold)
            painter.setFont(pt_font)
            painter.setPen(QColor(self.accent_color).lighter(135))
            painter.drawText(10, y_offset, pt_str)
            y_offset -= 16
            
        title = self.game_dict.get("title", "")
        title_font = QFont("Segoe UI", 11, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        fm = painter.fontMetrics()
        elided = fm.elidedText(title, Qt.ElideRight, rect.width() - 20)
        painter.drawText(10, y_offset, elided)

        # Paint last so the launch control stays above the title text.
        play_rect = QRect(rect.width() - 54, rect.height() - 54, 44, 44)
        if platform == "PC" and self._installed is None:
            self._installed = game_is_installed(self.game_dict)
        unavailable = platform == "PC" and not self._installed
        painter.setBrush(QColor("#52525b") if unavailable else QColor(self.accent_color))
        painter.setPen(QPen(QColor("#71717a") if unavailable else QColor(self.accent_color).lighter(145), 1))
        painter.drawEllipse(play_rect)
        painter.setPen(QColor("#a1a1aa") if unavailable else QColor("#ffffff"))
        painter.setBrush(QColor("#a1a1aa") if unavailable else QColor("#ffffff"))
        if unavailable:
            painter.setPen(QPen(self._action_icon_color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center_x = play_rect.center().x() + 2
            painter.drawLine(center_x, play_rect.y() + 12, center_x, play_rect.y() + 26)
            painter.drawLine(center_x - 5, play_rect.y() + 21, center_x, play_rect.y() + 26)
            painter.drawLine(center_x + 5, play_rect.y() + 21, center_x, play_rect.y() + 26)
            painter.drawLine(play_rect.x() + 14, play_rect.bottom() - 9, play_rect.right() - 10, play_rect.bottom() - 9)
        else:
            painter.setPen(self._action_icon_color)
            painter.setBrush(self._action_icon_color)
            triangle = QPainterPath()
            triangle.moveTo(play_rect.x() + 19, play_rect.y() + 16)
            triangle.lineTo(play_rect.x() + 19, play_rect.y() + 28)
            triangle.lineTo(play_rect.x() + 28, play_rect.y() + 22)
            triangle.closeSubpath()
            painter.drawPath(triangle)

        if self.is_selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#c084fc"), 4))
            painter.drawRoundedRect(2, 2, rect.width() - 4, rect.height() - 4, 10, 10)
