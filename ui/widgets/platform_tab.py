from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QRect, QPoint, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics
from core.config import config
from ui.theme import get_theme_colors

class PlatformTab(QWidget):
    tab_changed = Signal(str)
    collections_reordered = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.tabs = ["HOME"]
        self.tab_values = ["HOME"]
        self.current_index = 0
        self.scroll_offset = 0
        
        self.anim_x = 0.0
        self.anim_width = 0.0
        self.anim_timer = None
        self.target_x = 0.0
        self.target_width = 0.0

        self.setMouseTracking(True)
        self.tab_rects = []
        self._drag_index = None
        self._dragging = False
        self._drag_order_changed = False
        self._pressed_index = None

    def set_platforms(self, platforms, collections=None):
        """Refresh navigation with Home and user-created collections only.

        Platforms are filters inside the library views, not collections.  Do
        not expose them as top-level tabs: unlike collections, they are
        generated from scanned games and cannot be manually reordered.
        ``platforms`` remains an argument for callers that refresh the tab
        bar after a scan.
        """
        current_value = self.current_value()
        self.tabs = ["HOME"]
        self.tab_values = ["HOME"]
        for name in (collections or []):
            self.tabs.append(str(name).upper())
            self.tab_values.append(f"collection:{name}")
        next_index = self.tab_values.index(current_value) if current_value in self.tab_values else 0
        selection_changed = next_index != self.current_index or self.current_value() != current_value
        self.current_index = next_index
        self._ensure_current_visible()
        self.update()
        self._snap_underline()
        if selection_changed:
            self.tab_changed.emit(self.tab_values[self.current_index])

    def current_value(self):
        if 0 <= self.current_index < len(self.tab_values):
            return self.tab_values[self.current_index]
        return "HOME"

    def set_current_tab(self, index):
        if 0 <= index < len(self.tabs) and index != self.current_index:
            self.current_index = index
            self._ensure_current_visible()
            self._animate_underline()
            self.tab_changed.emit(self.tab_values[self.current_index])
            self.update()

    def _snap_underline(self):
        self._calculate_rects()
        if self.current_index < len(self.tab_rects):
            r = self.tab_rects[self.current_index]
            self.anim_x = r.x()
            self.anim_width = r.width()
        self.update()

    def _animate_underline(self):
        self._calculate_rects()
        if self.current_index < len(self.tab_rects):
            r = self.tab_rects[self.current_index]
            self.target_x = r.x()
            self.target_width = r.width()
            
            # Simple manual animation timer
            from PySide6.QtCore import QTimer
            if self.anim_timer:
                self.anim_timer.stop()
            self.anim_timer = QTimer(self)
            self.anim_timer.setInterval(16)
            self.anim_timer.timeout.connect(self._anim_step)
            self.anim_timer.start()

    def _anim_step(self):
        dx = (self.target_x - self.anim_x) * 0.2
        dw = (self.target_width - self.anim_width) * 0.2
        self.anim_x += dx
        self.anim_width += dw
        
        if abs(self.target_x - self.anim_x) < 1.0 and abs(self.target_width - self.anim_width) < 1.0:
            self.anim_x = self.target_x
            self.anim_width = self.target_width
            self.anim_timer.stop()
        self.update()

    def _calculate_rects(self):
        self.tab_rects = []
        x = 40 - self.scroll_offset
        font = QFont("Segoe UI", 16, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        fm = QFontMetrics(font)
        
        for t in self.tabs:
            w = fm.horizontalAdvance(t) + 40
            self.tab_rects.append(QRect(x, 0, w, self.height()))
            x += w

    def _content_width(self):
        self._calculate_rects()
        return (self.tab_rects[-1].right() + self.scroll_offset + 40) if self.tab_rects else 0

    def _max_scroll(self):
        return max(0, self._content_width() - self.width())

    def _ensure_current_visible(self):
        self._calculate_rects()
        if not self.tab_rects or not (0 <= self.current_index < len(self.tab_rects)):
            return
        rect = self.tab_rects[self.current_index]
        if rect.right() > self.width() - 20:
            self.scroll_offset += rect.right() - (self.width() - 20)
        elif rect.left() < 20:
            self.scroll_offset -= 20 - rect.left()
        self.scroll_offset = max(0, min(self.scroll_offset, self._max_scroll()))

    def wheelEvent(self, event):
        delta = event.angleDelta().x() or event.angleDelta().y()
        self.scroll_offset = max(0, min(self._max_scroll(), self.scroll_offset - int(delta / 2)))
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_index = None
            self._dragging = False
            self._drag_order_changed = False
            self._pressed_index = None
            for i, r in enumerate(self.tab_rects):
                if r.contains(event.pos()):
                    if self.tab_values[i].startswith("collection:"):
                        self._drag_index = i
                    self._pressed_index = i
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_index is not None and event.buttons() & Qt.LeftButton:
            if abs(event.position().x() - self.tab_rects[self._drag_index].center().x()) > 6:
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self._reorder_under_pointer(event.position().x())
            self.update()
        super().mouseMoveEvent(event)

    def _reorder_under_pointer(self, x):
        """Move the dragged collection as soon as the pointer crosses a tab."""
        self._calculate_rects()
        collection_indices = [
            i for i, value in enumerate(self.tab_values)
            if value.startswith("collection:")
        ]
        if len(collection_indices) < 2:
            return

        source = self._drag_index
        target = min(
            collection_indices,
            key=lambda index: abs(x - self.tab_rects[index].center().x()),
        )
        if target == source:
            return

        moved_value = self.tab_values.pop(source)
        moved_label = self.tabs.pop(source)
        self.tab_values.insert(target, moved_value)
        self.tabs.insert(target, moved_label)
        self._drag_index = target
        self.current_index = target
        self._drag_order_changed = True
        self._ensure_current_visible()
        self._snap_underline()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self._dragging
            if self._drag_index is not None and was_dragging:
                if self._drag_order_changed:
                    self.collections_reordered.emit([
                        value.split(":", 1)[1]
                        for value in self.tab_values
                        if value.startswith("collection:")
                    ])
            self._drag_index = None
            self._dragging = False
            self._drag_order_changed = False
            if self._pressed_index is not None and not was_dragging:
                if 0 <= self._pressed_index < len(self.tab_rects) and self.tab_rects[self._pressed_index].contains(event.pos()):
                    self.set_current_tab(self._pressed_index)
            self._pressed_index = None
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._calculate_rects()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))

        for i, (t, r) in enumerate(zip(self.tabs, self.tab_rects)):
            is_selected = (i == self.current_index)
            
            font = QFont("Segoe UI", 16, QFont.Bold)
            font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
            if is_selected:
                font.setPointSize(18)
                painter.setPen(QColor("#ffffff"))
            else:
                painter.setPen(QColor(palette["TEXT_DIM"]))
                
            painter.setFont(font)
            painter.drawText(r, Qt.AlignCenter, t)

        # Draw underline
        if self.anim_width > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette["ACCENT2"]))
            painter.drawRoundedRect(int(self.anim_x + 10), self.height() - 4, int(self.anim_width - 20), 4, 2, 2)
        painter.end()
