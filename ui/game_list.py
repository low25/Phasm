from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QLabel, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap
from core.config import config
from core.badges import badge_pixmap
from ui.theme import get_theme_colors


class GameList(QListWidget):
    """Compact vertical collection view with game focus and context signals."""
    game_focused = Signal(dict)
    game_selected = Signal(dict)
    context_requested = Signal(dict)
    navigate_up = Signal()
    navigate_down = Signal()

    def __init__(self, games, parent=None):
        super().__init__(parent)
        self.games = list(games)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.refresh_theme()
        for game in self.games:
            title = game.get("title", "Unknown game")
            platform = game.get("platform", "")
            item_widget = QWidget()
            item_widget.setObjectName("collectionResult")
            item_widget.setFixedHeight(62)
            item_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(14, 8, 18, 8)
            item_layout.setSpacing(14)

            platform_icon = QLabel()
            platform_icon.setFixedSize(36, 36)
            platform_icon.setAlignment(Qt.AlignCenter)
            platform_icon.setStyleSheet(self._platform_badge_style(platform))
            pixmap = badge_pixmap(platform, QSize(25, 25))
            if not pixmap.isNull():
                platform_icon.setPixmap(pixmap)
            else:
                platform_icon.setText({"PC": "▣", "PS1": "◈", "PS4": "◈"}.get(str(platform).upper(), "✦"))

            title_label = QLabel(title)
            title_label.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
            title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            title_label.setTextInteractionFlags(Qt.NoTextInteraction)
            item_layout.addWidget(platform_icon)
            item_layout.addWidget(title_label)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, game)
            item.setSizeHint(QSize(0, 66))
            self.addItem(item)
            self.setItemWidget(item, item_widget)
        self.currentRowChanged.connect(self._on_row_changed)
        self.itemActivated.connect(self._on_activated)

    def _on_row_changed(self, row):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        for index in range(self.count()):
            widget = self.itemWidget(self.item(index))
            if widget:
                active = index == row
                widget.setStyleSheet(
                    "QWidget#collectionResult { "
                    f"background: {palette['PANEL'] if active else palette['SURFACE']}; "
                    f"border: 1px solid {palette['ACCENT'] if active else 'transparent'}; "
                    "border-radius: 9px; }"
                )
        if 0 <= row < len(self.games):
            self.game_focused.emit(self.games[row])

    def _on_activated(self, item):
        game = item.data(Qt.ItemDataRole.UserRole)
        if game:
            self.game_selected.emit(game)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            game = item.data(Qt.ItemDataRole.UserRole)
            if game:
                self.setCurrentItem(item)
                self.context_requested.emit(game)
        event.accept()

    def focus_game(self, index=0):
        if self.count():
            index = max(0, min(index, self.count() - 1))
            self.setCurrentRow(index)
            self.setFocus()

    @property
    def focused_index(self):
        return max(0, self.currentRow())

    def focus_card(self, index=0):
        self.focus_game(index)

    def refresh_theme(self):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { background: transparent; border: none; padding: 2px 0; }"
        )

    @staticmethod
    def _platform_badge_style(platform):
        styles = {
            "PS1": "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
            "PS2": "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
            "PS3": "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
            "PS4": "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
            "SWITCH": "background: white; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
            "PC": "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;",
        }
        return styles.get(str(platform).upper(), "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 18px; color: #111827;")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up and self.currentRow() <= 0:
            self.navigate_up.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Down and self.currentRow() >= self.count() - 1:
            self.navigate_down.emit()
            event.accept()
            return
        super().keyPressEvent(event)
