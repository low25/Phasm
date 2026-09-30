from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication,
    QPushButton, QScrollArea, QSizePolicy, QFrame, QTextBrowser, QMenu, QDialog, QLineEdit, QGridLayout, QTabWidget,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QThread, QPropertyAnimation, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QPoint, QRect, QSize, QEvent, QBuffer, QIODevice
from PySide6.QtGui import QColor, QPixmap, QCursor, QIcon, QFont, QPainter, QLinearGradient, QImageReader

from ui.widgets.hero_banner import HeroBanner
from ui.widgets.starfield import Starfield
from ui.widgets.platform_tab import PlatformTab
from ui.game_row import GameRow
from ui.game_grid import GameGrid
from ui.game_list import GameList
from core.userdata import toggle_favorite, is_favorite
from core import userdata
from datetime import datetime
from core.config import config
from core.library import game_is_installed, should_show_game
from ui.sound_manager import sound_manager
from ui.theme import get_theme_colors
import shiboken6
from pathlib import Path
import shutil
import requests
from core.assets import SteamGridDB, download_custom_artwork
from core.metadata import _save_local_metadata
from core.artwork_color import dominant_accent
from core.desktop_entry import create_desktop_entry, desktop_entry_exists, remove_desktop_entry
from ui.phasm_dialog import show_message, confirm_message


# ── Focus zones ───────────────────────────────────────────────────────────────
# ZONE_BUTTONS  = top action bar  (Play / Favorite / Settings / Quit)
# ZONE_ROWS     = game card rows  (default)
ZONE_BUTTONS = "buttons"
ZONE_ROWS    = "rows"


from PySide6.QtCore import QObject, QEvent

class _BtnZoneFilter(QObject):
    """Event filter installed on each nav button.

    Redirects all key events back to the HomeView so that Left/Right/Up/Down
    are always handled by our zone logic and never by Qt's default focus
    traversal (which would move focus to the next widget in tab order).
    """
    def __init__(self, home_view):
        super().__init__(home_view)
        self._home = home_view

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            self._home.keyPressEvent(event)
            return True   # consumed — don't let Qt do default focus traversal
        return False


class _CollectionToolbarFilter(QObject):
    """Keep controller focus navigation inside collection actions."""
    def __init__(self, home_view):
        super().__init__(home_view)
        self.home = home_view

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            return self.home._collection_toolbar_key(obj, event)
        return False


class _DetailInputFilter(QObject):
    def __init__(self, home_view):
        super().__init__(home_view)
        self.home = home_view

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and self.home.detail_overlay.isVisible():
            key = event.key()
            if key == Qt.Key_Escape:
                self.home._close_game_details()
                return True
            controls = [self.home.detail_close, self.home.detail_artwork, self.home.detail_favorite, self.home.detail_remove, self.home.detail_install, self.home.detail_play]
            if key in (Qt.Key_Up, Qt.Key_Down) and obj in controls:
                index = controls.index(obj) + (-1 if key == Qt.Key_Up else 1)
                controls[max(0, min(len(controls) - 1, index))].setFocus()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter) and isinstance(obj, QPushButton):
                obj.click()
                return True
        return False


class _ControllerContextMenu(QMenu):
    """Context menu that can be dismissed by the controller toggle buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep menus as frameless, launcher-owned Qt surfaces. This prevents
        # the desktop from treating them like a separate native application
        # window and keeps the custom cursor/modal handoff consistent.
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)

    def showEvent(self, event):
        super().showEvent(event)
        # QMenu normally focuses itself, but controller-generated key events
        # can arrive during the popup transition. Claim focus explicitly so
        # arrows and confirm are handled by the menu, not the card underneath.
        self.setFocus(Qt.PopupFocusReason)
        if self.activeAction() is None:
            first = next((action for action in self.actions()
                          if action.isVisible() and action.isEnabled() and not action.isSeparator()), None)
            if first is not None:
                self.setActiveAction(first)

    def keyPressEvent(self, event):
        # X sends Key_Menu. Y normally sends F for favorite; while the menu
        # owns focus, use that same controller button as a second close key.
        if event.key() in (Qt.Key_Menu, Qt.Key_F, Qt.Key_Escape):
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

class _InAppContextMenu(QWidget):
    """A launcher-owned menu overlay, never a native Qt popup window."""

    def __init__(self, parent, palette, width=330, return_menu=None):
        super().__init__(parent)
        self._previous_focus = QApplication.focusWidget()
        self._return_menu = return_menu
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.panel = QFrame(self)
        self.panel.setFixedWidth(width)
        self.panel.setObjectName("inAppMenuPanel")
        self.panel.setStyleSheet(
            f"QFrame#inAppMenuPanel {{ background: {palette['PANEL']}; "
            f"border: 1px solid {palette['ACCENT']}; border-radius: 9px; }}"
            f"QPushButton {{ background: transparent; color: {palette['TEXT']}; "
            "border: none; border-radius: 6px; text-align: left; padding: 11px 14px; "
            "font-size: 13px; font-weight: bold; }"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
            f"QLabel {{ color: {palette['TEXT_DIM']}; padding: 7px 14px 3px; "
            "font-size: 11px; font-weight: bold; letter-spacing: 1px; }"
        )
        self.layout = QVBoxLayout(self.panel)
        self.layout.setContentsMargins(7, 7, 7, 7)
        self.layout.setSpacing(2)
        self.buttons = []
        self._focused_index = 0

    def add_label(self, text):
        self.layout.addWidget(QLabel(text, self.panel))

    def add_action(self, text, callback, icon=None):
        button = QPushButton(text, self.panel)
        button.setFocusPolicy(Qt.StrongFocus)
        button.installEventFilter(self)
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
            button.setIconSize(QSize(22, 22))
        button.clicked.connect(callback)
        self.layout.addWidget(button)
        self.buttons.append(button)
        return button

    def add_scroll_select(self, title, options, callback):
        """Add a bounded, controller-navigable in-app option list."""
        self.add_label(title)
        scroll = QScrollArea(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)
        for text, option_icon, value in options:
            button = QPushButton(text, content)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setMinimumHeight(36)
            button.installEventFilter(self)
            if option_icon is not None and not option_icon.isNull():
                button.setIcon(option_icon)
                button.setIconSize(QSize(20, 20))
            button.clicked.connect(lambda checked=False, v=value: callback(v))
            content_layout.addWidget(button)
            self.buttons.append(button)
        content_layout.addStretch()
        scroll.setWidget(content)
        scroll.setFixedHeight(min(220, max(44, len(options) * 38 + 4)))
        self.layout.addWidget(scroll)
        self._scroll_select = scroll
        return scroll

    def _focus_menu_button(self, index):
        if not self.buttons:
            return
        index = max(0, min(len(self.buttons) - 1, index))
        self._focused_index = index
        button = self.buttons[index]
        button.setFocus(Qt.PopupFocusReason)
        scroll = getattr(self, "_scroll_select", None)
        if scroll is not None and scroll.isAncestorOf(button):
            scroll.ensureWidgetVisible(button, 0, 8)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn and obj in self.buttons:
            self._focused_index = self.buttons.index(obj)
        if event.type() == QEvent.Type.KeyPress and obj in self.buttons:
            index = self.buttons.index(obj)
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Right):
                self._focus_menu_button(index + 1)
                return True
            if key in (Qt.Key_Up, Qt.Key_Left):
                self._focus_menu_button(index - 1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                obj.click()
                return True
            if key in (Qt.Key_Escape, Qt.Key_Menu):
                self.close_menu()
                return True
        return super().eventFilter(obj, event)

    def open_at(self, global_position):
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self.panel.adjustSize()
        point = self.mapFromGlobal(global_position)
        x = max(10, min(point.x(), self.width() - self.panel.width() - 10))
        y = max(10, min(point.y(), self.height() - self.panel.height() - 10))
        self.panel.move(x, y)
        self.show()
        self.raise_()
        if self.buttons:
            self._focused_index = 0
            self._focus_menu_button(0)

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.close_menu()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Menu):
            self.close_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def handle_controller_key(self, key):
        if not self.buttons:
            return True
        index = max(0, min(self._focused_index, len(self.buttons) - 1))
        if key in (Qt.Key_Down, Qt.Key_Right):
            self._focus_menu_button(index + 1)
            return True
        if key in (Qt.Key_Up, Qt.Key_Left):
            self._focus_menu_button(index - 1)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.buttons[index].click()
            return True
        if key in (Qt.Key_Escape, Qt.Key_Menu):
            self.close_menu()
            return True
        return False

    def close_menu(self):
        parent = self.parentWidget()
        if parent is not None and getattr(parent, "_in_app_context_menu", None) is self:
            if self._return_menu is not None and shiboken6.isValid(self._return_menu):
                parent._in_app_context_menu = self._return_menu
                self._return_menu.show()
                self._return_menu.raise_()
            else:
                parent._in_app_context_menu = None
        target = self._previous_focus
        if target is not None and shiboken6.isValid(target) and target.isVisible() and target.isEnabled():
            target.setFocus(Qt.OtherFocusReason)
        self.hide()
        self.deleteLater()


class _CollectionNameDialog(QDialog):
    """In-app collection naming overlay with a controller friendly keyboard."""

    def __init__(self, parent=None, initial_name=""):
        super().__init__(parent)
        self.setWindowTitle("Rename Collection" if initial_name else "New Collection")
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._previous_focus = QApplication.focusWidget()
        self.setFixedSize(700, 470)
        self._active_key = None
        self._closing = False
        self._keyboard_positions = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.setObjectName("collectionNameOverlay")
        self.setStyleSheet(
            f"QDialog#collectionNameOverlay {{ background: {palette['PANEL']}; "
            f"border: 1px solid {palette['ACCENT']}; border-radius: 16px; }}"
        )
        header = QHBoxLayout()
        title = QLabel("RENAME COLLECTION" if initial_name else "NAME NEW COLLECTION")
        title.setStyleSheet("font-size: 22px; font-weight: bold; letter-spacing: 2px; color: #f8fafc;")
        header.addWidget(title)
        header.addStretch()
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setFocusPolicy(Qt.StrongFocus)
        self.cancel_button.setFixedSize(98, 36)
        self.cancel_button.setAccessibleName("Cancel collection name")
        self.cancel_button.setStyleSheet(
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; "
            f"border: 1px solid {palette['ACCENT']}; border-radius: 7px; padding: 6px 12px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
        )
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.installEventFilter(self)
        header.addWidget(self.cancel_button)
        layout.addLayout(header)
        self.name_input = QLineEdit()
        self.name_input.setText(initial_name)
        self.name_input.setCursorPosition(len(initial_name))
        self.name_input.setPlaceholderText("Collection name")
        self.name_input.setFocusPolicy(Qt.StrongFocus)
        self.name_input.setStyleSheet(
            "QLineEdit { background: #12121a; color: white; font-size: 22px; "
            "padding: 12px 16px; border: 1px solid #6d4bb5; border-radius: 10px; }"
        )
        layout.addWidget(self.name_input)
        layout.addStretch()

        self.keyboard = QFrame(self)
        self.keyboard.setObjectName("collectionKeyboard")
        self.keyboard.setStyleSheet(
            f"QFrame#collectionKeyboard {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 14px; }}"
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; border: 1px solid {palette['ACCENT']}; "
            "border-radius: 7px; padding: 8px; font-size: 13px; font-weight: bold; }"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; border-color: {palette['ACCENT2']}; }}"
        )
        grid = QGridLayout(self.keyboard)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        rows = ("1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")
        for row, letters in enumerate(rows):
            for col, letter in enumerate(letters):
                button = self._key_button(letter, lambda value=letter: self._insert(value))
                button.setMinimumSize(46, 42)
                self._keyboard_positions[button] = (row, col)
                grid.addWidget(button, row, col)
        backspace = self._key_button("⌫", self._erase)
        backspace.setMinimumSize(46, 42)
        self._keyboard_positions[backspace] = (0, 10)
        grid.addWidget(backspace, 0, 10)
        clear = self._key_button("CLEAR", self.name_input.clear)
        clear.setMinimumSize(46, 42)
        self._keyboard_positions[clear] = (2, 9)
        grid.addWidget(clear, 2, 9)
        done = self._key_button("DONE", self._finish)
        done.setMinimumSize(46, 42)
        self._keyboard_positions[done] = (2, 10)
        grid.addWidget(done, 2, 10)
        space = self._key_button("SPACE", lambda: self._insert(" "))
        space.setMinimumSize(46, 42)
        self._keyboard_positions[space] = (3, 7)
        grid.addWidget(space, 3, 7, 1, 4)
        for column in range(11):
            grid.setColumnStretch(column, 1)
        self._keyboard_buttons = list(self._keyboard_positions)
        self._active_key = next(button for button in self._keyboard_buttons if button.text() == "A")
        self.name_input.installEventFilter(self)

    def _key_button(self, text, slot):
        button = QPushButton(text, self.keyboard)
        button.setFocusPolicy(Qt.StrongFocus)
        # QPushButton.clicked emits a checked bool; keyboard callbacks do not
        # use it and letter lambdas must retain their captured string.
        button.clicked.connect(lambda _checked=False, callback=slot: callback())
        button.installEventFilter(self)
        return button

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self.window(), "_controller_input_mode", False):
            self._active_key.setFocus(Qt.PopupFocusReason)
            self._animate_keyboard(True)
        else:
            self.keyboard.hide()
            self.name_input.setFocus(Qt.PopupFocusReason)

    def handle_controller_key(self, key):
        """Handle controller navigation directly while this overlay is open."""
        focused = QApplication.focusWidget()
        controller_mode = bool(getattr(self.window(), "_controller_input_mode", False))
        if controller_mode:
            self._animate_keyboard(True)
            if focused is self.name_input:
                self._active_key.setFocus(Qt.PopupFocusReason)
                focused = self._active_key
        if focused is self.cancel_button:
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._cancel()
                return True
            if key == Qt.Key_Down:
                self._active_key.setFocus(Qt.PopupFocusReason)
                return True
        if focused is self.name_input:
            if key == Qt.Key_Up:
                self.cancel_button.setFocus(Qt.PopupFocusReason)
                return True
            if key in (Qt.Key_Down, Qt.Key_Right):
                self._active_key.setFocus(Qt.PopupFocusReason)
                return True
        if focused in self._keyboard_positions:
            if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                self._move_focus(focused, key)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                focused.click()
                return True
        if key == Qt.Key_Escape:
            if controller_mode:
                self._erase()
            else:
                self._cancel()
            return True
        if key == Qt.Key_Menu:
            self._insert(" ")
            return True
        return False

    def activate_controller_input(self):
        """Reveal the virtual keyboard and claim controller focus."""
        self._animate_keyboard(True)
        focused = QApplication.focusWidget()
        focus_targets = {*self._keyboard_positions, self.name_input, self.cancel_button}
        if focused not in focus_targets or not focused.isVisible():
            self._active_key.setFocus(Qt.PopupFocusReason)

    def _animate_keyboard(self, showing, finished=None):
        width = self.width() - 56
        height = 250
        end_y = self.height() - height - 20
        end = QRect(28, end_y, width, height)
        start = QRect(28, self.height() + 12, width, height)
        if getattr(self, "_keyboard_animation", None) is not None:
            self._keyboard_animation.stop()
        if showing:
            if not self.keyboard.isVisible():
                self.keyboard.setGeometry(start)
                self.keyboard.show()
            self.keyboard.raise_()
            begin, target = self.keyboard.geometry(), end
        else:
            if not self.keyboard.isVisible():
                return
            begin, target = self.keyboard.geometry(), start
        animation = QPropertyAnimation(self.keyboard, b"geometry", self)
        animation.setDuration(280)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        animation.setStartValue(begin)
        animation.setEndValue(target)
        if not showing:
            animation.finished.connect(self.keyboard.hide)
        if finished:
            animation.finished.connect(finished)
        self._keyboard_animation = animation
        animation.start()

    def _insert(self, value):
        self.name_input.insert(value)

    def _erase(self):
        text = self.name_input.text()
        if text:
            self.name_input.setText(text[:-1])
            self.name_input.setCursorPosition(len(self.name_input.text()))

    def _finish(self):
        if self._closing:
            return
        self._closing = True
        self._animate_keyboard(False, self.accept)

    def _cancel(self):
        if self._closing:
            return
        self._closing = True
        if self.keyboard.isVisible():
            self._animate_keyboard(False, self.reject)
        else:
            self.reject()

    def _move_focus(self, button, key):
        row, col = self._keyboard_positions[button]
        if key in (Qt.Key_Left, Qt.Key_Right):
            direction = -1 if key == Qt.Key_Left else 1
            choices = sorted((c, b) for b, (r, c) in self._keyboard_positions.items() if r == row)
            columns = [c for c, _ in choices]
            target = choices[max(0, min(len(choices) - 1, columns.index(col) + direction))][1]
        else:
            target_row = row + (-1 if key == Qt.Key_Up else 1)
            choices = [(c, b) for b, (r, c) in self._keyboard_positions.items() if r == target_row]
            if not choices:
                self.name_input.setFocus()
                return
            _, target = min(choices, key=lambda item: abs(item[0] - col))
        target.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn and obj in self._keyboard_positions:
            self._active_key = obj
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if event.spontaneous() and (event.text() or key == Qt.Key_Backspace):
                self._animate_keyboard(False)
                if obj is not self.name_input:
                    self.name_input.setFocus(Qt.OtherFocusReason)
                    if event.text():
                        self.name_input.insert(event.text())
                    elif key == Qt.Key_Backspace:
                        self._erase()
                    return True
            if self.handle_controller_key(key):
                return True
            controller_event = (
                not event.spontaneous()
                and getattr(self.window(), "_controller_input_mode", False)
            )
            if obj is self.name_input:
                if controller_event:
                    self._animate_keyboard(True)
                elif event.spontaneous() and (event.text() or key == Qt.Key_Backspace):
                    self._animate_keyboard(False)
            if obj in self._keyboard_positions:
                if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                    self._move_focus(obj, key)
                    return True
                if key == Qt.Key_Return or key == Qt.Key_Enter:
                    obj.click()
                    return True
            if obj is self.cancel_button and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.cancel_button.click()
                return True
            if obj is self.cancel_button and key == Qt.Key_Down:
                self._active_key.setFocus(Qt.PopupFocusReason)
                return True
            if obj is self.name_input and key == Qt.Key_Up:
                self.cancel_button.setFocus(Qt.PopupFocusReason)
                return True
            if key == Qt.Key_Escape:
                # The controller maps B to Escape. Keep it as backspace so
                # the visible Cancel button is an intentional navigation
                # target rather than an accidental destructive action.
                if controller_event:
                    self._erase()
                else:
                    self._cancel()
                return True
            if key == Qt.Key_Menu:
                self._insert(" ")
                return True
            if key == Qt.Key_F:
                self._finish()
                return True
            if key in (Qt.Key_Down, Qt.Key_Right) and obj is self.name_input:
                self._active_key.setFocus()
                return True
        return super().eventFilter(obj, event)


class _TintButton(QPushButton):
    """Compact modal action button with a soft animated hover tint."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._tint = None
        self._tint_animation = None

    def _animate_tint(self, target):
        # Avoid QGraphicsColorizeEffect: it captures custom-painted widgets
        # into a second painter and can conflict with Wayland repaints.
        self._tint_animation = None

    def enterEvent(self, event):
        self._animate_tint(0.72)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_tint(0.0)
        super().leaveEvent(event)


class _DetailScrim(QWidget):
    clicked_outside = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 179);")
        self.hide()

    def mousePressEvent(self, event):
        self.clicked_outside.emit()
        event.accept()


class _DetailHeroBackdrop(QWidget):
    """Hero artwork layer behind the game-details modal content."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_artwork(self, path):
        self.pixmap = QPixmap(str(path)) if path else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipRect(self.rect())
        if not self.pixmap.isNull():
            # Zoom/crop each game's hero to fill the same modal frame.
            image = self.pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (self.width() - image.width()) // 2
            y = (self.height() - image.height()) // 2
            painter.setOpacity(0.90)
            painter.drawPixmap(x, y, image)
            painter.setOpacity(1.0)
            painter.fillRect(self.rect(), QColor(5, 5, 12, 92))
        painter.end()


class _DetailBackdropResizeFilter(QObject):
    """Keep the artwork layer fitted while the modal animates its geometry."""
    def __init__(self, backdrop, parent=None):
        super().__init__(parent)
        self.backdrop = backdrop

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.backdrop.setGeometry(watched.rect())
        return False


def _modal_icon(name):
    return QIcon(str(config.project_root / "assets" / "icons" / "modal" / f"{name}.svg"))


class _CoverArtWidget(QLabel):
    """Borderless cover art with a subtle glass reflection."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignCenter)

    def set_source_pixmap(self, pixmap):
        self.source_pixmap = pixmap if pixmap and not pixmap.isNull() else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipRect(self.rect())
        if not self.source_pixmap.isNull():
            image = self.source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - image.width()) // 2
            y = (self.height() - image.height()) // 2
            painter.drawPixmap(x, y, image)
            painter.save()
            painter.setClipRect(x, y, image.width(), image.height())
            glint = QLinearGradient(x, y, x + image.width(), y + image.height())
            glint.setColorAt(0.28, QColor(255, 255, 255, 0))
            glint.setColorAt(0.48, QColor(255, 255, 255, 28))
            glint.setColorAt(0.54, QColor(255, 255, 255, 72))
            glint.setColorAt(0.60, QColor(255, 255, 255, 0))
            painter.fillRect(x, y, image.width(), image.height(), glint)
            painter.restore()
        painter.end()


class _ArtworkFetchThread(QThread):
    """Fetch artwork bytes away from Qt's GUI thread."""

    kind_results = Signal(str, object)

    def __init__(self, title, kind, parent=None):
        super().__init__(parent)
        self.title = title
        self.kind = kind

    def run(self):
        try:
            search_results = SteamGridDB.search_games(self.title, limit=1)
            if not search_results:
                return
            result = search_results[0]
            result_id = int(result.get("id"))
            kind, _label, endpoint, params = next(
                item for item in _ArtworkPickerDialog.ART_TYPES if item[0] == self.kind
            )
            choices = []
            try:
                urls = SteamGridDB.fetch_urls(endpoint, result_id, params, limit=5)
            except Exception as exc:
                print(f"[ARTWORK] {endpoint} lookup failed: {exc}")
                urls = []
            for url in urls:
                if self.isInterruptionRequested():
                    return
                if any(choice[0] == url for choice in choices):
                    continue
                try:
                    response = requests.get(url, timeout=8)
                    if response.status_code != 200 or len(response.content) > 1 * 1024 * 1024:
                        continue
                    choices.append((url, response.content))
                except Exception as exc:
                    print(f"[ARTWORK] {endpoint} download failed: {exc}")
            self.kind_results.emit(kind, choices)
        except Exception as exc:
            print(f"[ARTWORK] background fetch failed: {exc}")


class _ArtworkSaveThread(QThread):
    saved = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, kind, game, url, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.game = game
        self.url = url

    def run(self):
        try:
            path = download_custom_artwork(
                self.kind,
                self.game.get("title", ""),
                self.game.get("platform", ""),
                self.url,
            )
            if path:
                self.saved.emit(self.kind, path)
            else:
                self.failed.emit(self.kind, "The artwork could not be downloaded.")
        except Exception as exc:
            self.failed.emit(self.kind, str(exc))


class _ArtworkPickerDialog(QDialog):
    """Choose replacement artwork from SteamGridDB, one type at a time."""

    ART_TYPES = (
        ("cover", "COVER", "grids", {"dimensions": "600x900"}),
        ("hero", "HERO", "heroes", {}),
        ("logo", "LOGO", "logos", {}),
        ("icon", "ICON", "icons", {}),
    )
    artwork_saved = Signal(str, str)

    def __init__(self, game, parent=None):
        super().__init__(parent)
        # Embed the editor in HomeView instead of creating a desktop dialog
        # window. This keeps artwork selection inside Phasm and avoids native
        # modal grabs while background artwork fetches are running.
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setFocusPolicy(Qt.StrongFocus)
        self._previous_focus = QApplication.focusWidget()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self._theme = palette
        self.setObjectName("artworkEditor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QDialog#artworkEditor { background: rgba(16, 14, 27, 150); "
            f"border: 1px solid {palette['ACCENT']}; border-radius: 12px; }}"
            "QTabWidget::pane { background: rgba(0, 0, 0, 153); border: 1px solid rgba(0, 0, 0, 90); border-radius: 8px; }"
            f"QTabBar::tab {{ background: rgba(0, 0, 0, 153); color: {palette['TEXT_DIM']}; "
            "padding: 10px 18px; margin-right: 3px; border: none; border-radius: 6px; "
            "font-weight: bold; }"
            f"QTabBar::tab:hover, QTabBar::tab:selected {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
        )
        self.backdrop = _DetailHeroBackdrop(self)
        self.backdrop.set_artwork(game.get("hero_path") or game.get("cover_path"))
        self._backdrop_sizer = _DetailBackdropResizeFilter(self.backdrop, self)
        self.installEventFilter(self._backdrop_sizer)
        self.backdrop.setGeometry(self.rect())
        self.backdrop.lower()
        self.game = game
        self.selected = {}
        self.buttons = {}
        self._focused_result_index = {}
        self.pages = {}
        self.placeholders = {}
        self._fetch_thread = None
        self._save_thread = None
        self._loaded_kinds = set()
        self._loading_kind = None
        self.setWindowTitle("Edit Artwork")
        self.resize(920, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel(f"EDIT ARTWORK — {game.get('title', '').upper()}")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; letter-spacing: 1.5px; color: {palette['ACCENT2']};"
        )
        header.addWidget(title)
        header.addStretch()
        self.close_button = QPushButton()
        close_icon_path = config.project_root / "assets" / "icons" / "modal" / "close.svg"
        if close_icon_path.exists():
            self.close_button.setIcon(QIcon(str(close_icon_path)))
            self.close_button.setIconSize(QSize(18, 18))
        self.close_button.setAccessibleName("Close artwork editor")
        self.close_button.setToolTip("Close")
        self.close_button.setFocusPolicy(Qt.StrongFocus)
        self.close_button.setFixedSize(38, 38)
        self.close_button.installEventFilter(self)
        self.close_button.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid transparent; "
            f"border-radius: 7px; padding: 0px; color: {palette['TEXT']}; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; border: 1px solid {palette['ACCENT2']}; }}"
        )
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.status = QLabel("Loading the top five SteamGridDB results...")
        self.status.setStyleSheet(f"color: {palette['ACCENT2']}; font-size: 12px;")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.tabBar().setFocusPolicy(Qt.StrongFocus)
        self.tabs.tabBar().installEventFilter(self)
        for kind, label, _endpoint, _params in self.ART_TYPES:
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(10, 10, 10, 10)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            self.pages[kind] = grid
            self.buttons[kind] = []
            placeholder = QLabel("LOADING ARTWORK...", page)
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setMinimumHeight(300)
            placeholder.setStyleSheet(
                f"color: {palette['TEXT_DIM']}; font-size: 16px; font-weight: bold; letter-spacing: 1px;"
            )
            self.placeholders[kind] = placeholder
            grid.addWidget(placeholder, 0, 0, 1, 4)
            self.tabs.addTab(page, label)
        self.tabs.currentChanged.connect(self._tab_changed)
        # Do not perform network/image work while the native modal window is
        # being constructed.  On Wayland that can race the popup grab and
        # take the whole Qt process down.  The dialog is already running when
        # this callback executes, so focus and modality are fully established.
        QTimer.singleShot(0, lambda: self._start_fetch("cover"))

    def _tab_changed(self, index):
        if 0 <= index < len(self.ART_TYPES):
            sound_manager.play("ui_toggle")
            self._start_fetch(self.ART_TYPES[index][0])

    def _start_fetch(self, kind):
        if kind in self._loaded_kinds or self._loading_kind is not None:
            return
        title = str(self.game.get("title", "") or "").strip()
        if not title:
            self.status.setText("This game has no title to search for.")
            return
        self._loading_kind = kind
        self.status.setText(f"Fetching {kind.upper()} artwork...")
        self._fetch_thread = _ArtworkFetchThread(title, kind, self)
        self._fetch_thread.kind_results.connect(self._add_results)
        self._fetch_thread.finished.connect(self._fetch_finished)
        self._fetch_thread.start()

    def _add_results(self, kind, raw_choices):
        grid = self.pages.get(kind)
        if grid is None:
            return
        palette = self._theme
        added = 0
        for index, (url, raw_data) in enumerate(raw_choices):
            try:
                buffer = QBuffer()
                buffer.setData(raw_data)
                buffer.open(QIODevice.ReadOnly)
                reader = QImageReader(buffer)
                reader.setAutoTransform(True)
                source_size = reader.size()
                if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                    scale = min(180 / source_size.width(), 180 / source_size.height())
                    reader.setScaledSize(QSize(
                        max(1, int(source_size.width() * scale)),
                        max(1, int(source_size.height() * scale)),
                    ))
                image = reader.read()
                buffer.close()
                pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
            except Exception as exc:
                print(f"[ARTWORK] image preview failed: {exc}")
                continue
            if pixmap.isNull():
                continue
            choice = {"url": url, "pixmap": pixmap}
            button = QPushButton()
            button.setFocusPolicy(Qt.StrongFocus)
            button.installEventFilter(self)
            button.setIcon(QIcon(choice["pixmap"]))
            button.setIconSize(QSize(180, 180))
            button.setFixedSize(200, 210)
            button.setStyleSheet(
                f"QPushButton {{ background: rgba(0, 0, 0, 153); border: 1px solid {palette['PANEL']}; "
                "border-radius: 8px; padding: 0px; }"
                f"QPushButton:hover, QPushButton:focus {{ background: {palette['PANEL']}; "
                f"border: 2px solid {palette['ACCENT']}; border-radius: 8px; }}"
            )
            button.setToolTip(choice["url"])
            button.clicked.connect(lambda checked=False, k=kind, c=choice: self._choose(k, c))
            grid.addWidget(button, index // 4, index % 4)
            self.buttons[kind].append(button)
            added += 1
        placeholder = self.placeholders.get(kind)
        if placeholder is not None:
            placeholder.setText("NO RESULTS FOUND" if added == 0 else "")
            placeholder.setVisible(added == 0)
        tab_index = next((i for i, item in enumerate(self.ART_TYPES) if item[0] == kind), -1)
        if tab_index >= 0:
            self.tabs.setTabText(tab_index, f"{self.ART_TYPES[tab_index][1]} ({added})")
        self._loaded_kinds.add(kind)
        self._loading_kind = None
        self.status.setText(f"{kind.upper()}: {added} result(s) found.")
        if kind == self.ART_TYPES[self.tabs.currentIndex()][0] and self.buttons[kind]:
            self._focus_artwork_result(0)

    def _fetch_finished(self):
        if self._loading_kind is not None and self._loading_kind not in self._loaded_kinds:
            self._loaded_kinds.add(self._loading_kind)
            self._loading_kind = None
        self.status.setText("Select artwork to apply it immediately.")
        current_kind = self.ART_TYPES[self.tabs.currentIndex()][0]
        if current_kind not in self._loaded_kinds:
            QTimer.singleShot(0, lambda: self._start_fetch(current_kind))

    def done(self, result):
        thread = self._fetch_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.wait(10000)
        save_thread = self._save_thread
        if save_thread is not None and save_thread.isRunning():
            save_thread.requestInterruption()
            save_thread.wait(10000)
        super().done(result)

    def _focus_artwork_result(self, index=0):
        kind = self.ART_TYPES[self.tabs.currentIndex()][0]
        buttons = self.buttons.get(kind, [])
        if buttons:
            index = max(0, min(len(buttons) - 1, index))
            self._focused_result_index[kind] = index
            buttons[index].setFocus(Qt.PopupFocusReason)
            return True
        self._focused_result_index[kind] = 0
        self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
        return False

    def handle_controller_key(self, key):
        """Route synthesized controller keys before Qt focus traversal."""
        if key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            direction = -1 if key == Qt.Key_BracketLeft else 1
            index = (self.tabs.currentIndex() + direction) % len(self.ART_TYPES)
            self.tabs.setCurrentIndex(index)
            self._focus_artwork_result(0)
            return True

        kind = self.ART_TYPES[self.tabs.currentIndex()][0]
        buttons = self.buttons.get(kind, [])
        focused = QApplication.focusWidget()
        index = self._focused_result_index.get(kind, 0)
        if focused in buttons:
            index = buttons.index(focused)
            self._focused_result_index[kind] = index
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                focused.click()
                focused.setFocus(Qt.PopupFocusReason)
                return True
            if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                if key == Qt.Key_Up and index < 4:
                    self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
                    return True
                delta = {
                    Qt.Key_Left: -1, Qt.Key_Right: 1,
                    Qt.Key_Up: -4, Qt.Key_Down: 4,
                }[key]
                self._focus_artwork_result(index + delta)
                return True

        if (buttons and focused is not self.tabs.tabBar()
                and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)):
            # Some evdev/controller paths leave focus on the dialog while the
            # key is being delivered. Keep navigation alive from the tracked
            # result instead of allowing Qt to drop focus.
            if key == Qt.Key_Up and index < 4:
                self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
                return True
            delta = {
                Qt.Key_Left: -1, Qt.Key_Right: 1,
                Qt.Key_Up: -4, Qt.Key_Down: 4,
            }[key]
            self._focus_artwork_result(index + delta)
            return True

        if focused is self.tabs.tabBar():
            if key in (Qt.Key_Left, Qt.Key_Right):
                direction = -1 if key == Qt.Key_Left else 1
                index = (self.tabs.currentIndex() + direction) % len(self.ART_TYPES)
                self.tabs.setCurrentIndex(index)
                self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
                return True
            if key in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._focus_artwork_result(0)
                return True

        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and buttons:
            # Some controller backends deliver A to the dialog instead of the
            # focused image button. Use the tracked result as a safe fallback.
            buttons[max(0, min(len(buttons) - 1, index))].click()
            self._focus_artwork_result(index)
            return True

        if key in (Qt.Key_Escape, Qt.Key_Menu):
            self.reject()
            return True
        return False

    def eventFilter(self, obj, event):
        tabs = getattr(self, "tabs", None)
        current_buttons = []
        if tabs is not None:
            current_kind = self.ART_TYPES[tabs.currentIndex()][0]
            current_buttons = self.buttons.get(current_kind, [])
        if obj in current_buttons and event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
            # Artwork choices use the same hover/focus sound as game cards.
            sound_manager.play("navigate")
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            # The controller maps LB/RB to bracket keys. Handle them anywhere
            # inside this dialog so shoulder navigation works while focus is
            # on a tab, an artwork result, or the close button.
            if key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
                direction = -1 if key == Qt.Key_BracketLeft else 1
                index = (self.tabs.currentIndex() + direction) % len(self.ART_TYPES)
                self.tabs.setCurrentIndex(index)
                self._focus_artwork_result(0)
                return True
            if obj is self.tabs.tabBar():
                if key in (Qt.Key_Left, Qt.Key_Right):
                    direction = -1 if key == Qt.Key_Left else 1
                    index = (self.tabs.currentIndex() + direction) % len(self.ART_TYPES)
                    self.tabs.setCurrentIndex(index)
                    return True
                if key in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                    self._focus_artwork_result(0)
                    return True
                if key == Qt.Key_Up:
                    self.close_button.setFocus(Qt.PopupFocusReason)
                    return True
            if obj is self.close_button:
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self.close_button.click()
                    return True
                if key == Qt.Key_Down:
                    self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
                    return True
            if isinstance(obj, QPushButton) and obj in self.buttons.get(self.ART_TYPES[self.tabs.currentIndex()][0], []):
                kind = self.ART_TYPES[self.tabs.currentIndex()][0]
                buttons = self.buttons[kind]
                index = buttons.index(obj)
                self._focused_result_index[kind] = index
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    obj.click()
                    obj.setFocus(Qt.PopupFocusReason)
                    return True
                if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                    if key == Qt.Key_Up and index < 4:
                        self.tabs.tabBar().setFocus(Qt.PopupFocusReason)
                        return True
                    columns = 4
                    delta = {
                        Qt.Key_Left: -1, Qt.Key_Right: 1,
                        Qt.Key_Up: -columns, Qt.Key_Down: columns,
                    }[key]
                    target = max(0, min(len(buttons) - 1, index + delta))
                    self._focus_artwork_result(target)
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        """Keep controller input inside the embedded artwork editor."""
        key = event.key()
        if key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            direction = -1 if key == Qt.Key_BracketLeft else 1
            index = (self.tabs.currentIndex() + direction) % len(self.ART_TYPES)
            self.tabs.setCurrentIndex(index)
            self._focus_artwork_result(0)
            event.accept()
            return
        if key in (Qt.Key_Escape, Qt.Key_Menu):
            self.reject()
            event.accept()
            return
        focused = QApplication.focusWidget()
        current_buttons = self.buttons.get(self.ART_TYPES[self.tabs.currentIndex()][0], [])
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if isinstance(focused, QPushButton) and focused in current_buttons:
                focused.click()
                event.accept()
                return
            if focused is self.tabs.tabBar() and current_buttons:
                current_buttons[0].setFocus(Qt.PopupFocusReason)
                event.accept()
                return
        if focused is self.tabs.tabBar() and key == Qt.Key_Down and current_buttons:
            current_buttons[0].setFocus(Qt.PopupFocusReason)
            event.accept()
            return
        super().keyPressEvent(event)

    def _choose(self, kind, choice):
        self.selected[kind] = choice
        for button in self.buttons.get(kind, []):
            button.setStyleSheet("QPushButton { border: 1px solid #3b2d5c; padding: 5px; } QPushButton:focus { border: 3px solid #c084fc; }")
        sender = self.sender()
        if sender:
            sender.setFocus()
            sender.setStyleSheet("QPushButton { border: 3px solid #c084fc; padding: 4px; }")
        if self._save_thread is not None and self._save_thread.isRunning():
            self.status.setText("Applying the previous artwork selection...")
            return
        if kind == "icon":
            home = self.parentWidget()
            if hasattr(home, "begin_artwork_change_lock"):
                home.begin_artwork_change_lock()
        self.status.setText(f"Applying {kind.upper()} artwork...")
        self._save_thread = _ArtworkSaveThread(kind, self.game, choice.get("url", ""), self)
        self._save_thread.saved.connect(self._artwork_saved)
        self._save_thread.failed.connect(self._artwork_save_failed)
        self._save_thread.start()

    def _artwork_saved(self, kind, path):
        self.artwork_saved.emit(kind, path)
        self.status.setText(f"{kind.upper()} artwork applied immediately.")

    def _artwork_save_failed(self, kind, message):
        self.status.setText(f"Could not apply {kind.upper()} artwork: {message}")
        if kind == "icon":
            home = self.parentWidget()
            if hasattr(home, "end_artwork_change_lock"):
                home.end_artwork_change_lock()


class HomeView(QWidget):
    game_launched = Signal(dict)
    game_install_requested = Signal(dict)
    open_search   = Signal()
    open_settings = Signal()
    quit_requested = Signal()
    library_changed = Signal()
    collections_changed = Signal(list)
    detail_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.games = []
        self.focused_game = None
        self._detail_game = None
        self._pending_tab_refresh = False
        self._detail_closing = False
        self._artwork_editor_open = False
        self._rows = []
        self._active_row = 0
        self._focus_zone = ZONE_ROWS          # which zone the controller is in
        self.current_accent = dominant_accent(None)
        self._btn_index  = 0                  # which button is highlighted in ZONE_BUTTONS
        self._focus_generation = 0
        self._collection_action_buttons = []
        self._collection_action_index = 0
        self._collection_toolbar_filter = _CollectionToolbarFilter(self)
        self._bulk_selection_mode = False
        self._selected_game_keys = set()
        self._bulk_selection_anchor_key = None
        self._all_games_grid = None
        self._collection_source_games = None
        self._platform_filter_value = "ALL"
        self._library_filter_value = "ALL"
        self._showing_recently_played = False
        self._desktop_refresh_generation = 0

        self.starfield = Starfield(self)
        self.starfield.lower()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Hero banner ────────────────────────────────────────────────────
        self.hero = HeroBanner()
        self.hero.width_dragged.connect(self._resize_hero_from_edge)
        self.hero.width_drag_finished.connect(self._save_hero_width)
        self.hero.setMinimumWidth(280)
        self.hero.setMaximumWidth(430)
        self._hero_orientation = "vertical"
        self._main_layout = main_layout

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        # Slight overlap visually joins the tilted hero artwork to the card rail.
        content_layout.setSpacing(-28)
        left_panel = QWidget()
        left_panel.setMinimumWidth(0)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        content_layout.addWidget(left_panel, 1)
        content_layout.addWidget(self.hero)
        self._content_layout = content_layout

        # ── Info bar (title + action buttons) ─────────────────────────────
        info_container = QWidget()
        self.info_container = info_container
        info_container.setFixedHeight(72)
        info_container.setStyleSheet("background-color: #0a0a0f;")
        info_layout = QHBoxLayout(info_container)
        info_layout.setContentsMargins(48, 8, 48, 8)

        left_info = QHBoxLayout()
        left_info.setSpacing(16)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #ffffff; letter-spacing: 2px;"
        )
        left_info.addWidget(self.title_label)

        self.btn_play = QPushButton("▶  PLAY")
        self.btn_play.setFixedHeight(32)
        self.btn_play.setFixedWidth(110)
        self.btn_play.setFocusPolicy(Qt.StrongFocus)
        self.btn_play.clicked.connect(self._launch_focused)
        self._apply_btn_style(self.btn_play, active=True)
        self.btn_play.hide()

        self.btn_fav = QPushButton("♡  FAV")
        self.btn_fav.setFixedHeight(32)
        self.btn_fav.setFixedWidth(100)
        self.btn_fav.setFocusPolicy(Qt.StrongFocus)
        self.btn_fav.clicked.connect(self._toggle_fav)
        self._apply_btn_style(self.btn_fav, active=False)
        self.btn_fav.hide()

        info_layout.addLayout(left_info)
        info_layout.addStretch()

        self.btn_settings = QPushButton("⚙  SETTINGS")
        self.btn_settings.setFixedHeight(32)
        self.btn_settings.setFixedWidth(120)
        self.btn_settings.setFocusPolicy(Qt.StrongFocus)
        self.btn_settings.clicked.connect(self.open_settings.emit)
        self._apply_btn_style(self.btn_settings, active=False)
        info_layout.addWidget(self.btn_settings, alignment=Qt.AlignVCenter)

        self.btn_quit = QPushButton("⏻  QUIT")
        self.btn_quit.setFixedHeight(32)
        self.btn_quit.setFixedWidth(90)
        self.btn_quit.setFocusPolicy(Qt.StrongFocus)
        self.btn_quit.clicked.connect(self.quit_requested.emit)
        self.btn_quit.setStyleSheet(
            "QPushButton { background: #12121a; color: #ef4444; font-weight: bold;"
            " font-size: 12px; border: 1px solid #7f1d1d; border-radius: 4px; }"
            "QPushButton:hover { background: #ef4444; color: white; border-color: #ef4444; }"
        )
        info_layout.addWidget(self.btn_quit, alignment=Qt.AlignVCenter)

        left_layout.addWidget(info_container)

        # All navigable buttons in order (for Left/Right in ZONE_BUTTONS)
        self.btn_settings.hide()
        self.btn_quit.hide()
        self._nav_buttons = []

        # Install key-event filter so Down/Up/Left/Right on any nav button
        # go to our zone logic instead of Qt's default focus traversal.
        self._btn_filter = _BtnZoneFilter(self)
        for btn in self._nav_buttons:
            btn.installEventFilter(self._btn_filter)
            btn.setCursor(Qt.PointingHandCursor)

        # ── Platform tabs ──────────────────────────────────────────────────
        self.platform_tab = PlatformTab()
        self.platform_tab.tab_changed.connect(self._on_tab_changed)
        self.platform_tab.collections_reordered.connect(self._collections_reordered)
        left_layout.addWidget(self.platform_tab)

        # Keep the filter surface compact: two aligned selectors, with their
        # options revealed only when opened.
        self.filter_bar = QWidget()
        filter_layout = QGridLayout(self.filter_bar)
        filter_layout.setContentsMargins(24, 12, 24, 12)
        filter_layout.setHorizontalSpacing(16)
        filter_layout.setVerticalSpacing(8)

        self.platform_filter = QPushButton()
        self.library_filter = QPushButton()
        self._platform_filter_menu = None
        self._library_filter_menu = None
        self.platform_filter.clicked.connect(lambda: self._show_filter_context("platform", self.platform_filter))
        self.library_filter.clicked.connect(lambda: self._show_filter_context("library", self.library_filter))
        self._style_select_button(self.platform_filter)
        self._style_select_button(self.library_filter)
        filter_layout.addWidget(self.platform_filter, 0, 0, 1, 2)
        filter_layout.addWidget(self.library_filter, 0, 2, 1, 2)
        for column in range(4):
            filter_layout.setColumnStretch(column, 1)

        # A separate floating toolbar keeps bulk actions close to the cards
        # without making the filter area carry unrelated controls.
        self.bulk_bar = QFrame(self)
        self.bulk_bar.setObjectName("bulkBar")
        self.bulk_bar.setStyleSheet(
            "QFrame#bulkBar { background: rgba(0, 0, 0, 204); "
            "border: 1px solid rgba(255, 255, 255, 35); border-radius: 12px; }"
        )
        bulk_layout = QHBoxLayout(self.bulk_bar)
        bulk_layout.setContentsMargins(14, 8, 14, 8)
        bulk_layout.setSpacing(12)

        self.bulk_button = QPushButton("BULK SELECT")
        self.bulk_button.clicked.connect(self._toggle_bulk_selection)
        self._style_filter_button(self.bulk_button)
        bulk_layout.addWidget(self.bulk_button)
        self.bulk_add_button = QPushButton("ADD SELECTED TO COLLECTION")
        self.bulk_add_button.clicked.connect(self._bulk_add_to_collection)
        self.bulk_add_button.hide()
        self._style_filter_button(self.bulk_add_button)
        bulk_layout.addWidget(self.bulk_add_button)
        self.bulk_count_label = QLabel("")
        self.bulk_count_label.setStyleSheet("color: #a78bfa; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        bulk_layout.addWidget(self.bulk_count_label)
        bulk_layout.addStretch()
        self.bulk_bar.hide()
        left_layout.addWidget(self.filter_bar)

        # ── Game rows scroll area ──────────────────────────────────────────
        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setMinimumWidth(0)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rows_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #0a0a0f; width: 6px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #7c3aed; border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.rows_scroll.setFocusPolicy(Qt.NoFocus)

        self.rows_container = QWidget()
        self.rows_container.setMinimumWidth(0)
        self.rows_container.setStyleSheet("background: transparent;")
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 40)
        self.rows_layout.setSpacing(10)
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.rows_scroll.setWidget(self.rows_container)
        self.rows_scroll.verticalScrollBar().valueChanged.connect(self._maybe_load_more)

        left_layout.addWidget(self.rows_scroll, 1)

        main_layout.addLayout(content_layout, 1)

        # ── Status bar ─────────────────────────────────────────────────────
        status_bar = QWidget(self)
        self.status_bar = status_bar
        status_bar.setFixedHeight(38)
        status_bar.setStyleSheet("background-color: #12121a; border-top: 1px solid #1a1a24;")
        sl = QHBoxLayout(status_bar)
        sl.setContentsMargins(20, 0, 20, 0)

        self.status_playing = QLabel("")
        self.status_playing.setStyleSheet("color: #c084fc; font-weight: bold; font-size: 12px;")

        self.status_section = QLabel("")
        self.status_section.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 12px;")
        self.status_section.setAlignment(Qt.AlignCenter)

        sl.addWidget(self.status_playing)
        sl.addStretch()
        status_bar.hide()
        sl.addWidget(self.status_section)
        sl.addStretch()
        # The old bottom section indicator is intentionally removed; navigation
        # is now handled by the sidebar and platform tabs.
        self._build_detail_overlay()
        self._build_artwork_change_lock()
        self.apply_hero_settings(
            config.settings.get("hero_orientation", "vertical"),
            config.settings.get("hero_width", 360),
            config.settings.get("hero_height", 260),
        )

    def apply_hero_settings(self, orientation="vertical", width=360, height=260):
        orientation = "horizontal" if orientation == "horizontal" else "vertical"
        width = max(240, min(640, int(width)))
        height = max(180, min(520, int(height)))
        if orientation == self._hero_orientation and getattr(self, "_hero_size", None) == (width, height):
            return
        self._hero_orientation = orientation
        self.hero.set_orientation(orientation)
        self._hero_size = (width, height)
        self._content_layout.removeWidget(self.hero)
        self._main_layout.removeWidget(self.hero)
        if orientation == "horizontal":
            self.hero.setMinimumWidth(0)
            self.hero.setMaximumWidth(16777215)
            self.hero.setFixedHeight(height)
            self.hero.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._main_layout.insertWidget(0, self.hero)
        else:
            self.hero.setMinimumWidth(240)
            self.hero.setMaximumWidth(width)
            self.hero.setFixedWidth(width)
            self.hero.setMinimumHeight(0)
            self.hero.setMaximumHeight(16777215)
            self.hero.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self._content_layout.addWidget(self.hero)
        self.hero.update()
        self._content_layout.activate()
        self.rows_scroll.updateGeometry()
        QTimer.singleShot(0, self._reflow_game_grids)

    def _reflow_game_grids(self):
        for row in self._rows:
            if hasattr(row, "_reflow"):
                row._reflow()

    def _resize_hero_from_edge(self, width):
        self.apply_hero_settings(self._hero_orientation, width, self._hero_size[1])

    def _save_hero_width(self, width):
        config.settings["hero_width"] = int(width)
        config.save_settings()

    def refresh_theme(self):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        accent = QColor(palette["ACCENT"])
        accent_rgba = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 128)"
        accent_hover_rgba = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 190)"
        self.info_container.setStyleSheet(f"background-color: {palette['BG']};")
        self.status_bar.setStyleSheet(
            f"background-color: {palette['SURFACE']}; border-top: 1px solid {palette['PANEL']};"
        )
        self.status_playing.setStyleSheet(f"color: {palette['ACCENT2']}; font-weight: bold; font-size: 12px;")
        self.status_section.setStyleSheet(f"color: {palette['TEXT_DIM']}; font-weight: bold; font-size: 12px;")
        self.detail_play.setStyleSheet(
            f"QPushButton {{ background: {palette['ACCENT']}; color: white; border: 1px solid {palette['ACCENT2']}; border-radius: 12px; font-size: 19px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['HIGHLIGHT']}; border: 2px solid white; }}"
        )
        self.detail_overlay.setStyleSheet(
            f"QFrame#gameDetailOverlay {{ background: rgba(16, 14, 27, 150); border: 1px solid {palette['ACCENT']}; border-radius: 18px; }}"
            f"QLabel {{ color: {palette['TEXT']}; }} QTextBrowser {{ background: transparent; color: {palette['TEXT']}; border: none; padding: 0; font-family: 'Inter', 'Noto Sans', 'Segoe UI'; font-size: 15px; }} QMenu::icon {{ width: 22px; height: 22px; }}"
        )
        self.detail_cover.setStyleSheet(
            "background: transparent; border: none;"
        )
        self.detail_description.setStyleSheet(
            f"QTextBrowser {{ background: rgba(0, 0, 0, 175); color: {palette['TEXT']}; "
            f"border: 1px solid rgba(255, 255, 255, 35); padding: 14px; "
            f"font-family: 'DejaVu Serif', serif; font-size: 15px; "
            f"selection-background-color: {palette['ACCENT']}; }}"
        )
        self.detail_meta.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        self.detail_screenshots.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.detail_actions.setStyleSheet(
            f"QFrame {{ background: rgba(0, 0, 0, 150); border: 1px solid {palette['ACCENT']}; border-radius: 12px; }}"
            f"QPushButton {{ background: {accent_rgba}; color: {palette['TEXT']}; border: none; border-radius: 8px; font-size: 20px; padding: 4px; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {accent_hover_rgba}; color: white; }}"
        )
        self.detail_close.setStyleSheet(
            f"QPushButton {{ background: {accent_rgba}; color: {palette['TEXT']}; border: none; border-radius: 8px; font-size: 20px; padding: 4px; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {accent_hover_rgba}; color: white; }}"
        )
        self.rows_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {palette['BG']}; width: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:vertical {{ background: {palette['ACCENT']}; border-radius: 3px; min-height: 30px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.platform_tab.update()
        self.hero.update()
        self.starfield.set_background_mode(config.settings.get("background_mode", "stars"))
        if self.focused_game:
            self.starfield.set_background_image(
                self.focused_game.get("hero_path") or self.focused_game.get("cover_path")
            )
        for row in self._rows:
            if hasattr(row, "refresh_theme"):
                row.refresh_theme()
            for card in getattr(row, "cards", []):
                card.inner.update()

    def resizeEvent(self, event):
        """Keep the side hero usable from compact windows to ultrawide screens."""
        super().resizeEvent(event)
        if hasattr(self, "starfield"):
            self.starfield.setGeometry(self.rect())
            self.starfield.lower()
        if hasattr(self, "artwork_change_lock"):
            self.artwork_change_lock.setGeometry(self.rect())
        if self.width() > 0:
            if self._hero_orientation == "vertical":
                configured = getattr(self, "_hero_size", (360, 260))[0]
                # Respect the configured pixel width until the window genuinely
                # becomes too narrow to fit the card rail beside it.
                panel_width = max(240, min(configured, self.width() - 320))
                self.hero.setFixedWidth(panel_width)
        if hasattr(self, "detail_overlay"):
            self.detail_scrim.setGeometry(self.rect())
            self.detail_overlay.setGeometry(self._detail_target_rect())
            self.detail_background.setGeometry(self.detail_overlay.rect())
            if self.detail_overlay.isVisible() and self._detail_game:
                cover_path = self._detail_game.get("cover_path", "")
                cover = QPixmap(cover_path) if cover_path else QPixmap()
                self._set_detail_cover(cover)
        if hasattr(self, "status_bar"):
            self.status_bar.setGeometry(0, max(0, self.height() - 38), self.width(), 38)
        if hasattr(self, "bulk_bar") and self.bulk_bar.isVisible():
            bar_width = min(760, max(320, self.width() - 80))
            bar_height = self.bulk_bar.sizeHint().height()
            self.bulk_bar.setGeometry(
                max(24, (self.width() - bar_width) // 2),
                max(24, self.height() - bar_height - 52),
                bar_width,
                bar_height,
            )
            self.bulk_bar.raise_()

    def _build_detail_overlay(self):
        self.detail_scrim = _DetailScrim(self)
        self.detail_scrim.clicked_outside.connect(self._close_game_details)
        self.detail_overlay = QFrame(self)
        self.detail_overlay.setObjectName("gameDetailOverlay")
        self.detail_overlay.setStyleSheet(
            "QFrame#gameDetailOverlay { background-color: rgba(16, 14, 27, 150); border: 1px solid #6d4bb5; border-radius: 18px; }"
            "QLabel { color: #e2e8f0; } QTextBrowser { background: transparent; color: #d8d0e8; border: none; padding: 0; font-family: 'Inter', 'Noto Sans', 'Segoe UI'; font-size: 15px; }"
        )
        self.detail_background = _DetailHeroBackdrop(self.detail_overlay)
        self._detail_backdrop_sizer = _DetailBackdropResizeFilter(
            self.detail_background, self
        )
        self.detail_overlay.installEventFilter(self._detail_backdrop_sizer)
        self.detail_background.lower()
        layout = QVBoxLayout(self.detail_overlay)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(10)
        self.detail_title = QLabel("GAME DETAILS")
        self.detail_title.setStyleSheet("font-size: 25px; font-weight: bold; letter-spacing: 1.5px; color: #ffffff;")
        header.addWidget(self.detail_title)
        header.addStretch()
        self.detail_close = _TintButton("", self.detail_overlay)
        self.detail_close.setIcon(_modal_icon("close"))
        self.detail_close.setIconSize(QSize(18, 18))
        self.detail_close.setFixedSize(40, 36)
        self.detail_close.setToolTip("Close game details")
        self.detail_close.setAccessibleName("Close game details")
        self.detail_close.setCursor(Qt.PointingHandCursor)
        self.detail_close.setStyleSheet(
            "QPushButton { background: rgba(124, 58, 237, 128); color: #e2e8f0; "
            "border: none; border-radius: 8px; font-size: 20px; padding: 4px; }"
            "QPushButton:hover, QPushButton:focus { background: rgba(124, 58, 237, 190); color: white; }"
        )
        self.detail_close.clicked.connect(self._close_game_details)
        header.addWidget(self.detail_close)
        layout.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(18)
        self.detail_cover = _CoverArtWidget()
        # The modal can shrink with wide hero artwork. Let the cover area
        # shrink with it too; its source image is scaled and clipped during
        # paint so it always stays inside the available frame.
        self.detail_cover.setMinimumSize(0, 0)
        self.detail_cover.setMaximumWidth(360)
        self.detail_cover.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.detail_cover.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.detail_cover.setStyleSheet("background: transparent; border: none;")
        stats = QFrame()
        stats.setStyleSheet("background: transparent; border: none;")
        stats_layout = QHBoxLayout(stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(10)
        self.detail_clock = QLabel()
        self.detail_clock.setFixedSize(48, 48)
        self.detail_clock.setPixmap(_modal_icon("clock").pixmap(42, 42))
        stats_layout.addWidget(self.detail_clock)
        self.detail_playtime = QLabel("TOTAL PLAYED\n0h 0m")
        self.detail_playtime.setStyleSheet("color: #e2e8f0; font-size: 13px; font-weight: bold; letter-spacing: 1px;")
        stats_layout.addWidget(self.detail_playtime)
        stats_layout.addStretch()
        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.detail_meta)
        self.detail_description = QTextBrowser()
        description_font = QFont("DejaVu Serif", 14)
        description_font.setStyleHint(QFont.Serif)
        self.detail_description.setFont(description_font)
        self.detail_description.setFrameShape(QFrame.NoFrame)
        self.detail_description.setMinimumHeight(0)
        self.detail_description.setStyleSheet(
            "QTextBrowser { background: rgba(0, 0, 0, 175); color: #f1f5f9; "
            "border: 1px solid rgba(255, 255, 255, 35); padding: 14px; "
            "font-family: 'DejaVu Serif', serif; font-size: 15px; "
            "selection-background-color: rgba(124, 58, 237, 190); }"
        )
        self.detail_description.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(self.detail_cover, 1)
        body.addWidget(self.detail_description, 2)
        self.detail_screenshots = QLabel("")
        self.detail_screenshots.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.detail_favorite = _TintButton("", self.detail_overlay)
        self.detail_favorite.setIcon(_modal_icon("heart"))
        self.detail_favorite.setIconSize(QSize(21, 21))
        self.detail_favorite.setFixedSize(44, 44)
        self.detail_favorite.setToolTip("Favorite / unfavorite game")
        self.detail_favorite.setAccessibleName("Favorite or unfavorite game")
        self.detail_favorite.setCursor(Qt.PointingHandCursor)
        self.detail_favorite.clicked.connect(self._toggle_detail_favorite)
        edit_icon_path = config.project_root / "assets" / "icons" / "menu" / "edit.svg"
        self.detail_artwork = _TintButton("", self.detail_overlay)
        if edit_icon_path.exists():
            self.detail_artwork.setIcon(QIcon(str(edit_icon_path)))
            self.detail_artwork.setIconSize(QSize(21, 21))
        self.detail_artwork.setFixedSize(44, 44)
        self.detail_artwork.setToolTip("Edit artwork from SteamGridDB")
        self.detail_artwork.setAccessibleName("Edit artwork")
        self.detail_artwork.clicked.connect(
            lambda: QTimer.singleShot(0, lambda: self._edit_game_artwork(self._detail_game))
        )
        self.detail_remove = _TintButton("", self.detail_overlay)
        self.detail_remove.setIcon(_modal_icon("trash"))
        self.detail_remove.setIconSize(QSize(21, 21))
        self.detail_remove.setFixedSize(44, 44)
        self.detail_remove.setToolTip("Remove file contents")
        self.detail_remove.setAccessibleName("Remove file contents")
        self.detail_remove.setCursor(Qt.PointingHandCursor)
        self.detail_remove.clicked.connect(self._confirm_remove_contents)
        self.detail_play = _TintButton("", self.detail_overlay)
        self.detail_play.setIcon(_modal_icon("play"))
        self.detail_play.setIconSize(QSize(22, 22))
        self.detail_play.setFixedSize(44, 44)
        self.detail_play.setToolTip("Play game")
        self.detail_play.setAccessibleName("Play game")
        self.detail_play.setCursor(Qt.PointingHandCursor)
        self.detail_play.clicked.connect(self._launch_focused)
        download_icon_path = config.project_root / "assets" / "icons" / "modal" / "download.svg"
        self.detail_install = _TintButton("", self.detail_overlay)
        if download_icon_path.exists():
            self.detail_install.setIcon(QIcon(str(download_icon_path)))
            self.detail_install.setIconSize(QSize(22, 22))
        self.detail_install.setFixedSize(44, 44)
        self.detail_install.setToolTip("Install game")
        self.detail_install.setAccessibleName("Install game")
        self.detail_install.setCursor(Qt.PointingHandCursor)
        self.detail_install.clicked.connect(self._install_focused)
        self._detail_filter = _DetailInputFilter(self)
        for control in (self.detail_close, self.detail_artwork, self.detail_favorite, self.detail_remove, self.detail_install, self.detail_play, self.detail_description):
            control.installEventFilter(self._detail_filter)
        self.detail_actions = QFrame(self.detail_overlay)
        self.detail_actions.setObjectName("detailActions")
        self.detail_actions.setStyleSheet(
            "QFrame#detailActions { background-color: rgba(0, 0, 0, 204); "
            "border: 1px solid rgba(192, 132, 252, 150); border-radius: 12px; }"
        )
        action_layout = QHBoxLayout(self.detail_actions)
        action_layout.setContentsMargins(6, 6, 6, 6)
        action_layout.setSpacing(2)
        action_layout.addWidget(self.detail_favorite)
        action_layout.addWidget(self.detail_artwork)
        action_layout.addWidget(self.detail_remove)
        action_layout.addWidget(self.detail_install)
        action_layout.addWidget(self.detail_play)
        layout.addLayout(body, 1)
        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addWidget(stats)
        footer.addStretch()
        footer.addWidget(self.detail_screenshots)
        footer.addWidget(self.detail_actions, 0, Qt.AlignRight | Qt.AlignBottom)
        layout.addLayout(footer)
        self.detail_overlay.hide()
        self.detail_scrim.hide()

    def _build_artwork_change_lock(self):
        self.artwork_change_lock = QFrame(self)
        self.artwork_change_lock.setObjectName("artworkChangeLock")
        self.artwork_change_lock.setFocusPolicy(Qt.StrongFocus)
        self.artwork_change_lock.setStyleSheet(
            "QFrame#artworkChangeLock { background: rgba(4, 4, 10, 225); "
            "border: 2px solid #7c3aed; border-radius: 14px; }"
            "QLabel { color: #c084fc; font-size: 22px; font-weight: bold; "
            "letter-spacing: 2px; }"
        )
        layout = QVBoxLayout(self.artwork_change_lock)
        layout.setContentsMargins(20, 20, 20, 20)
        label = QLabel("CHANGING ARTWORK...", self.artwork_change_lock)
        label.setAlignment(Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(label)
        layout.addStretch()
        self.artwork_change_lock.setGeometry(self.rect())
        self.artwork_change_lock.hide()

    def begin_artwork_change_lock(self):
        self.artwork_change_lock.setGeometry(self.rect())
        self.artwork_change_lock.show()
        self.artwork_change_lock.raise_()
        self.artwork_change_lock.setFocus(Qt.PopupFocusReason)

    def end_artwork_change_lock(self):
        if hasattr(self, "artwork_change_lock"):
            self.artwork_change_lock.hide()
            dialog = getattr(self, "_artwork_dialog", None)
            if dialog is not None and dialog.isVisible():
                dialog._focus_artwork_result()
            else:
                self._restore_focus()

    def _detail_target_rect(self):
        width = min(1180, max(320, self.width() - 64))
        # Keep a consistent modal frame across games. The active hero artwork
        # is zoomed and cropped by _DetailHeroBackdrop to fill this frame.
        height = min(760, max(240, self.height() - 64))
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def _close_game_details(self):
        if not self.detail_overlay.isVisible() or self._detail_closing:
            return
        self._detail_closing = True
        opening = getattr(self, "_detail_popup_animation", None)
        if opening and opening.state() == QAbstractAnimation.Running:
            opening.stop()
        detail_game = self._detail_game
        key = detail_game.get("key") if detail_game else None
        start_rect = self._detail_target_rect().adjusted(0, 42, 0, -42)
        popup = QParallelAnimationGroup(self)
        geometry = QPropertyAnimation(self.detail_overlay, b"geometry", popup)
        geometry.setDuration(200)
        geometry.setStartValue(self.detail_overlay.geometry())
        geometry.setEndValue(start_rect)
        geometry.setEasingCurve(QEasingCurve.InCubic)
        popup.addAnimation(geometry)
        popup.finished.connect(lambda: self._finish_game_details_close(key))
        self._detail_close_animation = popup
        popup.start()

    def _finish_game_details_close(self, key):
        self.detail_overlay.hide()
        self.detail_scrim.hide()
        self.detail_overlay.setGraphicsEffect(None)
        self.detail_scrim.setGraphicsEffect(None)
        self._detail_game = None
        self._detail_closing = False
        window = self.window()
        if window is not None and hasattr(window, "sidebar"):
            window.sidebar.setEnabled(True)
        if self._pending_tab_refresh:
            self._pending_tab_refresh = False
            self._refresh_current_tab()
        restored = False
        for row in self._rows:
            for index, card in enumerate(getattr(row, "cards", [])):
                if key and card.game_dict.get("key") == key:
                    QTimer.singleShot(0, lambda r=row, i=index: r.focus_card(i))
                    restored = True
                    break
            if restored:
                break
        if not restored:
            self.setFocus()
        self.detail_closed.emit()

    def _toggle_detail_favorite(self):
        game = self._detail_game
        if not game:
            return
        key = game.get("key", "")
        toggle_favorite(key)
        self._apply_favorite_state(game, is_favorite(key))

    def _apply_favorite_state(self, game_dict, favorite):
        key = game_dict.get("key", "")
        for game in self.games:
            if game.get("key") == key:
                game["is_favorite"] = favorite
        game_dict["is_favorite"] = favorite
        if self.focused_game and self.focused_game.get("key") == key:
            self.focused_game["is_favorite"] = favorite
        self.detail_favorite.setIcon(_modal_icon("heart-filled" if favorite else "heart"))
        self.btn_fav.setText("♥  UNFAVORITE" if favorite else "♡  FAVORITE")
        for row in self._rows:
            for card in getattr(row, "cards", []):
                if card.game_dict.get("key") == key:
                    card.game_dict["is_favorite"] = favorite
                    card.inner.update()
        if self.detail_overlay.isVisible():
            # Rebuilding the underlying tab moves focus to its first card. Keep
            # the modal's game as the action target and refresh the tab on close.
            self._pending_tab_refresh = True
        else:
            self._refresh_current_tab()

    # ── Button styling helpers ─────────────────────────────────────────────

    def _apply_btn_style(self, btn: QPushButton, active: bool):
        """Apply normal vs controller-highlighted style to an action button."""
        # btn_quit may not exist yet during __init__ — guard with getattr
        if btn is getattr(self, 'btn_quit', None):
            return  # quit has its own fixed style
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        accent = QColor(self.current_accent)
        accent_name = accent.name()
        accent_highlight = accent.lighter(135).name()
        if active:
            btn.setStyleSheet(
                f"QPushButton {{ background: {accent_name}; color: #fff; font-weight: bold;"
                f" font-size: 13px; border: none; border-radius: 4px; outline: none; }}"
                f"QPushButton:hover {{ background: {accent_highlight}; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT_DIM']}; font-weight: bold;"
                f" font-size: 12px; border: 1px solid #2a2a38; border-radius: 4px; outline: none; }}"
                f"QPushButton:hover {{ border-color: {accent_name}; color: #e2e8f0; }}"
            )

    def _highlight_button(self, index):
        """Visually highlight one button in the action bar via glow effect."""
        for i, btn in enumerate(self._nav_buttons):
            if btn is self.btn_quit:
                # Highlight quit with a red glow instead
                continue
            if i == index:
                self._apply_btn_style(btn, active=True)
            else:
                self._apply_btn_style(btn, active=False)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_games(self, games_list):
        # Keep the UI safe even when older cached/imported data contains
        # Steam runtimes, Proton, or owned-but-not-installed Steam entries.
        self.games = [game for game in games_list if should_show_game(game)]
        current_platform = self._platform_filter_value
        platforms = ["ALL"] + sorted({str(g.get("platform", "")).upper() for g in self.games if g.get("platform")})
        if current_platform not in platforms:
            current_platform = "ALL"
            self._platform_filter_value = current_platform
        self._configure_filter_menu(
            self.platform_filter,
            self._platform_filter_menu,
            [("ALL PLATFORMS", "ALL")] + [(platform, platform) for platform in platforms[1:]],
            "platform",
        )
        self._configure_filter_menu(
            self.library_filter,
            self._library_filter_menu,
            [("ALL GAMES", "ALL"), ("INSTALLED ONLY", "INSTALLED"),
             ("FAVORITES ONLY", "FAVORITES")],
            "library",
        )
        platforms = {g.get("platform") for g in self.games if str(g.get("platform", "")).casefold() not in ("switch", "pc")}
        collections = userdata.get_collections()
        self.platform_tab.set_platforms(platforms, collections)
        self.collections_changed.emit(list(collections))
        self._build_home_tab()

    def _library_filter_changed(self):
        if self.platform_tab.current_value() == "HOME":
            show_recently_played = (
                self._platform_filter_value == "ALL"
                and self._library_filter_value == "ALL"
            )
            if show_recently_played != self._showing_recently_played:
                self._build_home_tab()
                return
            # The filter only changes the ALL GAMES grid. Reuse the existing
            # HOME rows instead of tearing down and recreating every widget.
            if self._all_games_grid is not None:
                self._all_games_grid.set_games(self._filtered_all_games())
                self._all_games_grid.set_selection_mode(self._bulk_selection_mode)
                for card in self._all_games_grid.cards:
                    card.set_selected(card.game_dict.get("key", "") in self._selected_game_keys)
                self._all_games_grid.updateGeometry()
            else:
                self._build_home_tab()
        elif self.platform_tab.current_value().startswith("collection:"):
            # Collections use the same filter controls as HOME, but always
            # apply them to the active collection's games only.
            self._build_collection_tab(self.platform_tab.current_value().split(":", 1)[1])

    def _style_filter_button(self, button, active=False):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        color = palette["ACCENT2"] if active else palette["TEXT_DIM"]
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button.setMinimumHeight(30)
        button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 24)
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color}; border: none; "
            "padding: 4px 2px; font-size: 12px; font-weight: bold; letter-spacing: 1px; }"
            f"QPushButton:hover, QPushButton:focus {{ color: {palette['TEXT']}; background: transparent; }}"
        )

    def _style_select_button(self, button):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(34)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setStyleSheet(
            f"QPushButton {{ background: rgba(0, 0, 0, 70); color: {palette['TEXT']}; "
            f"border: 1px solid rgba(255, 255, 255, 35); border-radius: 7px; "
            "padding: 6px 32px 6px 12px; text-align: center; font-size: 12px; font-weight: bold; letter-spacing: 1px; }"
            f"QPushButton:hover, QPushButton:focus {{ border-color: {palette['ACCENT2']}; color: white; }}"
            "QPushButton::menu-indicator { image: none; width: 0px; }"
        )

    def _configure_filter_menu(self, button, menu, options, kind):
        button._filter_options = list(options)
        button._filter_kind = kind
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self._update_filter_button_labels()

    def _show_filter_context(self, kind, button):
        old_menu = getattr(self, "_in_app_context_menu", None)
        if old_menu is not None and shiboken6.isValid(old_menu):
            old_menu.close_menu()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        menu = _InAppContextMenu(self, palette, width=270)
        self._in_app_context_menu = menu
        menu.add_label("SELECT FILTER")
        for label, value in getattr(button, "_filter_options", []):
            menu.add_action(label, lambda checked=False, v=value: (
                menu.close_menu(), self._set_filter_value(kind, v)
            ))
        menu.open_at(button.mapToGlobal(QPoint(button.width() + 8, 0)))

    def _update_filter_button_labels(self):
        platform_label = next(
            (label for label, value in getattr(self.platform_filter, "_filter_options", [])
             if value == self._platform_filter_value),
            self._platform_filter_value,
        )
        library_labels = {
            "ALL": "ALL GAMES", "INSTALLED": "INSTALLED ONLY",
            "FAVORITES": "FAVORITES ONLY",
        }
        self.platform_filter.setText(f"PLATFORM  ·  {platform_label}")
        self.library_filter.setText(f"LIBRARY  ·  {library_labels.get(self._library_filter_value, self._library_filter_value)}")

    def _set_filter_value(self, kind, value):
        sound_manager.play("ui_toggle")
        if kind == "platform":
            self._platform_filter_value = value
        else:
            self._library_filter_value = value
        self._update_filter_button_labels()
        self._library_filter_changed()

    def _filtered_all_games(self):
        platform = self._platform_filter_value
        state = self._library_filter_value
        result = []
        for game in self.games:
            if platform != "ALL" and str(game.get("platform", "")).upper() != platform:
                continue
            installed = game_is_installed(game)
            if state == "INSTALLED" and not installed:
                continue
            if state == "FAVORITES" and not game.get("is_favorite"):
                continue
            result.append(game)
        return result

    def _filtered_collection_games(self):
        """Return only games from the active collection matching the filters."""
        source = self._collection_source_games or []
        platform = self._platform_filter_value
        state = self._library_filter_value
        result = []
        for game in source:
            if platform != "ALL" and str(game.get("platform", "")).upper() != platform:
                continue
            installed = game_is_installed(game)
            if state == "INSTALLED" and not installed:
                continue
            if state == "FAVORITES" and not game.get("is_favorite"):
                continue
            result.append(game)
        return result

    def _toggle_bulk_selection(self):
        self._bulk_selection_mode = not self._bulk_selection_mode
        if not self._bulk_selection_mode:
            self._selected_game_keys.clear()
            self._bulk_selection_anchor_key = None
        self.bulk_button.setText("DONE SELECTING" if self._bulk_selection_mode else "BULK SELECT")
        self._style_filter_button(self.bulk_button)
        self.bulk_add_button.setVisible(self._bulk_selection_mode)
        self.bulk_bar.setVisible(self._bulk_selection_mode)
        self._update_bulk_count()
        self._build_home_tab()

    def _update_bulk_count(self):
        count = len(self._selected_game_keys)
        self.bulk_count_label.setText(f"{count} SELECTED" if self._bulk_selection_mode else "")
        self.bulk_add_button.setEnabled(count > 0)

    def _all_grid_game_selected(self, game):
        if not self._bulk_selection_mode:
            self._show_game_details(game)
            return
        # Selection mode is handled by _all_grid_selection_requested so the
        # keyboard modifiers are available here.

    def _all_grid_selection_requested(self, game, modifiers):
        if not self._bulk_selection_mode:
            return
        key = game.get("key", "")
        keys = [item.get("key", "") for item in self._all_games_grid.games]
        index = keys.index(key) if key in keys else -1
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        if shift and self._bulk_selection_anchor_key in keys and index >= 0:
            start = keys.index(self._bulk_selection_anchor_key)
            lo, hi = sorted((start, index))
            self._selected_game_keys.update(keys[lo:hi + 1])
        elif ctrl:
            if key in self._selected_game_keys:
                self._selected_game_keys.remove(key)
            else:
                self._selected_game_keys.add(key)
        else:
            self._selected_game_keys = {key}
        self._bulk_selection_anchor_key = key
        if self._all_games_grid:
            for card in self._all_games_grid.cards:
                if card.game_dict.get("key") == key:
                    card.set_selected(key in self._selected_game_keys)
                elif card.game_dict.get("key") in self._selected_game_keys:
                    card.set_selected(True)
                else:
                    card.set_selected(False)
        self._update_bulk_count()

    def _bulk_add_to_collection(self):
        selected = {g.get("key") for g in self.games if g.get("key") in self._selected_game_keys}
        if not selected:
            return

        def create_collection(name):
            name = userdata.create_collection(name.strip())
            if not name:
                show_message(self, "Invalid Collection", "Choose a non-empty collection name other than HOME.")
                return
            for key in selected:
                userdata.add_to_collection(name, key)
            self._selected_game_keys.clear()
            self._bulk_selection_anchor_key = None
            self._bulk_selection_mode = False
            self.bulk_button.setText("BULK SELECT")
            self.bulk_add_button.hide()
            self.bulk_bar.hide()
            self._update_bulk_count()
            self._sync_collection_tabs()
            self._build_home_tab()

        self._open_collection_name_dialog(on_accept=create_collection)

    def update_card_art(self, game_key, cover_path, hero_path, logo_path, icon_path=None):
        HeroBanner.invalidate_artwork(cover_path, hero_path, logo_path)
        for g in self.games:
            if g.get("key") == game_key:
                g["cover_path"] = cover_path
                g["hero_path"] = hero_path
                g["logo_path"] = logo_path
                if icon_path is not None:
                    g["icon_path"] = icon_path
                break
        if self.focused_game and self.focused_game.get("key") == game_key:
            self.focused_game["cover_path"] = cover_path
            self.focused_game["hero_path"] = hero_path
            self.focused_game["logo_path"] = logo_path
            if icon_path is not None:
                self.focused_game["icon_path"] = icon_path
            self.hero.set_game(self.focused_game, force_artwork=True)
            self.starfield.set_background_image(hero_path or cover_path)
        for row in self._rows:
            row.update_card_cover(game_key, cover_path)

    def set_now_playing(self, game_dict_or_none, play_time_str=None):
        if game_dict_or_none:
            self.status_bar.setGeometry(0, max(0, self.height() - 38), self.width(), 38)
            self.status_bar.show()
            self.status_bar.raise_()
            title = game_dict_or_none.get("title", "")
            if play_time_str:
                self.status_playing.setText(f"NOW PLAYING: {title} — {play_time_str}")
            else:
                self.status_playing.setText(f"NOW PLAYING: {title}")
            key = game_dict_or_none.get("key")
            for game in self.games:
                if game.get("key") == key:
                    game["is_playing"] = True
            for row in self._rows:
                for game in getattr(row, "games", []):
                    if game.get("key") == key:
                        game["is_playing"] = True
                for card in getattr(row, "cards", []):
                    if card.game_dict.get("key") == key:
                        card.set_playing(True)
        else:
            self.status_bar.hide()
            self.status_playing.setText("")
            for row in self._rows:
                for card in getattr(row, "cards", []):
                    if card.game_dict.get('is_playing'):
                        card.set_playing(False)
                for game in getattr(row, "games", []):
                    game["is_playing"] = False
            for game in self.games:
                game["is_playing"] = False

    def set_section_label(self, sections, current_index):
        # Section navigation now lives in the auto-hide sidebar and platform
        # tabs; the former bottom indicator was removed from the layout.
        return

    # ── Row management ─────────────────────────────────────────────────────

    def _build_home_tab(self):
        self._collection_source_games = None
        self.filter_bar.show()
        self.bulk_bar.setVisible(self._bulk_selection_mode)
        self._clear_rows()
        from core.userdata import get_recently_played, get_favorites_keys
        rp_keys = [r["key"] for r in get_recently_played()]
        rp_games = [g for g in self.games if g.get("key") in rp_keys]
        show_recently_played = (
            self._platform_filter_value == "ALL"
            and self._library_filter_value == "ALL"
        )
        self._showing_recently_played = bool(rp_games and show_recently_played)
        if rp_games and show_recently_played:
            self._add_row("RECENTLY PLAYED", rp_games)

        fav_keys = get_favorites_keys()
        fav_games = [g for g in self.games if g.get("key") in fav_keys]
        if fav_games:
            self._add_row("FAVORITES", fav_games)

        self._add_grid("ALL GAMES", self._filtered_all_games())
        self._focus_zone = ZONE_ROWS
        self._focus_row(0, card_index=0)
        self._finish_rows_rebuild()

    def _build_platform_tab(self, platform):
        self._collection_source_games = None
        self.filter_bar.hide()
        self.bulk_bar.hide()
        self._clear_rows()
        p_games = [g for g in self.games if g.get("platform", "").upper() == platform]
        # Platform tabs use a dedicated filtered rail. The main HOME view
        # remains the responsive grid, while this path avoids rebuilding the
        # large grid widget when switching categories (especially Switch).
        self._add_row(f"ALL {platform} GAMES", p_games)
        self._focus_zone = ZONE_ROWS
        self._focus_row(0, card_index=0)
        self._finish_rows_rebuild()

    def _build_collection_tab(self, name):
        self.filter_bar.show()
        self.bulk_bar.hide()
        self._clear_rows()
        self._collection_action_buttons = []
        collection_keys = userdata.get_collections().get(name, [])
        games_by_key = {g.get("key"): g for g in self.games if g.get("key")}
        # Keep the collection's own order, while using the exact same GameGrid
        # and GameCard renderer as HOME (cover art, platform badge, favorites,
        # playtime, focus treatment, and context actions).
        collection_games = [games_by_key[key] for key in collection_keys if key in games_by_key]
        self._collection_source_games = collection_games
        collection_platforms = sorted({
            str(game.get("platform", "")).upper()
            for game in collection_games
            if game.get("platform")
        })
        if self._platform_filter_value not in ["ALL", *collection_platforms]:
            self._platform_filter_value = "ALL"
        self._configure_filter_menu(
            self.platform_filter,
            self._platform_filter_menu,
            [("ALL PLATFORMS", "ALL")] + [(platform, platform) for platform in collection_platforms],
            "platform",
        )
        self._configure_filter_menu(
            self.library_filter,
            self._library_filter_menu,
            [("ALL GAMES", "ALL"), ("INSTALLED ONLY", "INSTALLED"),
             ("FAVORITES ONLY", "FAVORITES")],
            "library",
        )
        collection_games = self._filtered_collection_games()
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(24, 8, 24, 0)
        heading = QLabel(f"{name.upper()}  •  {len(collection_games)} GAMES")
        heading.setStyleSheet("font-size: 18px; font-weight: bold; letter-spacing: 2px; color: #e2e8f0;")
        toolbar_layout.addWidget(heading)
        toolbar_layout.addStretch()
        current_view = userdata.get_collection_view(name)
        toggle = QPushButton()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        toggle.clicked.connect(lambda: self._toggle_collection_view(name))
        edit = QPushButton()
        remove = QPushButton()
        icon_dir = config.project_root / "assets" / "icons" / "menu"
        edit.setIcon(QIcon(str(icon_dir / "edit.svg")))
        remove.setIcon(QIcon(str(icon_dir / "remove.svg")))
        toggle.setIcon(QIcon(str(icon_dir / ("list.svg" if current_view == "grid" else "grid.svg"))))
        for button, tooltip in (
            (edit, "Rename collection"),
            (remove, "Delete collection"),
            (toggle, "Switch to list view" if current_view == "grid" else "Switch to grid view"),
        ):
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setIconSize(QSize(20, 20))
        action_strip = QFrame()
        action_strip.setObjectName("collectionActions")
        action_layout = QHBoxLayout(action_strip)
        action_layout.setContentsMargins(3, 3, 3, 3)
        action_layout.setSpacing(3)
        action_strip.setStyleSheet(
            f"QFrame#collectionActions {{ background: rgba(0, 0, 0, 128); border: 1px solid {palette['ACCENT']}; border-radius: 10px; }}"
        )
        for button in (edit, remove, toggle):
            button.setFocusPolicy(Qt.StrongFocus)
            button.setFixedSize(48, 38)
            button.setStyleSheet(
                f"QPushButton {{ background: rgba(0, 0, 0, 128); color: {palette['TEXT']}; border: none; border-radius: 7px; padding: 6px; }}"
                f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
            )
        edit.clicked.connect(lambda: self._rename_collection(name))
        remove.clicked.connect(lambda: self._delete_collection(name))
        self._collection_action_buttons = [edit, remove, toggle]
        for button in self._collection_action_buttons:
            button.installEventFilter(self._collection_toolbar_filter)
        action_layout.addWidget(edit)
        action_layout.addWidget(remove)
        action_layout.addWidget(toggle)
        toolbar_layout.addWidget(action_strip)
        self.rows_layout.addWidget(toolbar)
        if current_view == "list":
            game_list = GameList(collection_games)
            game_list.game_focused.connect(self._on_game_focused)
            game_list.game_selected.connect(self._show_game_details)
            game_list.context_requested.connect(self._show_game_context)
            game_list.navigate_up.connect(lambda: self._on_navigate_up(game_list))
            game_list.navigate_down.connect(lambda: self._move_row(1, game_list))
            self.rows_layout.addWidget(game_list)
            self._rows.append(game_list)
        else:
            self._add_grid(name.upper(), collection_games)
            # The toolbar already contains the collection name and total, so
            # avoid repeating the GameGrid's own title/count heading.
            self._rows[-1].heading.hide()
        self._focus_zone = ZONE_ROWS
        self._focus_row(0, card_index=0)
        self._finish_rows_rebuild()

    def _toggle_collection_view(self, name):
        sound_manager.play("ui_toggle")
        current = userdata.get_collection_view(name)
        userdata.set_collection_view(name, "list" if current == "grid" else "grid")
        self._build_collection_tab(name)

    def _rename_collection(self, old_name):

        def rename_collection(new_name):
            renamed = userdata.rename_collection(old_name, new_name.strip())
            if not renamed:
                show_message(
                    self,
                    "Unable to Rename Collection",
                    "Choose a non-empty name other than HOME and avoid duplicate names.",
                )
                return
            self._sync_collection_tabs()
            target = f"collection:{renamed}"
            if target in self.platform_tab.tab_values:
                self.platform_tab.set_current_tab(self.platform_tab.tab_values.index(target))

        self._open_collection_name_dialog(old_name, rename_collection)

    def _delete_collection(self, name):
        if not confirm_message(
            self,
            "Delete Collection",
            f'Delete the collection "{name}"? The games themselves will not be deleted.',
        ):
            return
        # Leave the collection before rebuilding its tab list. Otherwise the
        # tab widget can already be on index 0 while HomeView still displays
        # the deleted collection.
        self.platform_tab.set_current_tab(0)
        userdata.delete_collection(name)
        self._sync_collection_tabs()

    def _clear_rows(self):
        # Invalidate delayed focus callbacks targeting rows that are being replaced.
        self._focus_generation += 1
        self._collection_action_buttons = []
        self.rows_container.setUpdatesEnabled(False)
        self._rows.clear()
        self._all_games_grid = None
        self._active_row = 0
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _finish_rows_rebuild(self):
        self.rows_container.setUpdatesEnabled(True)
        self.rows_container.update()

    def _add_row(self, title, games):
        row = GameRow(title)
        row.set_games(games)
        row.game_focused.connect(self._on_game_focused)
        row.game_selected.connect(self._show_game_details)
        row.game_favorite_toggled.connect(self._on_card_favorite_toggled)
        row.game_play_requested.connect(self._launch_game)
        row.game_install_requested.connect(self.game_install_requested.emit)
        row.context_requested.connect(self._show_game_context)
        row.navigate_up.connect(lambda r=row: self._on_navigate_up(r))
        row.navigate_down.connect(lambda r=row: self._move_row(1, r))
        self.rows_layout.addWidget(row)
        self._rows.append(row)

    def _add_grid(self, title, games):
        grid = GameGrid(title)
        grid.set_games(games)
        grid.game_focused.connect(self._on_game_focused)
        if title == "ALL GAMES":
            self._all_games_grid = grid
            grid.set_selection_mode(self._bulk_selection_mode)
            for card in grid.cards:
                card.set_selected(card.game_dict.get("key", "") in self._selected_game_keys)
            grid.game_selected.connect(self._all_grid_game_selected)
            grid.selection_requested.connect(self._all_grid_selection_requested)
        else:
            grid.game_selected.connect(self._show_game_details)
        grid.game_favorite_toggled.connect(self._on_card_favorite_toggled)
        grid.game_play_requested.connect(self._launch_game)
        grid.game_install_requested.connect(self.game_install_requested.emit)
        grid.context_requested.connect(self._show_game_context)
        grid.navigate_up.connect(lambda: self._on_navigate_up(grid))
        grid.navigate_down.connect(lambda: self._move_row(1, grid))
        self.rows_layout.addWidget(grid)
        self._rows.append(grid)

    def _focus_row(self, row_index, card_index=None):
        if not self._rows:
            return
        row_index = max(0, min(row_index, len(self._rows) - 1))
        self._active_row = row_index
        row = self._rows[row_index]
        ci = card_index if card_index is not None else row.focused_index
        generation = self._focus_generation
        QTimer.singleShot(80, lambda: self._do_focus_row(row, ci, generation))

    def _do_focus_row(self, row, card_index, generation=None):
        """Actually move focus — called after layout settles."""
        if generation is not None and generation != self._focus_generation:
            return
        if not shiboken6.isValid(row):
            return
        viewport = self.rows_scroll.viewport()
        top_left = row.mapTo(viewport, QPoint(0, 0))
        row_rect = QRect(top_left, row.size())
        if viewport.rect().contains(row_rect):
            row.focus_card(card_index)
            return
        bar = self.rows_scroll.verticalScrollBar()
        # A grid row can be taller than the viewport. Align its top rather
        # than scrolling all the way down to its bottom before focusing it.
        if row.height() > viewport.height() or row_rect.top() < 0:
            target = bar.value() + row_rect.top() - 12
        else:
            target = bar.value() + row_rect.bottom() - viewport.height() + 12
        target = int(max(0, min(target, bar.maximum())))
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        animation.setStartValue(int(bar.value()))
        animation.setEndValue(target)
        def finish_focus():
            bar.setValue(int(target))
            if generation is None or generation == self._focus_generation:
                row.focus_card(card_index)
        animation.finished.connect(finish_focus)
        self._vertical_focus_animation = animation
        animation.start()

    def _on_navigate_up(self, from_row):
        """Up from a card row: go to previous row, or to the action buttons if at top."""
        if from_row in self._rows:
            idx = self._rows.index(from_row)
        else:
            idx = self._active_row

        if idx > 0:
            # Move to previous row
            self._focus_row(idx - 1)
        else:
            # Already at top row → enter ZONE_BUTTONS
            if self._collection_action_buttons:
                self._enter_collection_toolbar()
            else:
                self._enter_buttons_zone()

    def _move_row(self, direction, from_row):
        if from_row in self._rows:
            idx = self._rows.index(from_row)
        else:
            idx = self._active_row
        self._focus_row(idx + direction)

    # ── Button zone navigation ─────────────────────────────────────────────

    def _enter_buttons_zone(self):
        """Switch focus to the action button bar."""
        if not self._nav_buttons:
            window = self.window()
            sidebar = getattr(window, "sidebar", None)
            nav_home = getattr(sidebar, "nav_home", None)
            if sidebar and nav_home:
                sidebar.set_expanded(True)
                nav_home.setFocus()
            return
        self._focus_zone = ZONE_BUTTONS
        self._btn_index = 0
        self._highlight_button(self._btn_index)
        sound_manager.play("navigate")
        self._nav_buttons[self._btn_index].setFocus()

    def _leave_buttons_zone(self):
        """Switch focus back to the game rows."""
        self._focus_zone = ZONE_ROWS
        # Reset all button highlights
        for btn in self._nav_buttons:
            if btn is not self.btn_quit:
                self._apply_btn_style(btn, active=False)
        if self.btn_play.isVisible():
            self._apply_btn_style(self.btn_play, active=True)
        self._focus_row(0, card_index=self._rows[0].focused_index if self._rows else 0)

    def _enter_collection_toolbar(self):
        if not self._collection_action_buttons:
            return
        self._collection_action_index = 0
        self._collection_action_buttons[0].setFocus()

    def controller_enter_collection_toolbar(self):
        """Enter collection actions when the card's parent misses Up propagation."""
        if not self._collection_action_buttons or not self._rows:
            return False
        focused = QApplication.focusWidget()
        first_row = self._rows[0]
        if focused is not first_row and not first_row.isAncestorOf(focused):
            return False
        self._enter_collection_toolbar()
        return True

    def _leave_collection_toolbar(self):
        self._focus_row(0, card_index=self._rows[0].focused_index if self._rows else 0)

    def _collection_toolbar_key(self, button, event):
        if button not in self._collection_action_buttons:
            return False
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Right):
            direction = -1 if key == Qt.Key_Left else 1
            self._collection_action_index = max(
                0,
                min(len(self._collection_action_buttons) - 1,
                    self._collection_action_index + direction),
            )
            self._collection_action_buttons[self._collection_action_index].setFocus()
            sound_manager.play("navigate")
            return True
        if key == Qt.Key_Down:
            self._leave_collection_toolbar()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            button.click()
            return True
        return False

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_tab_changed(self, tab_name):
        sound_manager.play("ui_toggle")
        if tab_name == "HOME":
            self._build_home_tab()
        elif tab_name.startswith("collection:"):
            self._build_collection_tab(tab_name.split(":", 1)[1])
        else:
            self._build_platform_tab(tab_name)

    def _collections_reordered(self, names):
        userdata.reorder_collections(names)
        platforms = {
            g.get("platform") for g in self.games
            if str(g.get("platform", "")).casefold() not in ("switch", "pc")
        }
        self.platform_tab.set_platforms(platforms, userdata.get_collections())
        self.collections_changed.emit(list(userdata.get_collections()))

    def _on_game_focused(self, game_dict):
        # Focus can be reported twice by a controller (for example when a
        # d-pad and stick event arrive together). Avoid rebuilding the hero,
        # backdrop, and styles when the selected game did not change.
        if self.focused_game is game_dict or (
            self.focused_game and self.focused_game.get("key") == game_dict.get("key")
        ):
            return
        sound_manager.play("navigate")
        self.focused_game = game_dict
        self.current_accent = dominant_accent(
            game_dict.get("hero_path") or game_dict.get("cover_path")
        )
        self.starfield.set_accent(self.current_accent)
        for button in getattr(self, "_nav_buttons", []):
            self._apply_btn_style(button, button.hasFocus())
        self.starfield.set_background_image(
            game_dict.get("hero_path") or game_dict.get("cover_path")
        )
        self.title_label.setText(game_dict.get("title", "").upper())
        self.hero.set_game(game_dict)

    def _show_game_context_legacy(self, game_dict):
        self._on_game_focused(game_dict)
        menu = _ControllerContextMenu(self.window())
        menu.setFocusPolicy(Qt.StrongFocus)
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        menu.setStyleSheet(
            f"QMenu {{ background: {palette['PANEL']}; color: {palette['TEXT']}; border: 1px solid {palette['ACCENT']}; padding: 6px; }}"
            "QMenu::item { padding: 10px 28px 10px 14px; border-radius: 4px; }"
            "QMenu::icon { width: 22px; height: 22px; }"
            f"QMenu::item:selected {{ background: {palette['ACCENT']}; color: white; }}"
        )
        def menu_icon(name):
            path = config.project_root / "assets" / "icons" / "menu" / f"{name}.svg"
            return QIcon(str(path)) if path.exists() else QIcon()
        favorite = menu.addAction(
            _modal_icon("heart-filled" if game_dict.get("is_favorite") else "heart"),
            "REMOVE FROM FAVORITES" if game_dict.get("is_favorite") else "ADD TO FAVORITES",
        )
        edit_artwork = menu.addAction(menu_icon("edit"), "EDIT ARTWORK")
        edit_artwork_requested = [False]
        edit_artwork.triggered.connect(lambda: (edit_artwork_requested.__setitem__(0, True), menu.close()))
        collection_menu = _ControllerContextMenu(self.window())
        collection_menu.setIcon(menu_icon("folder"))
        collection_menu.setTitle("MOVE TO COLLECTION")
        menu.addMenu(collection_menu)
        collection_menu.setFocusPolicy(Qt.StrongFocus)
        collections = userdata.get_collections()
        new_collection = collection_menu.addAction(
            menu_icon("plus"),
            "NEW COLLECTION...",
        )
        # Defer the actual dialog until menu.exec() has returned. Starting a
        # second nested modal loop directly from a QMenu action can leave Qt
        # with two competing popup owners and freeze/crash the app.
        open_new_collection = [False]
        def request_new_collection():
            open_new_collection[0] = True
            menu.close()
        new_collection.triggered.connect(request_new_collection)
        collection_menu.aboutToShow.connect(lambda: collection_menu.setActiveAction(new_collection))
        if collections:
            collection_menu.addSeparator()
            current_value = self.platform_tab.current_value()
            current_collection = current_value.split(":", 1)[1] if current_value.startswith("collection:") else None
            for name in collections:
                action = collection_menu.addAction(
                    menu_icon("folder"), name
                )
                action.setCheckable(True)
                action.setChecked(game_dict.get("key", "") in collections[name])
                action.triggered.connect(lambda checked=False, n=name: self._move_game_to_collection(game_dict, n))
            if current_collection:
                collection_menu.addSeparator()
                remove_current = collection_menu.addAction(
                    menu_icon("remove"),
                    "REMOVE FROM THIS COLLECTION",
                )
                remove_current.triggered.connect(lambda: self._remove_game_from_collection(game_dict, current_collection))
        remove = menu.addAction(
            menu_icon("trash"),
            "REMOVE FILE CONTENTS",
        )
        favorite.triggered.connect(lambda: self._toggle_game_favorite(game_dict))
        remove.triggered.connect(lambda: self._remove_from_context(game_dict))
        menu.setActiveAction(favorite)
        menu.setDefaultAction(favorite)
        # Controller navigation has no meaningful mouse position. Anchor the
        # popup to the selected card (or list row) so it opens beside that item.
        anchor = None
        source_widget = None
        key = game_dict.get("key", "")

        # A game can appear in several rails at once (for example Recently
        # Played and All Games).  The focused widget identifies the instance
        # the controller is acting on, so prefer it over searching rows in
        # display order.
        focused_widget = QApplication.focusWidget()
        if focused_widget is not None:
            from ui.widgets.game_card import GameCard
            if isinstance(focused_widget, GameCard):
                if focused_widget.game_dict.get("key") == key:
                    source_widget = focused_widget
                    anchor = focused_widget.mapToGlobal(
                        QPoint(focused_widget.width() + 4, max(8, focused_widget.height() // 3))
                    )
            elif isinstance(focused_widget, GameList):
                index = focused_widget.currentRow()
                if 0 <= index < len(focused_widget.games) and focused_widget.games[index].get("key") == key:
                    item = focused_widget.item(index)
                    rect = focused_widget.visualItemRect(item)
                    source_widget = focused_widget
                    anchor = focused_widget.viewport().mapToGlobal(
                        QPoint(rect.right() + 4, rect.center().y())
                    )

        for row in self._rows:
            if anchor is not None:
                break
            for card in getattr(row, "cards", []):
                if card.game_dict.get("key") == key:
                    source_widget = card
                    anchor = card.mapToGlobal(QPoint(card.width() + 4, max(8, card.height() // 3)))
                    break
            if anchor is not None:
                break
            if isinstance(row, GameList):
                index = next((i for i, game in enumerate(row.games) if game.get("key") == key), -1)
                if index >= 0:
                    source_widget = row
                    item = row.item(index)
                    rect = row.visualItemRect(item)
                    anchor = row.viewport().mapToGlobal(QPoint(rect.right(), rect.center().y()))
                    break
        if source_widget is not None and shiboken6.isValid(source_widget):
            source_widget.setFocus(Qt.OtherFocusReason)
        else:
            self._restore_focus()
            focused = QApplication.focusWidget()
            if focused is not None and hasattr(focused, "game_dict"):
                source_widget = focused
                anchor = focused.mapToGlobal(
                    QPoint(focused.width() + 4, max(8, focused.height() // 3))
                )

        window = self.window()
        if window is not None:
            window.activateWindow()
            window.raise_()
            menu.winId()
            popup_window = menu.windowHandle()
            parent_window = window.windowHandle()
            if popup_window is not None and parent_window is not None:
                popup_window.setTransientParent(parent_window)
        menu.exec(anchor if anchor is not None else QCursor.pos())
        if source_widget is not None and shiboken6.isValid(source_widget):
            source_widget.setFocus()
        if open_new_collection[0]:
            self._create_collection_for_game(game_dict)
        if edit_artwork_requested[0]:
            # Let QMenu finish releasing its native popup grab before opening
            # another application-modal window.
            QTimer.singleShot(0, lambda: self._edit_game_artwork(game_dict))

    def _show_game_context(self, game_dict):
        """Open the game actions as an in-window overlay, never a QMenu."""
        self._on_game_focused(game_dict)
        old_menu = getattr(self, "_in_app_context_menu", None)
        if old_menu is not None and shiboken6.isValid(old_menu):
            old_menu.close_menu()

        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        menu = _InAppContextMenu(self, palette)
        self._in_app_context_menu = menu

        def menu_icon(name):
            path = config.project_root / "assets" / "icons" / "menu" / f"{name}.svg"
            return QIcon(str(path)) if path.exists() else QIcon()

        # Restore the selected card after a menu action, but defer the action
        # by one event turn so no modal operation starts during menu teardown.
        focused_widget = QApplication.focusWidget()
        source_widget = focused_widget if focused_widget is not None else None

        def run(callback):
            menu.close_menu()
            if source_widget is not None and shiboken6.isValid(source_widget):
                source_widget.setFocus(Qt.OtherFocusReason)
            QTimer.singleShot(0, callback)

        menu.add_action(
            "REMOVE FROM FAVORITES" if game_dict.get("is_favorite") else "ADD TO FAVORITES",
            lambda: run(lambda: self._toggle_game_favorite(game_dict)),
            _modal_icon("heart-filled" if game_dict.get("is_favorite") else "heart"),
        )
        menu.add_action("EDIT ARTWORK", lambda: run(lambda: self._edit_game_artwork(game_dict)), menu_icon("edit"))
        menu.add_action(
            "REMOVE FROM DESKTOP" if desktop_entry_exists(game_dict) else "ADD TO DESKTOP",
            lambda: run(lambda: self._add_to_desktop(game_dict)),
            menu_icon("trash" if desktop_entry_exists(game_dict) else "plus"),
        )
        menu.add_action("NEW COLLECTION...", lambda: run(lambda: self._create_collection_for_game(game_dict)), menu_icon("plus"))

        collections = userdata.get_collections()
        if collections:
            collection_button = menu.add_action(
                "MOVE TO COLLECTION",
                lambda: self._open_collection_submenu(menu, collection_button, game_dict),
                menu_icon("folder"),
            )
            current_value = self.platform_tab.current_value()
            current_collection = current_value.split(":", 1)[1] if current_value.startswith("collection:") else None
            if current_collection:
                # Keep removal in the same submenu so all collection actions
                # are reached through one predictable controller path.
                collection_button._current_collection = current_collection
        menu.add_action("REMOVE FILE CONTENTS", lambda: run(lambda: self._remove_from_context(game_dict)), menu_icon("trash"))

        # The overlay is parented to HomeView and clamped to its bounds, so it
        # cannot create a native popup grab or a second desktop window.
        anchor = self.mapToGlobal(self.rect().center())
        if source_widget is not None and hasattr(source_widget, "game_dict"):
            anchor = source_widget.mapToGlobal(QPoint(source_widget.width() + 4, max(8, source_widget.height() // 3)))
        menu.open_at(anchor)

    def _open_collection_submenu(self, parent_menu, source_button, game_dict):
        """Open the collection choices as a nested launcher-owned menu."""
        collections = userdata.get_collections()
        if not collections:
            return
        old_menu = getattr(self, "_in_app_context_menu", None)
        if old_menu is not parent_menu:
            return
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        submenu = _InAppContextMenu(self, palette, width=310, return_menu=parent_menu)
        self._in_app_context_menu = submenu

        def choose_collection(name):
            submenu.close_menu()
            parent_menu.close_menu()
            QTimer.singleShot(0, lambda: self._move_game_to_collection(game_dict, name))

        options = [
            (f"MOVE TO: {name}", QIcon(str(config.project_root / "assets" / "icons" / "menu" / "folder.svg")), name)
            for name in collections
        ]
        submenu.add_scroll_select("SELECT COLLECTION", options, choose_collection)
        current_collection = getattr(source_button, "_current_collection", None)
        if current_collection:
            def remove_current_collection():
                submenu.close_menu()
                parent_menu.close_menu()
                QTimer.singleShot(
                    0,
                    lambda: self._remove_game_from_collection(game_dict, current_collection),
                )

            submenu.add_action(
                "REMOVE FROM THIS COLLECTION",
                remove_current_collection,
                QIcon(str(config.project_root / "assets" / "icons" / "menu" / "remove.svg")),
            )
        anchor = source_button.mapToGlobal(QPoint(source_button.width() + 6, 0))
        submenu.open_at(anchor)

    def _sync_collection_tabs(self):
        platforms = {g.get("platform") for g in self.games if str(g.get("platform", "")).casefold() not in ("switch", "pc")}
        collections = userdata.get_collections()
        self.platform_tab.set_platforms(platforms, collections)
        self.collections_changed.emit(list(collections))

    def _create_collection_for_game(self, game_dict):
        def create_collection(value):
            created = userdata.create_collection(value.strip())
            if not created:
                show_message(self, "Invalid Collection", "Choose a name other than HOME.")
                return
            self._move_game_to_collection(game_dict, created)

        self._open_collection_name_dialog(on_accept=create_collection)

    def _open_collection_name_dialog(self, initial_name="", on_accept=None):
        current = getattr(self, "_collection_name_dialog", None)
        if current is not None and shiboken6.isValid(current):
            return
        previous_focus = QApplication.focusWidget()
        window = self.window()
        sidebar = getattr(window, "sidebar", None)
        sidebar_was_expanded = bool(sidebar and sidebar._expanded)
        dialog = _CollectionNameDialog(self, initial_name)
        dialog._previous_focus = previous_focus
        dialog._sidebar_was_expanded = sidebar_was_expanded
        self._collection_name_dialog = dialog
        scrim = _DetailScrim(self)
        self._collection_name_scrim = scrim
        scrim.clicked_outside.connect(dialog._cancel)
        scrim.setGeometry(self.rect())
        scrim.show()
        scrim.raise_()
        x = max(0, (self.width() - dialog.width()) // 2)
        y = max(0, (self.height() - dialog.height()) // 2)
        dialog.move(x, y)

        def finished(result):
            entered_name = dialog.name_input.text()
            if getattr(self, "_collection_name_dialog", None) is dialog:
                self._collection_name_dialog = None
            if getattr(self, "_collection_name_scrim", None) is scrim:
                self._collection_name_scrim = None
            scrim.hide()
            scrim.deleteLater()
            previous_focus = getattr(dialog, "_previous_focus", None)
            if previous_focus is not None and shiboken6.isValid(previous_focus) and previous_focus.isVisible() and previous_focus.isEnabled():
                previous_focus.setFocus(Qt.OtherFocusReason)
            if sidebar is not None and not getattr(dialog, "_sidebar_was_expanded", False):
                QTimer.singleShot(0, lambda: sidebar.set_expanded(False))
            dialog.deleteLater()
            if result == QDialog.DialogCode.Accepted and on_accept is not None:
                QTimer.singleShot(0, lambda value=entered_name: on_accept(value))

        dialog.finished.connect(finished)
        dialog.show()
        dialog.raise_()
        if getattr(self.window(), "_controller_input_mode", False):
            dialog._active_key.setFocus(Qt.PopupFocusReason)
        else:
            dialog.name_input.setFocus(Qt.PopupFocusReason)

    def _move_game_to_collection(self, game_dict, name):
        userdata.move_to_collection(name, game_dict.get("key", ""))
        self._sync_collection_tabs()
        target = f"collection:{name}"
        if target in self.platform_tab.tab_values:
            self.platform_tab.set_current_tab(self.platform_tab.tab_values.index(target))
        else:
            self._refresh_current_tab()

    def _remove_game_from_collection(self, game_dict, name):
        userdata.remove_from_collection(name, game_dict.get("key", ""))
        self._refresh_current_tab()

    def _toggle_game_favorite(self, game_dict):
        key = game_dict.get("key", "")
        toggle_favorite(key)
        self._apply_favorite_state(game_dict, is_favorite(key))

    def _remove_from_context(self, game_dict):
        self._on_game_focused(game_dict)
        self._confirm_remove_contents()

    def _edit_game_artwork(self, game_dict):
        if not game_dict or self._artwork_editor_open:
            return
        self._artwork_editor_open = True
        try:
            dialog = _ArtworkPickerDialog(game_dict, self)
            self._artwork_dialog = dialog
            dialog.artwork_saved.connect(
                lambda kind, path: self._apply_artwork_change(game_dict, kind, path)
            )
            dialog.setGeometry(self.rect().adjusted(28, 28, -28, -28))
            dialog.finished.connect(lambda _result: self._finish_artwork_editor(dialog))
            dialog.show()
            dialog.raise_()
            sound_manager.play("modal_popup")
            dialog.tabs.tabBar().setFocus(Qt.PopupFocusReason)
        except Exception as exc:
            # Artwork search/download is optional; it must never terminate the
            # launcher if the API, image decoder, or local cache misbehaves.
            print(f"[ARTWORK] editor failed: {exc}")
            show_message(self, "Artwork Editor", f"Could not open the artwork editor:\n{exc}")
            self._artwork_editor_open = False

    def _finish_artwork_editor(self, dialog):
        if getattr(self, "_artwork_dialog", None) is dialog:
            self._artwork_dialog = None
        self._artwork_editor_open = False
        previous_focus = getattr(dialog, "_previous_focus", None)
        if previous_focus is not None and shiboken6.isValid(previous_focus) and previous_focus.isVisible() and previous_focus.isEnabled():
            previous_focus.setFocus(Qt.OtherFocusReason)
        dialog.deleteLater()

    def _apply_artwork_change(self, game_dict, kind, path):
        game_dict[f"{kind}_path"] = path
        _save_local_metadata(game_dict)
        if kind == "icon" and desktop_entry_exists(game_dict):
            try:
                # Give the desktop environment time to observe removal before
                # recreating the same launcher. Without this gap some menus
                # retain the old icon from their desktop-entry cache.
                remove_desktop_entry(game_dict)
                self._desktop_refresh_generation += 1
                generation = self._desktop_refresh_generation
                self._desktop_refresh_pending = True
                self._refresh_desktop_button(game_dict)

                def recreate():
                    if generation != self._desktop_refresh_generation:
                        return
                    try:
                        create_desktop_entry(game_dict)
                    except Exception as exc:
                        print(f"[DESKTOP] icon refresh failed: {exc}")
                    finally:
                        self._desktop_refresh_pending = False
                        self._refresh_desktop_button(game_dict)
                        self.end_artwork_change_lock()

                QTimer.singleShot(3000, recreate)
            except Exception as exc:
                print(f"[DESKTOP] icon refresh failed: {exc}")
                self.end_artwork_change_lock()
        elif kind == "icon":
            self.end_artwork_change_lock()
        self.update_card_art(
            game_dict.get("key", ""),
            game_dict.get("cover_path"),
            game_dict.get("hero_path"),
            game_dict.get("logo_path"),
            game_dict.get("icon_path"),
        )
        if self.detail_overlay.isVisible() and self._detail_game is game_dict:
            self.detail_background.set_artwork(
                game_dict.get("hero_path") or game_dict.get("cover_path")
            )
            cover = QPixmap(game_dict.get("cover_path", "")) if game_dict.get("cover_path") else QPixmap()
            self._set_detail_cover(cover)
            self._refresh_desktop_button(game_dict)

    def _launch_focused(self):
        game = self._detail_game if self.detail_overlay.isVisible() else self.focused_game
        if game and not (game.get("platform") == "PC" and not game_is_installed(game)):
            sound_manager.play("play")
            self._launch_game(game)

    def _add_focused_to_desktop(self):
        game = self._detail_game if self.detail_overlay.isVisible() else self.focused_game
        if game:
            self._add_to_desktop(game)

    def _refresh_desktop_button(self, game):
        if not hasattr(self, "detail_desktop"):
            return
        if getattr(self, "_desktop_refresh_pending", False):
            self.detail_desktop.setText("UPDATING ICON...")
            self.detail_desktop.setToolTip("Updating the desktop launcher icon")
            self.detail_desktop.setEnabled(False)
            return
        exists = bool(game and desktop_entry_exists(game))
        self.detail_desktop.setText("REMOVE FROM DESKTOP" if exists else "ADD TO DESKTOP")
        self.detail_desktop.setEnabled(True)
        self.detail_desktop.setToolTip(
            "Remove this game's desktop launcher" if exists
            else "Create a desktop launcher using this game's selected icon"
        )

    def _add_to_desktop(self, game):
        if getattr(self, "_desktop_refresh_pending", False):
            return
        if desktop_entry_exists(game):
            removed = remove_desktop_entry(game)
            self._refresh_desktop_button(game)
            show_message(
                self,
                "Desktop Launcher",
                "The desktop and application-menu launchers were removed." if removed
                else "No desktop launcher was found.",
            )
            return
        try:
            entry = create_desktop_entry(game)
        except Exception as exc:
            show_message(self, "Desktop Launcher", f"Could not create the desktop launcher.\n\n{exc}")
            return
        show_message(
            self,
            "Desktop Launcher",
            f"A direct launcher for {game.get('title', 'this game')} was added to the Desktop and application menu.\n\n{entry}",
        )
        self._refresh_desktop_button(game)

    def _install_focused(self):
        game = self._detail_game if self.detail_overlay.isVisible() else self.focused_game
        if not game or game.get("platform") != "PC" or game_is_installed(game):
            return
        install_game = dict(game)
        install_game["launch_uri"] = f"steam://install/{game.get('source_id', '')}"
        self.game_install_requested.emit(install_game)

    def _show_game_details(self, game_dict):
        """Select a game and open its detail state without launching it."""
        sound_manager.play("modal_popup")
        self._detail_closing = False
        closing = getattr(self, "_detail_close_animation", None)
        if closing and closing.state() == QAbstractAnimation.Running:
            closing.stop()
        self._on_game_focused(game_dict)
        self._detail_game = game_dict
        self._focus_zone = ZONE_ROWS
        self.detail_title.setText(game_dict.get("title", "GAME DETAILS").upper())
        key = game_dict.get("key", "")
        minutes = userdata.get_playtime(key) // 60
        last = userdata.get_last_played(key)
        last_text = datetime.fromtimestamp(last).strftime("%d %b %Y") if last else "Never"
        self.detail_meta.setText(f"{game_dict.get('platform', 'UNKNOWN')}  •  {game_dict.get('year', 'YEAR UNKNOWN')}  •  {game_dict.get('developer', 'DEVELOPER UNKNOWN')}  •  PLAYTIME {minutes // 60}h {minutes % 60}m  •  LAST PLAYED {last_text}")
        self.detail_playtime.setText(f"TOTAL PLAYED\n{minutes // 60}h {minutes % 60}m")
        cover = QPixmap(game_dict.get("cover_path", "")) if game_dict.get("cover_path") else QPixmap()
        self._set_detail_cover(cover)
        self.detail_background.setGeometry(self.detail_overlay.rect())
        self.detail_background.set_artwork(
            game_dict.get("hero_path") or game_dict.get("cover_path")
        )
        self.detail_favorite.setIcon(_modal_icon("heart-filled" if game_dict.get("is_favorite") else "heart"))
        self.detail_description.setText(game_dict.get("description", "No description is available yet."))
        self.detail_screenshots.setText(f"{len(game_dict.get('screenshots', []))} cached gameplay screenshot(s) available")
        self._refresh_desktop_button(game_dict)
        unavailable = game_dict.get("platform") == "PC" and not game_is_installed(game_dict)
        self.detail_play.setEnabled(not unavailable)
        self.detail_play.setVisible(not unavailable)
        self.detail_play.setToolTip("Install this game first" if unavailable else "Play game")
        self.detail_install.setVisible(unavailable)
        target_rect = self._detail_target_rect()
        start_rect = target_rect.adjusted(0, 42, 0, -42)
        self.detail_scrim.setGeometry(self.rect())
        self.detail_scrim.show()
        self.detail_scrim.raise_()
        window = self.window()
        if window is not None and hasattr(window, "sidebar"):
            window.sidebar.setEnabled(False)
        self.detail_overlay.setGeometry(start_rect)
        self.detail_background.setGeometry(self.detail_overlay.rect())
        self.detail_overlay.show()
        self.detail_overlay.raise_()
        QTimer.singleShot(0, lambda: self._set_detail_cover(cover))
        popup = QParallelAnimationGroup(self)
        geometry = QPropertyAnimation(self.detail_overlay, b"geometry", popup)
        geometry.setDuration(200)
        geometry.setStartValue(self.detail_overlay.geometry())
        geometry.setEndValue(target_rect)
        geometry.setEasingCurve(QEasingCurve.OutCubic)
        popup.addAnimation(geometry)
        self._detail_popup_animation = popup
        popup.start()
        (self.detail_install if unavailable else self.detail_play).setFocus()

    def _confirm_remove_contents(self):
        game = self._detail_game if self.detail_overlay.isVisible() else self.focused_game
        if not game:
            return
        target = Path(game.get("path", "")).expanduser()
        if not target.exists():
            show_message(self, "File Not Found", "The game files are already missing.")
            return
        if not confirm_message(
            self, "Remove Game Files",
            f"Permanently remove all contents for:\n\n{target}\n\nThis cannot be undone.",
        ):
            return
        configured = config.library.get("libraries", {}).get(game.get("platform", ""), "")
        root = Path(configured).expanduser().resolve() if configured else None
        resolved = target.resolve()
        if root is None or (resolved != root and root not in resolved.parents):
            show_message(self, "Blocked", "Only files inside the configured game library can be removed.")
            return
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            show_message(self, "Remove Failed", str(exc))
            return
        self._close_game_details()
        self.library_changed.emit()

    def _refresh_current_tab(self):
        tab = self.platform_tab.current_value()
        if tab == "HOME":
            self._build_home_tab()
        elif tab.startswith("collection:"):
            self._build_collection_tab(tab.split(":", 1)[1])
        else:
            self._build_platform_tab(tab)

    def _maybe_load_more(self, value):
        if not self._rows or self.rows_scroll.verticalScrollBar().maximum() - value > 180:
            return
        grid = self._rows[-1]
        if isinstance(grid, GameGrid):
            grid.load_more()

    def _set_detail_cover(self, cover):
        if cover.isNull():
            self.detail_cover.set_source_pixmap(QPixmap())
            return
        self.detail_cover.set_source_pixmap(cover)

    def _on_card_favorite_toggled(self, game_dict):
        self._apply_favorite_state(game_dict, game_dict.get("is_favorite", False))

    def _launch_game(self, game_dict):
        if self.detail_overlay.isVisible():
            self._close_game_details()
        sound_manager.play("launch")
        self.game_launched.emit(game_dict)

    def _toggle_fav(self):
        if not self.focused_game:
            return
        sound_manager.play("select")
        key = self.focused_game.get("key", "")
        toggle_favorite(key)
        fav = is_favorite(key)
        self._apply_favorite_state(self.focused_game, fav)

    def scroll_by_page(self, direction):
        bar = self.rows_scroll.verticalScrollBar()
        amount = max(80, self.rows_scroll.viewport().height() // 2)
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(260)
        animation.setStartValue(bar.value())
        animation.setEndValue(bar.value() + direction * amount)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._vertical_scroll_animation = animation
        animation.start()

    # ── Key events ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()

        if self._focus_zone == ZONE_BUTTONS:
            # Navigate the action buttons
            if key == Qt.Key_Left:
                self._btn_index = max(0, self._btn_index - 1)
                self._highlight_button(self._btn_index)
                self._nav_buttons[self._btn_index].setFocus()
                sound_manager.play("navigate")
            elif key == Qt.Key_Right:
                self._btn_index = min(len(self._nav_buttons) - 1, self._btn_index + 1)
                self._highlight_button(self._btn_index)
                self._nav_buttons[self._btn_index].setFocus()
                sound_manager.play("navigate")
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._nav_buttons[self._btn_index].click()
            elif key == Qt.Key_Down:
                # Drop back into the rows
                self._leave_buttons_zone()
            elif key == Qt.Key_PageDown:
                self.scroll_by_page(1)
            elif key == Qt.Key_PageUp:
                self.scroll_by_page(-1)
            elif key == Qt.Key_Up:
                pass   # already at top — do nothing
            else:
                super().keyPressEvent(event)
            return

        # ── ZONE_ROWS — global shortcuts ───────────────────────────────────
        if key == Qt.Key_PageDown:
            self.scroll_by_page(1)
        elif key == Qt.Key_PageUp:
            self.scroll_by_page(-1)
        elif key == Qt.Key_F and not mod:
            self._toggle_fav()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._launch_focused()
        elif key == Qt.Key_S:
            self.open_settings.emit()
        elif key == Qt.Key_F and (mod & Qt.ControlModifier):
            self.open_search.emit()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        """Re-grab focus on the current card whenever HomeView becomes visible."""
        super().showEvent(event)
        QTimer.singleShot(120, self._restore_focus)

    def _restore_focus(self):
        """Focus the currently active card, activating the window if needed."""
        win = self.window()
        if win:
            win.activateWindow()
            win.raise_()
        self._focus_zone = ZONE_ROWS
        if self._rows and self._active_row < len(self._rows):
            row = self._rows[self._active_row]
            row.focus_card(row.focused_index)
        elif self._rows:
            self._rows[0].focus_card(0)

    def controller_focus_ready(self):
        """Whether controller actions currently have a game/control target."""
        focused = QApplication.focusWidget()
        if focused is None:
            return False
        if self.detail_overlay.isVisible():
            return True
        if focused in self._collection_action_buttons:
            return True
        return any(
            focused is row or row.isAncestorOf(focused)
            for row in self._rows
        )
