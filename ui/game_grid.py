from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QPoint, QRect, QPropertyAnimation, QEasingCurve


class GameGrid(QWidget):
    game_focused = Signal(dict)
    game_selected = Signal(dict)
    selection_requested = Signal(dict, object)
    game_favorite_toggled = Signal(dict)
    game_play_requested = Signal(dict)
    game_install_requested = Signal(dict)
    context_requested = Signal(dict)
    navigate_up = Signal()
    navigate_down = Signal()
    # Keep card creation incremental so a large HOME library does not freeze
    # while Qt creates and lays out a whole screen of artwork at once.
    BATCH_SIZE = 12
    MIN_CARD_WIDTH = 176
    MAX_CARD_WIDTH = 300

    def __init__(self, title="ALL GAMES", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumWidth(0)
        self.games, self.cards = [], []
        self.loaded_count = self.focused_index = 0
        self._reflowing = False
        self.selection_mode = False
        self.title = title
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(24, 48, 24, 40)
        self.grid.setHorizontalSpacing(16); self.grid.setVerticalSpacing(16)
        self.grid.setAlignment(Qt.AlignTop)
        self.empty = QLabel("NO GAMES")
        self.empty.setStyleSheet("font-size: 16px; color: #64748b; letter-spacing: 2px;")
        self.empty.setAlignment(Qt.AlignCenter)
        self.heading = QLabel(self)
        self.heading.setStyleSheet("font-size: 18px; font-weight: bold; letter-spacing: 2px; color: #e2e8f0;")
        self.heading.setText(f"{title}  •  0 GAMES")
        self.heading.raise_()

    def set_games(self, games):
        self.games = list(games); self.cards.clear(); self.loaded_count = self.focused_index = 0
        self.heading.setText(f"{self.title}  •  {len(self.games)} GAMES")
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget and widget is not self.empty:
                widget.deleteLater()
        if not self.games:
            self.grid.addWidget(self.empty, 0, 0); self.empty.show()
        else:
            self.empty.hide(); self.load_more()

    def _columns(self):
        available = max(1, self.width() - self.grid.contentsMargins().left() - self.grid.contentsMargins().right())
        spacing = max(0, self.grid.horizontalSpacing())
        return max(1, (available + spacing) // (self.MIN_CARD_WIDTH + spacing))

    def _card_width(self, columns):
        available = max(1, self.width() - self.grid.contentsMargins().left() - self.grid.contentsMargins().right())
        spacing = max(0, self.grid.horizontalSpacing())
        width = (available - spacing * (columns - 1)) // columns
        # Use every column's available width when the side hero narrows the
        # viewport, while keeping cards capped at a readable desktop size.
        return max(150, min(self.MAX_CARD_WIDTH, width))

    def load_more(self):
        if self.loaded_count >= len(self.games): return False
        from ui.widgets.game_card import GameCard
        end = min(len(self.games), self.loaded_count + self.BATCH_SIZE)
        for game in self.games[self.loaded_count:end]:
            card = GameCard(game)
            card.card_focused.connect(self._card_focused)
            card.card_clicked.connect(self._card_clicked)
            card.card_clicked_with_modifiers.connect(self.selection_requested.emit)
            card.favorite_toggled.connect(self.game_favorite_toggled.emit)
            card.play_requested.connect(self._card_play_requested)
            card.install_requested.connect(self.game_install_requested.emit)
            card.context_requested.connect(self.context_requested.emit)
            self.cards.append(card)
        self.loaded_count = end; self._reflow(); return True

    def set_selection_mode(self, enabled):
        self.selection_mode = bool(enabled)
        for card in self.cards:
            card.set_selected(False)

    def _card_clicked(self, game):
        self.game_selected.emit(game)

    def _card_play_requested(self, game):
        if self.selection_mode:
            self.game_selected.emit(game)
        else:
            self.game_play_requested.emit(game)

    def _reflow(self):
        if self._reflowing:
            return
        self._reflowing = True
        while self.grid.count():
            item = self.grid.takeAt(0)
            # Removing the layout item is enough; keep the widget parented to
            # the grid so Qt can safely reinsert it during responsive reflow.
        cols = self._columns()
        card_width = self._card_width(cols)
        for i, card in enumerate(self.cards):
            card.set_card_size(card_width)
            self.grid.addWidget(card, i // cols, i % cols)
        self._reflowing = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.heading.setGeometry(24, 8, max(0, self.width() - 48), 30)
        self.heading.raise_()
        if self.cards: self._reflow()

    def focus_card(self, index):
        if not self.cards: return
        self.focused_index = max(0, min(index, len(self.cards) - 1)); self.cards[self.focused_index].setFocus()
        self._ensure_card_visible(self.cards[self.focused_index])
        if self.focused_index >= len(self.cards) - 8: self.load_more()

    def _ensure_card_visible(self, card):
        parent = self.parentWidget()
        while parent:
            if hasattr(parent, "verticalScrollBar") and hasattr(parent, "viewport"):
                viewport = parent.viewport()
                top_left = card.mapTo(viewport, QPoint(0, 0))
                card_rect = QRect(top_left, card.size())
                if viewport.rect().contains(card_rect):
                    return
                bar = parent.verticalScrollBar()
                if card_rect.top() < 0:
                    target = bar.value() + card_rect.top() - 12
                else:
                    target = bar.value() + card_rect.bottom() - viewport.height() + 12
                target = int(max(0, min(target, bar.maximum())))
                animation = QPropertyAnimation(bar, b"value", self)
                animation.setDuration(180)
                animation.setEasingCurve(QEasingCurve.OutQuad)
                animation.setStartValue(int(bar.value()))
                animation.setEndValue(target)
                animation.finished.connect(lambda b=bar, value=target: b.setValue(int(value)))
                self._scroll_animation = animation
                animation.start()
                return
            parent = parent.parentWidget()

    def update_card_cover(self, key, path):
        for card in self.cards:
            if card.game_dict.get("key") == key: card.set_cover(path); break

    def _card_focused(self, game):
        card = self.sender()
        if card in self.cards: self.focused_index = self.cards.index(card)
        self.game_focused.emit(game)
        if self.focused_index >= len(self.cards) - 8: self.load_more()

    def keyPressEvent(self, event):
        key = event.key(); cols = self._columns()
        if key == Qt.Key_Right:
            self.focus_card(self.focused_index + 1)
        elif key == Qt.Key_Left:
            self.focus_card(self.focused_index - 1)
        elif key == Qt.Key_Down:
            target = self.focused_index + cols
            if target >= len(self.cards):
                self.navigate_down.emit()
            else:
                self.focus_card(target)
        elif key == Qt.Key_Up:
            target = self.focused_index - cols
            if target < 0:
                self.navigate_up.emit()
            else:
                self.focus_card(target)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and self.cards: self.game_selected.emit(self.cards[self.focused_index].game_dict)
        else: super().keyPressEvent(event)
