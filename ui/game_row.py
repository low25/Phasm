import shiboken6
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer, QPoint, QRect
from core.config import config
from ui.theme import get_theme_colors


class _PassthroughScrollArea(QScrollArea):
    """QScrollArea that does NOT consume arrow/nav key events.
    
    The default QScrollArea.keyPressEvent scrolls on arrow keys, which
    prevents those events from reaching GameRow. We override it to simply
    ignore all key events, letting Qt propagate them up to GameRow.
    """
    def keyPressEvent(self, event):
        event.ignore()   # do not accept — Qt propagates to parent (GameRow)


class GameRow(QWidget):
    game_focused = Signal(dict)
    game_selected = Signal(dict)
    game_favorite_toggled = Signal(dict)
    game_play_requested = Signal(dict)
    game_install_requested = Signal(dict)
    context_requested = Signal(dict)
    navigate_up = Signal()
    navigate_down = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setFixedHeight(430)   # title(~30) + spacing(10) + card(360) + margins(20) + slack
        self.setFocusPolicy(Qt.StrongFocus)
        self.focused_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 10, 40, 10)
        layout.setSpacing(10)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #e2e8f0; letter-spacing: 2px;"
        )
        layout.addWidget(self.title_label)

        self.scroll_area = _PassthroughScrollArea()
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.refresh_theme()

        self.container = QWidget()
        self.container.setFocusPolicy(Qt.NoFocus)
        self.container.setStyleSheet("background: transparent;")
        self.h_layout = QHBoxLayout(self.container)
        self.h_layout.setContentsMargins(0, 0, 0, 0)   # no vertical padding — prevents card overflow
        self.h_layout.setSpacing(16)
        self.h_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)

        self.empty_label = QLabel("NO GAMES")
        self.empty_label.setStyleSheet(
            "font-size: 16px; color: #64748b; letter-spacing: 2px;"
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.cards = []
        self.scroll_anim = QPropertyAnimation(
            self.scroll_area.horizontalScrollBar(), b"value"
        )
        self.scroll_anim.setDuration(180)
        self.scroll_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._scroll_target = 0
        self.scroll_anim.finished.connect(self._finish_scroll)

    def refresh_theme(self):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:horizontal {{ background: {palette['BG']}; height: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:horizontal {{ background: {palette['ACCENT']}; border-radius: 3px; min-width: 30px; }}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
        )

    # ── Public ────────────────────────────────────────────────────────────

    def set_games(self, games_list):
        while self.h_layout.count():
            item = self.h_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards.clear()
        self.focused_index = 0

        if not games_list:
            self.empty_label.show()
            return

        self.empty_label.hide()
        for g in games_list:
            from ui.widgets.game_card import GameCard
            card = GameCard(g)
            card.card_focused.connect(self._on_card_focused)
            card.card_clicked.connect(self._on_card_clicked)
            card.favorite_toggled.connect(self.game_favorite_toggled.emit)
            card.play_requested.connect(self.game_play_requested.emit)
            card.install_requested.connect(self.game_install_requested.emit)
            card.context_requested.connect(self.context_requested.emit)
            self.h_layout.addWidget(card)
            self.cards.append(card)

    def focus_card(self, index):
        if not self.cards:
            return
        index = max(0, min(index, len(self.cards) - 1))
        self.focused_index = index
        self.cards[index].setFocus()
        self._scroll_to(index)

    def update_card_cover(self, game_key, cover_path):
        for card in self.cards:
            if card.game_dict.get("key") == game_key:
                card.set_cover(cover_path)
                break

    # ── Internals ─────────────────────────────────────────────────────────

    def _on_card_focused(self, game_dict):
        self.game_focused.emit(game_dict)
        sender_card = self.sender()
        if sender_card and sender_card in self.cards:
            self.focused_index = self.cards.index(sender_card)
        self._scroll_to(self.focused_index)

    def _scroll_to(self, index):
        if not self.cards or index >= len(self.cards):
            return
        card = self.cards[index]
        QTimer.singleShot(0, lambda: self._do_scroll(card))

    def _do_scroll(self, card):
        if not card or not shiboken6.isValid(card):
            return
        viewport = self.scroll_area.viewport()
        card_top_left = card.mapTo(viewport, QPoint(0, 0))
        card_rect = QRect(card_top_left, card.size())
        if viewport.rect().contains(card_rect):
            return
        scrollbar = self.scroll_area.horizontalScrollBar()
        if card_rect.left() < 0:
            target = scrollbar.value() + card_rect.left() - 12
        else:
            target = scrollbar.value() + card_rect.right() - viewport.width() + 12
        target = int(max(0, min(target, scrollbar.maximum())))
        self.scroll_anim.stop()
        self.scroll_anim.setStartValue(int(scrollbar.value()))
        self.scroll_anim.setEndValue(target)
        self._scroll_target = target
        self.scroll_anim.start()

    def _finish_scroll(self):
        self.scroll_area.horizontalScrollBar().setValue(int(self._scroll_target))

    def _on_card_clicked(self, game_dict):
        """A card click selects it; launching is reserved for Play."""
        card = self.sender()
        if card and card in self.cards:
            self.focused_index = self.cards.index(card)
            card.setFocus()
        self.game_selected.emit(game_dict)

    # ── Key events ────────────────────────────────────────────────────────
    #
    # Navigation key path (after the QScrollArea passthrough fix):
    #   GameCard.keyPressEvent(ignore) → container(ignore) →
    #   _PassthroughScrollArea(ignore) → GameRow.keyPressEvent ← here
    #
    def keyPressEvent(self, event):
        key = event.key()
        if event.modifiers() & Qt.ShiftModifier and key in (Qt.Key_Left, Qt.Key_Right):
            self.scroll_horizontal(-1 if key == Qt.Key_Left else 1)
        elif key == Qt.Key_Right:
            self.focus_card(self.focused_index + 1)
        elif key == Qt.Key_Left:
            self.focus_card(self.focused_index - 1)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            if self.cards and self.focused_index < len(self.cards):
                self.game_selected.emit(self.cards[self.focused_index].game_dict)
        elif key == Qt.Key_Up:
            self.navigate_up.emit()
        elif key == Qt.Key_Down:
            self.navigate_down.emit()
        else:
            # Everything else (Tab, F, S, Escape…) propagates up to HomeView
            super().keyPressEvent(event)

    def scroll_horizontal(self, direction):
        scrollbar = self.scroll_area.horizontalScrollBar()
        amount = max(80, self.scroll_area.viewport().width() // 2)
        scrollbar.setValue(scrollbar.value() + direction * amount)

    def wheelEvent(self, event):
        hdelta = event.angleDelta().x()
        vdelta = event.angleDelta().y()

        if hdelta != 0 or (event.modifiers() & Qt.ShiftModifier):
            # Horizontal swipe or Shift+wheel → scroll cards left/right
            scrollbar = self.scroll_area.horizontalScrollBar()
            move = -int((hdelta or -vdelta) / 8) * 3
            scrollbar.setValue(scrollbar.value() + move)
            event.accept()
        else:
            # Regular vertical scroll → let the outer rows_scroll handle it
            event.ignore()


    def get_cards(self):
        return self.cards
