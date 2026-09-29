from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QLabel, QPushButton, QSizePolicy, QFrame)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize, QRect, QEvent, QTimer
from PySide6.QtGui import QColor, QPainter, QFont, QPixmap
from pathlib import Path
from difflib import SequenceMatcher
from core import userdata
from core.config import config
from ui.theme import get_theme_colors

class SearchView(QWidget):
    game_selected = Signal(dict)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.games = []
        self.filtered_games = []
        
        self.current_focus = 'input'
        self.results_mode = False
        self._active_keyboard_button = None
        self.active_platform_filter = 'ALL'
        self.platforms = ['ALL', 'PC', 'PS2', 'PS3', 'PS4', 'SWITCH']
        self.filter_buttons = []
        palette = get_theme_colors(accent_name=config.settings.get("accent"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 42, 56, 34)
        layout.setSpacing(18)
        
        header_container = QWidget()
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("SEARCH GAMES...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #12121a;
                color: #ffffff;
                font-size: 26px;
                padding: 16px 20px;
                border: 1px solid #303047;
                border-radius: 12px;
                selection-background-color: %s;
            }
            QLineEdit:focus {
                border: 2px solid %s;
                background-color: #181626;
            }
        """ % (palette["ACCENT"], palette["HIGHLIGHT"]))
        self.search_input.textChanged.connect(self._filter)
        self.search_input.returnPressed.connect(self.show_results_mode)
        self.search_input.installEventFilter(self)
        header_layout.addWidget(self.search_input)
        layout.addWidget(header_container)

        filter_row = QHBoxLayout()
        self.filter_buttons_row = QWidget()
        filter_buttons_layout = QHBoxLayout(self.filter_buttons_row)
        filter_buttons_layout.setContentsMargins(0, 0, 0, 0)
        for p in self.platforms:
            btn = QPushButton(p)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.setStyleSheet(self._get_btn_style(p == self.active_platform_filter))
            btn.clicked.connect(lambda checked=False, p=p: self._set_platform_filter(p))
            btn.installEventFilter(self)
            self.filter_buttons.append(btn)
            filter_buttons_layout.addWidget(btn)
            
        filter_buttons_layout.addStretch()
        
        self.count_label = QLabel("0 results")
        self.count_label.setStyleSheet("color: #64748b; font-size: 16px; font-weight: bold;")
        filter_buttons_layout.addWidget(self.count_label)
        
        layout.addWidget(self.filter_buttons_row)
        self.filter_buttons_row.hide()

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setFocusPolicy(Qt.StrongFocus)
        self.list_widget.installEventFilter(self)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(6)
        self.list_widget.setCursor(Qt.PointingHandCursor)
        self.list_widget.setContentsMargins(4, 6, 4, 10)
        self.list_widget.setWordWrap(False)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
            }
            QListWidget::item {
                padding: 0px;
                color: #e2e8f0;
                background: transparent;
                border: none;
            }
            QListWidget::item:selected {
                background-color: transparent;
                border: none;
            }
        """)
        # Open a result on a single click; Enter/controller confirmation still
        # uses the same activation handler through the keyboard path.
        self.list_widget.itemClicked.connect(self._on_item_activated)
        self.list_widget.currentRowChanged.connect(self._highlight_search_result)
        layout.addWidget(self.list_widget)

        self._build_virtual_keyboard()
        self.refresh_theme()
        self.list_widget.hide()

    def _build_virtual_keyboard(self):
        self.keyboard = QFrame(self)
        self.keyboard.setObjectName("virtualKeyboard")
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.keyboard.setStyleSheet(
            f"QFrame#virtualKeyboard {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 14px; }}"
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; border: 1px solid {palette['ACCENT']}; border-radius: 7px; padding: 8px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: #ffffff; border-color: {palette['ACCENT2']}; }}"
        )
        grid = QGridLayout(self.keyboard)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        self.keyboard_positions = {}
        for row_index, letters in enumerate(rows):
            for col, letter in enumerate(letters):
                button = QPushButton(letter)
                button.setMinimumSize(46, 42)
                button.setFocusPolicy(Qt.StrongFocus)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(lambda checked=False, value=letter: self._keyboard_insert(value))
                button.installEventFilter(self)
                self.keyboard_positions[button] = (row_index, col)
                grid.addWidget(button, row_index, col)
        backspace = QPushButton("⌫")
        backspace.setMinimumSize(46, 42)
        backspace.setFocusPolicy(Qt.StrongFocus)
        backspace.installEventFilter(self)
        self.keyboard_positions[backspace] = (0, 10)
        backspace.clicked.connect(self._erase_last_character)
        grid.addWidget(backspace, 0, 10)
        clear = QPushButton("CLEAR")
        clear.setMinimumSize(46, 42)
        clear.setFocusPolicy(Qt.StrongFocus)
        clear.installEventFilter(self)
        self.keyboard_positions[clear] = (2, 9)
        clear.clicked.connect(self.search_input.clear)
        grid.addWidget(clear, 2, 9)
        done = QPushButton("DONE")
        done.setMinimumSize(46, 42)
        done.setFocusPolicy(Qt.StrongFocus)
        done.installEventFilter(self)
        self.keyboard_positions[done] = (2, 10)
        done.clicked.connect(self._finish_virtual_search)
        grid.addWidget(done, 2, 10)
        space = QPushButton("SPACE")
        space.setMinimumSize(46, 42)
        space.setFocusPolicy(Qt.StrongFocus)
        space.installEventFilter(self)
        self.keyboard_positions[space] = (3, 7)
        space.clicked.connect(lambda: self._keyboard_insert(" "))
        grid.addWidget(space, 3, 7, 1, 4)
        for column in range(11):
            grid.setColumnStretch(column, 1)
        self.keyboard_buttons = [grid.itemAt(i).widget() for i in range(grid.count()) if grid.itemAt(i).widget()]
        self._active_keyboard_button = next((b for b in self.keyboard_buttons if b.text() == "A"), None)
        self.keyboard.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "keyboard"):
            width = min(860, max(560, self.width() - 40))
            visible_y = self.height() - 315
            current_y = self.keyboard.geometry().y()
            y = visible_y if self.keyboard.isVisible() and current_y <= self.height() else self.height() + 12
            self.keyboard.setGeometry((self.width() - width) // 2, y, width, 300)

    def _animate_keyboard(self, showing):
        width = min(860, max(560, self.width() - 40))
        visible = QRect((self.width() - width) // 2, self.height() - 315, width, 300)
        hidden = QRect((self.width() - width) // 2, self.height() + 12, width, 300)
        if getattr(self, "_keyboard_animation", None) is not None:
            self._keyboard_animation.stop()
        if showing:
            if self.keyboard.isVisible() and self.keyboard.geometry() == visible:
                return
            if not self.keyboard.isVisible():
                self.keyboard.setGeometry(hidden)
                self.keyboard.show()
            self.keyboard.raise_()
            start = self.keyboard.geometry()
            end = visible
        else:
            if not self.keyboard.isVisible():
                return
            start = self.keyboard.geometry()
            end = hidden
        animation = QPropertyAnimation(self.keyboard, b"geometry", self)
        animation.setDuration(280)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        if not showing:
            animation.finished.connect(self.keyboard.hide)
        self._keyboard_animation = animation
        animation.start()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn and obj in getattr(self, "keyboard_positions", {}):
            self._active_keyboard_button = obj
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            in_keyboard = obj in getattr(self, "keyboard_positions", {}) or obj is self.search_input
            window = self.window()
            controller_event = (
                not event.spontaneous()
                and getattr(window, "_controller_input_mode", False)
            )
            if obj is self.search_input:
                if controller_event:
                    self._animate_keyboard(True)
                elif event.spontaneous() and (event.text() or key == Qt.Key_Backspace):
                    # A physical keyboard is more efficient for text entry;
                    # keep the virtual keyboard out of the way until a
                    # controller key is detected again.
                    self._animate_keyboard(False)
            if self.results_mode and (obj is self.list_widget or obj in self.filter_buttons):
                if key in (Qt.Key_Escape, Qt.Key_Menu):
                    self.show_keyboard_mode()
                    return True
            if in_keyboard:
                if obj is self.search_input and key in (Qt.Key_Return, Qt.Key_Enter):
                    self._finish_virtual_search()
                    return True
                if key in (Qt.Key_Escape,):  # Controller B: erase the last character.
                    self._erase_last_character()
                    return True
                if key == Qt.Key_Menu:  # Controller X: insert a space.
                    self._keyboard_insert(" ")
                    return True
                if key == Qt.Key_F:  # Controller Y: show the results list.
                    self._finish_virtual_search()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter):  # Controller A: activate the focused key.
                    button = obj if obj in self.keyboard_buttons else self._active_keyboard_button
                    if button:
                        button.click()
                    else:
                        self._focus_first_keyboard_key()
                    return True
        if getattr(self, "list_widget", None) is obj and event.type() == QEvent.Type.KeyPress:
            row = self.list_widget.currentRow()
            if event.key() == Qt.Key_Down:
                self.list_widget.setCurrentRow(min(self.list_widget.count() - 1, row + 1))
                return True
            if event.key() == Qt.Key_Up:
                if row <= 0:
                    self.filter_buttons[self.platforms.index(self.active_platform_filter)].setFocus()
                else:
                    self.list_widget.setCurrentRow(row - 1)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and 0 <= row < len(self.filtered_games):
                self.game_selected.emit(self.filtered_games[row])
                return True
        if obj in getattr(self, "keyboard_positions", {}):
            if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                self._move_keyboard_focus(obj, event.key())
                return True
        if obj is self.search_input:
            if event.type() == QEvent.Type.FocusIn:
                if not self.results_mode:
                    self._animate_keyboard(True)
            elif event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(120, lambda: self._animate_keyboard(False) if self.focusWidget() not in self.keyboard_buttons and self.focusWidget() is not self.search_input else None)
            elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key_Down, Qt.Key_Right):
                if self.keyboard_buttons:
                    self._animate_keyboard(True)
                    self._focus_first_keyboard_key()
                    return True
        return super().eventFilter(obj, event)

    def _move_keyboard_focus(self, button, key):
        row, col = self.keyboard_positions[button]
        if key in (Qt.Key_Left, Qt.Key_Right):
            direction = -1 if key == Qt.Key_Left else 1
            choices = sorted((c, b) for b, (r, c) in self.keyboard_positions.items() if r == row)
            columns = [c for c, _ in choices]
            index = columns.index(col)
            target = max(0, min(len(choices) - 1, index + direction))
            choices[target][1].setFocus()
            return

        direction = -1 if key == Qt.Key_Up else 1
        target_row = row + direction
        if target_row < 0:
            self.search_input.setFocus()
            return
        choices = [(c, b) for b, (r, c) in self.keyboard_positions.items() if r == target_row]
        if not choices:
            return
        _, target = min(choices, key=lambda item: abs(item[0] - col))
        target.setFocus()

    def _keyboard_insert(self, value):
        self.search_input.setText(self.search_input.text() + value)
        self.search_input.setCursorPosition(len(self.search_input.text()))

    def _erase_last_character(self):
        text = self.search_input.text()
        if text:
            self.search_input.setText(text[:-1])
            self.search_input.setCursorPosition(len(self.search_input.text()))

    def _focus_first_keyboard_key(self):
        button = next((b for b in self.keyboard_buttons if b.text() == "A"), None)
        if button:
            button.setFocus()

    def show_keyboard_mode(self):
        # The keyboard is now an input layer on top of the results page,
        # rather than a separate first screen.
        self.results_mode = True
        self.filter_buttons_row.show()
        self.list_widget.show()
        self._animate_keyboard(True)
        QTimer.singleShot(0, self._focus_first_keyboard_key)

    def show_results_mode(self):
        self.results_mode = True
        self.filter_buttons_row.show()
        self.list_widget.show()
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        if getattr(self.window(), "_controller_input_mode", False):
            self._animate_keyboard(True)
            QTimer.singleShot(0, self._focus_first_keyboard_key)
        else:
            self._animate_keyboard(False)
            self.search_input.setFocus(Qt.OtherFocusReason)

    def _finish_virtual_search(self):
        """Keep the results page visible after virtual-keyboard entry."""
        self.results_mode = True
        self._animate_keyboard(False)
        self.filter_buttons_row.show()
        self.list_widget.show()
        self.search_input.setFocus(Qt.OtherFocusReason)
        

    def _get_btn_style(self, active=False):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        if active:
            return f"QPushButton {{ background-color: {palette['ACCENT']}; color: white; font-weight: bold; padding: 10px 20px; border-radius: 8px; font-size: 14px; border: 1px solid {palette['ACCENT2']}; }} QPushButton:focus {{ border: 2px solid #ffffff; }}"
        else:
            return f"QPushButton {{ background-color: {palette['SURFACE']}; color: {palette['TEXT_DIM']}; font-weight: bold; padding: 10px 20px; border-radius: 8px; font-size: 14px; border: 1px solid #2d2d42; }} QPushButton:hover {{ color: #ffffff; border-color: {palette['ACCENT2']}; }} QPushButton:focus {{ background-color: {palette['PANEL']}; color: #ffffff; border: 2px solid {palette['HIGHLIGHT']}; }}"

    def _update_btn_styles(self):
        for i, p in enumerate(self.platforms):
            self.filter_buttons[i].setStyleSheet(self._get_btn_style(p == self.active_platform_filter))

    def _set_platform_filter(self, p):
        self.active_platform_filter = p
        self._update_btn_styles()
        self._filter(self.search_input.text())

    def cycle_platform_filter(self, direction):
        """Cycle the platform filter for controller shoulder navigation."""
        if not self.platforms:
            return
        index = self.platforms.index(self.active_platform_filter)
        self._set_platform_filter(self.platforms[(index + int(direction)) % len(self.platforms)])

    def set_games(self, games_list):
        self.games = games_list
        self.search_input.clear()
        self._filter("")

    def update_game_art(self, game_key, cover_path):
        for g in self.games:
            if g.get("key") == game_key:
                g["cover_path"] = cover_path
                break

    def _filter(self, text):
        self.list_widget.clear()
        self.filtered_games = []
        
        q = text.lower()
        ranked = []
        for g in self.games:
            p = g.get("platform", "").upper()
            if self.active_platform_filter != 'ALL' and p != self.active_platform_filter:
                continue
            title = g.get("title", "").lower()
            if not q:
                score = 0.0
            elif q in title:
                # Keep direct matches ahead of approximate matches.
                score = 2.0 - (title.index(q) / max(1, len(title)))
            else:
                compact_query = "".join(ch for ch in q if ch.isalnum())
                compact_title = "".join(ch for ch in title if ch.isalnum())
                word_ratio = max(
                    (SequenceMatcher(None, compact_query, word).ratio() for word in title.split()),
                    default=0.0,
                )
                ratio = max(word_ratio, SequenceMatcher(None, compact_query, compact_title).ratio())
                # Also reward a query whose letters appear in order across the
                # title, which is useful for abbreviated controller searches.
                cursor = 0
                for char in compact_title:
                    if cursor < len(compact_query) and char == compact_query[cursor]:
                        cursor += 1
                subsequence = cursor / max(1, len(compact_query))
                score = ratio * 0.72 + subsequence * 0.28
                threshold = 0.28 if len(compact_query) >= 3 else 0.50
                if score < threshold:
                    continue
            ranked.append((score, g))

        ranked.sort(key=lambda item: (-item[0], item[1].get("title", "").lower()))
        self.filtered_games = [game for _score, game in ranked]
                
        for g in self.filtered_games:
            title = g.get("title", "")
            platform = str(g.get("platform", "")).upper()
            game_key = g.get("key", "")
            
            pt_seconds = userdata.get_playtime(game_key)
            if pt_seconds > 0:
                mins = pt_seconds // 60
                if mins < 1:
                    pt_str = "▶ <1m"
                elif mins < 60:
                    pt_str = f"▶ {mins}m"
                else:
                    h = mins // 60
                    m = mins % 60
                    if m == 0:
                        pt_str = f"▶ {h}h"
                    else:
                        pt_str = f"▶ {h}h {m}m"
            else:
                pt_str = "▶ 0m"
                
            item_widget = QWidget()
            item_widget.setObjectName("searchResult")
            item_widget.setFixedHeight(72)
            item_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            palette = get_theme_colors(accent_name=config.settings.get("accent"))
            item_widget.setStyleSheet(
                f"QWidget#searchResult {{ background: {palette['SURFACE']}; border: none; border-radius: 5px; }}"
            )
            item_widget.setAttribute(Qt.WA_Hover, True)
            item_widget.setCursor(Qt.PointingHandCursor)
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(16, 8, 16, 8)
            item_layout.setSpacing(14)
            
            # Search rows lead with the emulator logo, then the SteamGridDB
            # cover thumbnail, followed by the title.
            emulator_icon = QLabel()
            emulator_icon.setAlignment(Qt.AlignCenter)
            emulator_icon.setFixedSize(34, 34)
            badge_style = {
                "PC": "background: #ffffff; border: 1px solid rgba(0,0,0,90); border-radius: 17px; color: #17456b;",
                "PS2": "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #001a5e, stop:1 #0050d0); border: 1px solid rgba(255,255,255,90); border-radius: 17px;",
                "PS3": "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #001060, stop:1 #003fc7); border: 1px solid rgba(255,255,255,90); border-radius: 17px;",
                "PS4": "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00185a, stop:1 #0044bb); border: 1px solid rgba(255,255,255,90); border-radius: 17px;",
                "SWITCH": "background: #ffffff; border: 1px solid rgba(0,0,0,90); border-radius: 17px; color: #000000;",
            }
            emulator_icon.setStyleSheet(badge_style.get(platform.upper(), "background: #27223d; border-radius: 17px;"))
            logo_file = {"PS2": "ps2-logo.png", "PS3": "ps3-logo.png", "SWITCH": "switch-logo.png"}.get(platform)
            logo_path = (
                config.project_root / "assets" / "Emus" / logo_file
                if logo_file else
                config.project_root / "assets" / "UI" / "pc_badge.svg"
                if platform == "PC" else None
            )
            if logo_path is not None:
                pixmap = QPixmap(str(logo_path))
                if not pixmap.isNull():
                    emulator_icon.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                emulator_icon.setText({"PS4": "◈"}.get(platform, "✦"))

            steam_icon = QLabel()
            steam_icon.setFixedSize(38, 54)
            steam_icon.setAlignment(Qt.AlignCenter)
            cover_path = g.get("cover_path")
            if cover_path:
                cover = QPixmap(cover_path)
                if not cover.isNull():
                    steam_icon.setPixmap(cover.scaled(36, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("color: #ffffff; font-size: 17px; font-weight: bold;")
            lbl_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl_title.setTextInteractionFlags(Qt.NoTextInteraction)
            
            lbl_pt = QLabel(pt_str)
            lbl_pt.setStyleSheet(f"color: {palette['ACCENT2']}; font-size: 13px; font-weight: bold;")
            lbl_pt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            item_layout.addWidget(emulator_icon)
            item_layout.addWidget(steam_icon)
            item_layout.addWidget(lbl_title)
            item_layout.addStretch()
            item_layout.addWidget(lbl_pt)
            for child in item_widget.findChildren(QWidget):
                child.setCursor(Qt.PointingHandCursor)
            
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 72))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)
            
        self.count_label.setText(f"{len(self.filtered_games)} results")
        if self.filtered_games:
            self.list_widget.setCurrentRow(0)

    def _on_item_activated(self, item):
        row = self.list_widget.row(item)
        if 0 <= row < len(self.filtered_games):
            self.game_selected.emit(self.filtered_games[row])
            self.closed.emit()

    def _highlight_search_result(self, row):
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            widget = self.list_widget.itemWidget(item)
            if widget:
                palette = get_theme_colors(accent_name=config.settings.get("accent"))
                color = palette["ACCENT"] if index == row else palette["SURFACE"]
                widget.setStyleSheet(
                    f"QWidget#searchResult {{ background: {color}; border: none; border-radius: 5px; }}"
                    f"QWidget#searchResult:hover {{ background: {palette['PANEL']}; }}"
                )

    def refresh_theme(self):
        from core.config import config
        from ui.theme import get_theme_colors
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.keyboard.setStyleSheet(
            f"QFrame#virtualKeyboard {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 14px; }}"
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; border: 1px solid {palette['ACCENT']}; border-radius: 7px; padding: 8px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: #ffffff; border-color: {palette['ACCENT2']}; }}"
        )
        for index in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(index))
            if widget:
                color = palette['ACCENT'] if index == self.list_widget.currentRow() else palette['SURFACE']
                widget.setStyleSheet(
                    f"QWidget#searchResult {{ background: {color}; border: none; border-radius: 5px; }}"
                )
                for label in widget.findChildren(QLabel):
                    if label.text().startswith("▶"):
                        label.setStyleSheet(
                            f"color: {palette['ACCENT_TEXT'] if index == self.list_widget.currentRow() else palette['ACCENT2']}; "
                            "font-size: 13px; font-weight: bold;"
                        )

    def scroll_by_page(self, direction):
        bar = self.list_widget.verticalScrollBar()
        amount = max(80, self.list_widget.viewport().height() * 2 // 3)
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(260)
        animation.setStartValue(bar.value())
        animation.setEndValue(bar.value() + direction * amount)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation = animation
        animation.start()

    def keyPressEvent(self, event):
        k = event.key()
        
        if k == Qt.Key_BracketRight:
            idx = self.platforms.index(self.active_platform_filter)
            next_idx = (idx + 1) % len(self.platforms)
            self._set_platform_filter(self.platforms[next_idx])
            return
        elif k == Qt.Key_BracketLeft:
            idx = self.platforms.index(self.active_platform_filter)
            prev_idx = (idx - 1) % len(self.platforms)
            self._set_platform_filter(self.platforms[prev_idx])
            return

        focused = self.focusWidget()
        
        if k == Qt.Key_Escape:
            self.closed.emit()
            return
            
        if k == Qt.Key_Down:
            if focused == self.search_input:
                self.filter_buttons[self.platforms.index(self.active_platform_filter)].setFocus()
            elif focused in self.filter_buttons:
                if self.list_widget.count() > 0:
                    self.list_widget.setFocus()
                    if self.list_widget.currentRow() < 0:
                        self.list_widget.setCurrentRow(0)
            else:
                super().keyPressEvent(event)
            return
            
        if k == Qt.Key_Up:
            if focused == self.list_widget:
                if self.list_widget.currentRow() <= 0:
                    self.filter_buttons[self.platforms.index(self.active_platform_filter)].setFocus()
                else:
                    super().keyPressEvent(event)
            elif focused in self.filter_buttons:
                self.search_input.setFocus()
            else:
                super().keyPressEvent(event)
            return
            
        if k == Qt.Key_Right and focused in self.filter_buttons:
            idx = self.filter_buttons.index(focused)
            if idx < len(self.filter_buttons) - 1:
                self.filter_buttons[idx + 1].setFocus()
            return
            
        if k == Qt.Key_Left and focused in self.filter_buttons:
            idx = self.filter_buttons.index(focused)
            if idx > 0:
                self.filter_buttons[idx - 1].setFocus()
            return
            
        if (k == Qt.Key_Return or k == Qt.Key_Enter) and focused in self.filter_buttons:
            focused.click()
            return

        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(5, 5, 10, 240))
        painter.end()
