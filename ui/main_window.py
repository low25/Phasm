from PySide6.QtWidgets import (QMainWindow, QStackedWidget, QApplication, QMessageBox,
                               QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QGraphicsOpacityEffect,
                               )
from PySide6.QtCore import (Qt, QSize, QCoreApplication, QThread, Signal, QTimer,
                            QObject, QEvent, QPropertyAnimation, QParallelAnimationGroup,
                            QEasingCurve, QFileSystemWatcher, QByteArray, QVariantAnimation,
                            QPointF)
from PySide6.QtGui import (
    QIcon, QCursor, QPalette, QColor, QPixmap, QPainter, QPen,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer

from ui.loading_screen import LoadingScreen
from ui.home_view import HomeView
from ui.search_view import SearchView
from ui.settings_view import SettingsView
from ui.library_view import LibraryView
from ui.account_view import AccountView
from ui.quit_dialog import QuitDialog
from ui.theme import get_stylesheet
from ui.theme import get_theme_colors
from core.config import config
from core.launcher import EmulatorLauncher
from core.session import GameSession
from core import userdata
from pathlib import Path


class _LibraryMonitor(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(1000)
        self._debounce.timeout.connect(self._emit_changed)
        self._paused = False
        self._change_while_paused = False

    def refresh(self):
        self._paused = True
        current = set(self.watcher.directories())
        if current:
            self.watcher.removePaths(list(current))
        paths = set()
        libraries = config.library.get("libraries", {})
        for value in libraries.values():
            folders = value if isinstance(value, (list, tuple)) else [value]
            for folder in folders:
                root = Path(str(folder)).expanduser()
                if not root.is_dir():
                    continue
                paths.add(str(root))
                for child in root.rglob("*"):
                    if child.is_dir():
                        paths.add(str(child))
        if paths:
            self.watcher.addPaths(sorted(paths))
        QTimer.singleShot(500, self._finish_refresh)

    def _finish_refresh(self):
        self._paused = False
        if self._change_while_paused:
            self._change_while_paused = False
            self._debounce.start()

    def _on_changed(self, _path):
        if self._paused:
            self._change_while_paused = True
            return
        self._debounce.start()

    def _emit_changed(self):
        self.changed.emit()


def _app_version():
    try:
        return (config.project_root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


_accent_icon_cache = {}


def _accent_icon(path, color, size=26):
    """Render the brand SVG with the active accent color."""
    key = (str(path), str(color), int(size))
    cached = _accent_icon_cache.get(key)
    if cached is not None:
        return cached
    try:
        svg = Path(path).read_text(encoding="utf-8")
        svg = (
            svg.replace("#ffffff", str(color))
            .replace("#7c3aed", str(color))
            .replace("#c084fc", str(color))
            .replace("rgb(255, 255, 255)", str(color))
        )
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon = QIcon(pixmap)
    except (OSError, RuntimeError):
        icon = QIcon(str(path))
    _accent_icon_cache[key] = icon
    return icon


class _SmoothNavButton(QPushButton):
    """Navbar button with a lightweight animated hover/focus background."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hover_amount = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_amount)

    def _set_hover_amount(self, value):
        self._hover_amount = float(value)
        self.update()

    def _animate_hover(self, showing):
        start = self._hover_amount
        end = 1.0 if showing else 0.0
        self._hover_animation.stop()
        self._hover_animation.setStartValue(start)
        self._hover_animation.setEndValue(end)
        self._hover_animation.start()

    def enterEvent(self, event):
        self._animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(self.hasFocus())
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._animate_hover(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._animate_hover(self.underMouse())
        super().focusOutEvent(event)

    def paintEvent(self, event):
        if self._hover_amount > 0.001:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            color = QColor(0, 0, 0, int(150 * self._hover_amount))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
            painter.end()
        super().paintEvent(event)


class _AccentCursor(QWidget):
    """Accent cursor with a visible multi-colour trail and soft glow."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(False)
        self._accent = QColor("#7c3aed")
        self._position = QPointF(-100, -100)
        self._trail = []
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def set_accent(self, color):
        self._accent = QColor(color)
        self.update()

    def move_to(self, position):
        if self._position.x() >= 0:
            self._trail.insert(0, QPointF(self._position))
        self._trail = self._trail[:14]
        self._position = QPointF(position)
        self.show()
        self.raise_()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self):
        if self._trail:
            self._trail.pop()
            self.update()
        elif self._position.x() < 0:
            self._timer.stop()

    def clear(self):
        """Remove the marker, glow, and all trail state immediately."""
        self._trail.clear()
        self._position = QPointF(-100, -100)
        self._timer.stop()
        self.hide()
        self.update()

    def paintEvent(self, event):
        if self._position.x() < 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        trail_shifts = (0, 18, -14, 32, -28, 10, -10, 24, -20, 14, -6, 28, -18, 8)

        # Draw the newest trail points first, with enough opacity and size to
        # remain visible even on bright artwork. Each point gets a nearby hue
        # so the trail follows the selected accent rather than staying purple.
        for index, point in enumerate(self._trail):
            strength = 1.0 - (index / max(1, len(self._trail)))
            alpha = int(165 * strength)
            color = QColor(self._accent)
            hue = color.hue()
            if hue < 0:
                color = color.lighter(100 + int(35 * strength))
            else:
                color.setHsv(
                    (hue + trail_shifts[index % len(trail_shifts)]) % 360,
                    color.saturation(),
                    min(255, color.value() + int(35 * strength)),
                )
            color.setAlpha(alpha)
            painter.setBrush(color)
            radius = max(1.5, 5.0 - index * 0.25)
            painter.drawEllipse(point, radius, radius)

        # A radial gradient gives the cursor a soft halo without introducing a
        # white center or changing the accent colour of the actual marker.
        glow = QRadialGradient(self._position, 20.0)
        glow.setColorAt(0.0, QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 150))
        glow.setColorAt(0.35, QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 75))
        glow.setColorAt(1.0, QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 0))
        painter.setBrush(glow)
        painter.drawEllipse(self._position, 20.0, 20.0)

        # The marker is fully tinted; there is intentionally no white inner
        # dot so it remains consistent with the selected accent.
        painter.setBrush(self._accent)
        painter.drawEllipse(self._position, 5.5, 5.5)
        painter.end()

class _GlobalFilter(QObject):
    def __init__(self, window):
        super().__init__()
        self.window = window
    def eventFilter(self, obj, event):
        popup = QApplication.activePopupWidget()
        modal = QApplication.activeModalWidget()
        native_surface = modal or popup
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                            QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel):
            if native_surface is not None:
                self.window._use_system_cursor_for_popup()
                return False
            if self.window._controller_input_mode:
                self.window._set_mouse_input()
            if event.type() == QEvent.Type.MouseMove and hasattr(event, "globalPosition"):
                self.window._update_accent_cursor(event.globalPosition().toPoint())
            return False
        # Every modal surface owns controller input until it closes.  Native
        # dialogs/menus are handled by Qt's modal/popup focus, while the
        # launcher-specific quit overlay needs this explicit guard.
        if self.window.quit_container.isVisible():
            custom_modal = self.window.quit_container
        elif self.window.home.detail_overlay.isVisible():
            custom_modal = self.window.home.detail_overlay
        elif getattr(self.window.home, "_in_app_context_menu", None) is not None and self.window.home._in_app_context_menu.isVisible():
            custom_modal = self.window.home._in_app_context_menu
        elif getattr(self.window.home, "_collection_name_dialog", None) is not None and self.window.home._collection_name_dialog.isVisible():
            custom_modal = self.window.home._collection_name_dialog
        elif getattr(self.window.home, "_artwork_dialog", None) is not None and self.window.home._artwork_dialog.isVisible():
            custom_modal = self.window.home._artwork_dialog
        elif getattr(self.window.settings_view, "_color_dialog", None) is not None and self.window.settings_view._color_dialog.isVisible():
            custom_modal = self.window.settings_view._color_dialog
        elif getattr(self.window.settings_view, "_settings_option_overlay", None) is not None and self.window.settings_view._settings_option_overlay.isVisible():
            custom_modal = self.window.settings_view._settings_option_overlay
        else:
            custom_modal = None
        # A native modal dialog takes precedence over the popup that may have
        # launched it; this is important for QInputDialog opened from menus.
        owner = modal or popup or custom_modal
        if owner is not None:
            if (custom_modal is getattr(self.window.home, "_in_app_context_menu", None)
                    and hasattr(custom_modal, "handle_controller_key")):
                if event.type() == QEvent.Type.KeyPress and custom_modal.handle_controller_key(event.key()):
                    return True
            if (custom_modal is getattr(self.window.home, "_artwork_dialog", None)
                    and hasattr(custom_modal, "handle_controller_key")):
                if event.type() == QEvent.Type.KeyPress and custom_modal.handle_controller_key(event.key()):
                    return True
            if (custom_modal is getattr(self.window.home, "_collection_name_dialog", None)
                    and hasattr(custom_modal, "handle_controller_key")):
                if event.type() == QEvent.Type.KeyPress and custom_modal.handle_controller_key(event.key()):
                    return True
            # QMenu already owns the platform popup grab. Let its own event
            # handling receive controller keys even during the short focus
            # transition while it is opening.
            if popup is not None and modal is None and custom_modal is None:
                return False
            # Let Qt complete popup/modal focus and mouse-grab transitions.
            # Intercepting those transitions from the application filter can
            # re-enter Qt's focus machinery and crash the process.
            if event.type() != QEvent.Type.KeyPress:
                return False
            focused = QApplication.focusWidget()
            inside = focused and (focused is owner or owner.isAncestorOf(focused))
            if not inside:
                if self.window.quit_container.isVisible():
                    self.window.quit_dialog.btn_cancel.setFocus()
                elif self.window.home.detail_overlay.isVisible():
                    self.window.home.detail_play.setFocus()
                else:
                    # Native popup/modal widgets manage their own focus. Do
                    # not call setFocus() here: focus events re-enter this
                    # application-wide filter and can recurse indefinitely.
                    return True
                return True
            # Do not let global controller shortcuts (navbar, sections, etc.)
            # escape a modal task.  The modal's own key handler still receives
            # arrows, confirm, and escape.
            return False
        if event.type() == QEvent.Type.KeyPress:
            if self.window.home.detail_overlay.isVisible():
                if event.key() == Qt.Key_Escape:
                    self.window.home._close_game_details()
                    return True
                return False
            k = event.key()
            if k == Qt.Key_Up and self.window.stack.currentWidget() is self.window.home:
                if self.window.home.controller_enter_collection_toolbar():
                    return True
            # The controller Menu/Start button is a direct quit command.  The
            # modifier keeps ordinary keyboard Escape behavior unchanged.
            if k == Qt.Key_Escape and (event.modifiers() & Qt.ControlModifier):
                self.window._show_quit()
                return True
            # Controller shoulder/trigger events carry Ctrl so they can use
            # dedicated keys without changing the existing keyboard section
            # shortcuts.  They move focus through the visible side rail.
            if k in (Qt.Key_F6, Qt.Key_F7) and (event.modifiers() & Qt.ControlModifier):
                self.window._focus_sidebar(-1 if k == Qt.Key_F6 else 1)
                return True
            if k == Qt.Key_F7:
                self.window._section_next()
                return True
            elif k == Qt.Key_F6:
                self.window._section_prev()
                return True
            elif k in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
                direction = -1 if k == Qt.Key_BracketLeft else 1
                current = self.window.stack.currentWidget()
                if current is self.window.home:
                    tabs = self.window.home.platform_tab.tab_values
                    if tabs:
                        index = (self.window.home.platform_tab.current_index + direction) % len(tabs)
                        self.window.home.platform_tab.set_current_tab(index)
                        return True
                elif current is self.window.search:
                    self.window.search.cycle_platform_filter(direction)
                    return True
            elif k in (Qt.Key_PageUp, Qt.Key_PageDown):
                current = self.window.stack.currentWidget()
                scroll = getattr(current, "scroll_by_page", None)
                if scroll:
                    scroll(-1 if k == Qt.Key_PageUp else 1)
                    return True
            elif k == Qt.Key_Escape:
                if self.window.quit_container.isVisible():
                    self.window._hide_quit()
                    return True
                current = self.window.stack.currentWidget()
                if current is self.window.search:
                    return False
                if current is self.window.home and self.window.home.detail_overlay.isVisible():
                    self.window.home._close_game_details()
                    return True
                if current in (self.window.search, self.window.settings_view, self.window.library_view, self.window.account_view):
                    self.window._show_home()
                    return True
        return False


class _AutoHideSidebar(QWidget):
    """Slim icon rail that expands on hover or controller focus."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(58)
        self._expanded = False
        self._animation = None
        self._brand = None
        self._version_label = None
        self._items = []
        self._nav_labels = []
        self._label_effects = []
        self._icon_files = (
            "navbarHome.svg", "navbarSearch.svg", "navbarLibrary.svg",
            "navbarSettings.svg", "navbarAccount.svg", "navbarScan.svg", "navbarQuit.svg",
        )

    def configure(self, brand, items, version_label=None):
        self._brand = brand
        self._version_label = version_label
        self._items = items
        labels = ("HOME", "SEARCH", "LIBRARY", "SETTINGS", "ACCOUNT", "SCAN", "QUIT")
        for button, label in zip(items, labels):
            # Keep the icon in the button's fixed left position. The label is
            # an independent overlay, so changing sidebar width never causes
            # the button layout to recalculate or snap the icon.
            button.setText("")
            text = QLabel(label, self)
            text.setAttribute(Qt.WA_TransparentForMouseEvents)
            text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text.setStyleSheet(
                "QLabel { background: transparent; color: #8f86a8; "
                "font-size: 13px; font-weight: bold; }"
            )
            effect = QGraphicsOpacityEffect(text)
            effect.setOpacity(0.0)
            text.setGraphicsEffect(effect)
            self._nav_labels.append(text)
            self._label_effects.append(effect)
        for widget in [brand, *items]:
            widget.installEventFilter(self)
        self._set_visual_state(False)

    def _set_visual_state(self, expanded):
        self._expanded = expanded
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        accent = palette["ACCENT"]
        icon_path = config.project_root / "assets" / "icon.svg"
        self._brand.setIcon(_accent_icon(icon_path, accent, 26))
        self._brand.setText("  PHASM" if expanded else "")
        self._brand.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {accent}; "
            "font-size: 14px; letter-spacing: 1px; padding: 10px 4px; } "
            f"QPushButton:hover, QPushButton:focus, QPushButton:pressed {{ background: transparent; color: {accent}; }}"
            if expanded else
            f"QPushButton {{ background: transparent; border: none; color: {accent}; "
            "text-align: center; padding: 10px 0; } "
            f"QPushButton:hover, QPushButton:focus, QPushButton:pressed {{ background: transparent; color: {accent}; }}"
        )
        if self._version_label is not None:
            version = _app_version().lstrip("V")
            compact_version = ".".join(version.split(".")[:2]) if "." in version else version
            self._version_label.setText(f"V{version}" if expanded else compact_version)
        labels = ("HOME", "SEARCH", "LIBRARY", "SETTINGS", "ACCOUNT", "SCAN", "QUIT")
        icon_dir = config.project_root / "assets" / "UI"
        for index, (button, label) in enumerate(zip(self._items, labels)):
            self._nav_labels[index].setStyleSheet(
                f"QLabel {{ background: transparent; color: {palette['ACCENT']}; "
                "font-size: 13px; font-weight: bold; }"
            )
            icon_path = icon_dir / self._icon_files[index]
            # The account SVG shipped with a hard-coded violet stroke. Render
            # it through the same accent pipeline as the brand icon so it
            # follows custom accent selections instead of staying purple.
            icon = (
                _accent_icon(icon_path, palette["ACCENT"], 22)
                if index in (4, 5, 6) else QIcon(str(icon_path))
            )
            button.setIcon(icon)
            button.setIconSize(QSize(22, 22))
            if self._expanded:
                style = (
                    "QPushButton { text-align: left; padding: 13px 16px; border: none; "
                    "border-radius: 8px; color: #8f86a8; font-size: 13px; font-weight: bold; }"
                    "QPushButton:hover, QPushButton:focus { background: transparent; "
                    f"color: #ffffff; border-left: 3px solid {palette['HIGHLIGHT']}; }}"
                    f"QPushButton[active=\"true\"] {{ background: #000000; color: #ffffff; border-left: 3px solid {palette['ACCENT2']}; }}"
                )
            else:
                style = (
                    "QPushButton { text-align: center; padding: 13px 0; border: none; "
                    f"border-radius: 8px; color: {palette['TEXT_DIM']}; }}"
                    "QPushButton:hover, QPushButton:focus { background: transparent; color: #ffffff; }"
                    "QPushButton[active=\"true\"] { background: #000000; color: #ffffff; }"
                )
            button.setStyleSheet(style)
        self._sync_nav_labels()

    def _sync_nav_labels(self):
        for button, label in zip(self._items, self._nav_labels):
            label.setGeometry(68, button.y(), max(0, self.width() - 68), button.height())

    def resizeEvent(self, event):
        self._sync_nav_labels()
        super().resizeEvent(event)

    def set_expanded(self, expanded):
        if expanded == self._expanded and self._animation is None:
            return
        self._set_visual_state(expanded)
        # Leave enough room for the icon and the complete brand name while
        # keeping the collapsed rail compact.
        target = 240 if expanded else 58
        current = max(58, self.width())
        if self._animation is not None:
            self._animation.stop()
        self.setMinimumWidth(58)
        self.setMaximumWidth(max(current, target))
        group = QParallelAnimationGroup(self)
        for property_name in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self, property_name, group)
            animation.setDuration(280)
            animation.setStartValue(current)
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(animation)
        for effect in self._label_effects:
            fade = QPropertyAnimation(effect, b"opacity", group)
            fade.setDuration(220)
            fade.setStartValue(effect.opacity())
            fade.setEndValue(1.0 if expanded else 0.0)
            fade.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(fade)
        self._animation = group
        group.finished.connect(lambda: self.setFixedWidth(target))
        group.finished.connect(self._clear_animation)
        group.start()

    def _clear_animation(self):
        self._animation = None

    def enterEvent(self, event):
        self.set_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QTimer.singleShot(80, self._collapse_if_unfocused)
        super().leaveEvent(event)

    def _collapse_if_unfocused(self):
        focused = QApplication.focusWidget()
        if not self.underMouse() and not (focused and (focused is self or self.isAncestorOf(focused))):
            self.set_expanded(False)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and obj in self._items:
            index = self._items.index(obj)
            if event.key() == Qt.Key_Down:
                self._items[min(index + 1, len(self._items) - 1)].setFocus()
                return True
            if event.key() == Qt.Key_Up:
                if index == 0:
                    home = self.window().home
                    home._focus_zone = "rows"
                    home._focus_row(0, card_index=0)
                else:
                    self._items[index - 1].setFocus()
                return True
            if event.key() == Qt.Key_Right:
                home = self.window().home
                home._focus_zone = "rows"
                home._focus_row(0, card_index=0)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                obj.click()
                return True
        if event.type() == QEvent.Type.FocusIn:
            self.set_expanded(True)
        elif event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(80, self._collapse_if_unfocused)
        return super().eventFilter(obj, event)

class ArtworkFetcherThread(QThread):
    art_ready = Signal(str, str, str, str)

    def __init__(self, games, parent=None):
        super().__init__(parent)
        self.games = games

    def run(self):
        from core.assets import fetch_cover, fetch_hero, fetch_logo
        for game in self.games:
            if self.isInterruptionRequested():
                return
            key = game.get("key", "")
            title = game.get("title", "")
            platform = game.get("platform", "")

            if game.get("cover_path") and game.get("hero_path") and game.get("logo_path"):
                continue

            try:
                cover = game.get("cover_path") or fetch_cover(title, platform) or ""
                hero = game.get("hero_path") or fetch_hero(title, platform) or ""
                logo = game.get("logo_path") or fetch_logo(title, platform) or ""

                if cover or hero or logo:
                    self.art_ready.emit(key, cover, hero, logo)
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._controller_input_mode = False
        self.setWindowTitle("Phasm")
        self.setWindowIcon(QIcon(str(config.project_root / "assets" / "icon.svg")))
        self.setStyleSheet(get_stylesheet())

        icon_path = config.project_root / "assets" / "icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.stack = QStackedWidget(self)
        shell = QWidget(self)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.sidebar = _AutoHideSidebar()
        self.sidebar.setStyleSheet("_AutoHideSidebar { background: #000000; border-right: 1px solid #242039; }")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 18)
        sidebar_layout.setSpacing(8)

        brand_row = QWidget(self.sidebar)
        brand_layout = QHBoxLayout(brand_row)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(6)

        brand = QPushButton("  PHASM")
        brand.setCursor(Qt.PointingHandCursor)
        brand.setIcon(_accent_icon(
            icon_path, get_theme_colors(accent_name=config.settings.get("accent"))["ACCENT"], 26
        ) if icon_path.exists() else QIcon())
        brand.setIconSize(QSize(26, 26))
        brand.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {get_theme_colors(accent_name=config.settings.get('accent'))['ACCENT']}; "
            "font-size: 14px; letter-spacing: 1px; padding: 10px 4px; } "
            f"QPushButton:hover, QPushButton:focus, QPushButton:pressed {{ background: transparent; color: {get_theme_colors(accent_name=config.settings.get('accent'))['ACCENT']}; }}"
        )
        brand.clicked.connect(self._show_home)
        brand_layout.addWidget(brand, 1)

        sidebar_layout.addWidget(brand_row)

        divider = QLabel()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #2b2342;")
        sidebar_layout.addWidget(divider)

        self.nav_home = _SmoothNavButton("⌂   HOME")
        self.nav_search = _SmoothNavButton("⌕   SEARCH")
        self.nav_settings = _SmoothNavButton("⚙   SETTINGS")
        self.nav_account = _SmoothNavButton("◉   ACCOUNT")
        self.nav_quit = _SmoothNavButton("⏻   QUIT")
        self.nav_library = _SmoothNavButton("▤   LIBRARY")
        self.nav_scan = _SmoothNavButton("⟳   SCAN")
        nav_items = ((self.nav_home, self._show_home), (self.nav_search, self._show_search),
                     (self.nav_library, self._show_library), (self.nav_settings, self._show_settings),
                     (self.nav_account, self._show_account), (self.nav_scan, self._manual_scan),
                     (self.nav_quit, self._show_quit))
        for index, (button, slot) in enumerate(nav_items):
            button.setFocusPolicy(Qt.StrongFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            if button is self.nav_account:
                account_divider = QLabel()
                account_divider.setFixedHeight(1)
                account_divider.setStyleSheet("background: #2b2342;")
                sidebar_layout.addWidget(account_divider)
            sidebar_layout.addWidget(button)
        # QUIT remains mouse-clickable, but is intentionally excluded from
        # controller focus/navigation. Controller Menu/Start opens the same
        # confirmation directly.
        self.nav_quit.setFocusPolicy(Qt.NoFocus)
        # Scan is mouse-accessible but is intentionally excluded from
        # controller trigger/sidebar focus navigation, like Quit.
        self.nav_scan.setFocusPolicy(Qt.NoFocus)
        sidebar_layout.addStretch()
        version_label = QLabel(f"V{_app_version()}", self.sidebar)
        version_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        version_label.setStyleSheet(
            "QLabel { background: transparent; color: #8f86a8; padding: 4px 2px; "
            "font-size: 10px; font-weight: bold; letter-spacing: 1px; }"
        )
        sidebar_layout.addWidget(version_label, 0, Qt.AlignLeft)
        self.sidebar.configure(
            brand,
            [self.nav_home, self.nav_search, self.nav_library, self.nav_settings, self.nav_account, self.nav_scan, self.nav_quit],
            version_label,
        )
        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        self._accent_cursor = _AccentCursor(self)
        self._accent_cursor.set_accent(
            get_theme_colors(accent_name=config.settings.get("accent"))["ACCENT"]
        )
        self._custom_cursor_enabled = config.settings.get("custom_cursor", True)
        self._cursor_popup_active = False
        if self._custom_cursor_enabled:
            QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))

        self.loading = LoadingScreen()
        self.home = HomeView()
        self.search = SearchView()
        self._return_to_search_after_detail = False
        self.settings_view = SettingsView()
        self.library_view = LibraryView()
        self.account_view = AccountView()
        self.quit_dialog = QuitDialog()

        self.stack.addWidget(self.loading)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.search)
        self.stack.addWidget(self.settings_view)
        self.stack.addWidget(self.library_view)
        self.stack.addWidget(self.account_view)

        self.quit_container = QWidget(self)
        self.quit_container.setFocusPolicy(Qt.StrongFocus)
        q_layout = QVBoxLayout(self.quit_container)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.addWidget(self.quit_dialog)
        self.quit_container.hide()

        self.loading.loading_complete.connect(self._on_loading_complete)

        self.home.game_launched.connect(self._launch_game)
        self.home.game_install_requested.connect(self._launch_game)
        self.home.library_changed.connect(self._start_scan)
        self.home.collections_changed.connect(self._on_collections_changed)
        self.home.open_search.connect(self._show_search)
        self.home.open_settings.connect(self._show_settings)
        self.home.quit_requested.connect(self._show_quit)

        self.search.closed.connect(self._show_home)
        self.search.game_selected.connect(self._open_search_result)
        self.home.detail_closed.connect(self._return_to_search_results)

        self.settings_view.closed.connect(self._show_home)
        self.settings_view.rescan_requested.connect(self._start_scan)
        self.library_view.rescan_requested.connect(self._start_scan)
        self.library_view.closed.connect(self._show_home)
        self.account_view.closed.connect(self._show_home)
        self.account_view.accounts_changed.connect(self._start_scan)
        self.settings_view.rescan_requested.connect(
            lambda: self.home.apply_hero_settings(
                config.settings.get("hero_orientation", "vertical"),
                config.settings.get("hero_width", 360),
                config.settings.get("hero_height", 260),
            )
        )

        self.quit_dialog.confirmed.connect(QCoreApplication.quit)
        self.quit_dialog.cancelled.connect(self._hide_quit)

        self._artwork_thread = None
        self._controller_thread = None

        self._active_session = None
        self._sections = ['HOME']
        self._section_index = 0
        self._scan_pending = False
        self._scan_cooldown = QTimer(self)
        self._scan_cooldown.setSingleShot(True)
        self._scan_cooldown.setInterval(5000)
        self._scan_cooldown.timeout.connect(lambda: self.nav_scan.setEnabled(True))
        self._library_monitor = _LibraryMonitor(self)
        self._library_monitor.changed.connect(self._request_library_scan)
        self._library_monitor.refresh()

        self._global_filter = _GlobalFilter(self)
        QApplication.instance().installEventFilter(self._global_filter)

        self._start_scan()
        QTimer.singleShot(500, self._start_controller)

        # showFullScreen MUST come last — it fires resizeEvent immediately,
        # which references quit_container, so that must exist first.
        if config.settings.get("fullscreen", True):
            self.showFullScreen()
        else:
            self.resize(1280, 720)
        self.setMinimumSize(720, 480)

    def _prepare_controller_input(self):
        """Make controller input authoritative and restore a missing focus target."""
        self._set_controller_input()
        collection_name_dialog = getattr(self.home, "_collection_name_dialog", None)
        if collection_name_dialog is not None and collection_name_dialog.isVisible():
            collection_name_dialog.activate_controller_input()
            return
        if self.quit_container.isVisible():
            if QApplication.focusWidget() not in (
                self.quit_dialog.btn_yes,
                self.quit_dialog.btn_cancel,
            ):
                self.quit_dialog.btn_cancel.setFocus(Qt.PopupFocusReason)
            return
        current = self.stack.currentWidget()
        if current is self.home and not self.home.controller_focus_ready():
            self.home._restore_focus()

    def _set_controller_input(self):
        if self._controller_input_mode:
            return
        self._controller_input_mode = True
        self._accent_cursor.clear()
        QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))

    def _set_mouse_input(self):
        self._controller_input_mode = False
        if self._cursor_popup_active:
            return
        if not self._custom_cursor_enabled:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        elif QApplication.overrideCursor() is None:
            QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))

    def set_custom_cursor_enabled(self, enabled):
        self._custom_cursor_enabled = bool(enabled)
        self._cursor_popup_active = False
        if self._custom_cursor_enabled:
            if QApplication.overrideCursor() is None:
                QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))
        else:
            self._accent_cursor.clear()
            if QApplication.overrideCursor() is not None and not self._controller_input_mode:
                QApplication.restoreOverrideCursor()

    def _update_accent_cursor(self, global_position):
        if not self._custom_cursor_enabled:
            self._accent_cursor.clear()
            return
        if self._cursor_popup_active:
            self._cursor_popup_active = False
            if self._custom_cursor_enabled and QApplication.overrideCursor() is None:
                QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))
        if not self.isVisible() or not self.rect().contains(self.mapFromGlobal(global_position)):
            return
        self._accent_cursor.move_to(self.mapFromGlobal(global_position))

    def _use_system_cursor_for_popup(self):
        self._cursor_popup_active = True
        self._accent_cursor.clear()
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()


    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.quit_container.setGeometry(self.rect())
        if hasattr(self, "_accent_cursor"):
            self._accent_cursor.setGeometry(self.rect())

    def _start_controller(self):
        from ui.controller import start_controller
        self._controller_thread = start_controller()

    def closeEvent(self, event):
        # Stop application-wide event filtering before child widgets such as
        # the quit overlay are destroyed. Otherwise late Qt events can call
        # eventFilter() with wrappers whose C++ QFrame is already deleted.
        app = QApplication.instance()
        if app is not None and app.overrideCursor() is not None:
            app.restoreOverrideCursor()
        if app is not None and self._global_filter is not None:
            app.removeEventFilter(self._global_filter)
        if self._active_session:
            self._active_session.kill()
        if hasattr(self.loading, "stop_loading"):
            self.loading.stop_loading()
        if self._controller_thread:
            self._controller_thread.stop()
            self._controller_thread.wait(3000)
        if self._artwork_thread and self._artwork_thread.isRunning():
            self._artwork_thread.requestInterruption()
            if not self._artwork_thread.wait(5000):
                print("[ARTWORK] Previous artwork scan is still stopping")
                return
        super().closeEvent(event)

    def _start_scan(self):
        scanner = getattr(self.loading, "scanner", None)
        if scanner and scanner.isRunning():
            self._scan_pending = True
            return
        self.nav_scan.setEnabled(False)
        self._library_monitor._paused = True
        self.sidebar.hide()
        self._transition_to(self.loading)
        self.loading.start_loading()

    def _request_library_scan(self):
        self._start_scan()

    def _manual_scan(self):
        if self._scan_cooldown.isActive():
            return
        self._start_scan()

    def _on_loading_complete(self, games_list):
        # scan_complete is emitted just before the worker thread returns. Do
        # not replace that worker with another scan until Qt reports it fully
        # stopped; this prevents rapid manual scans from crashing QThread.
        scanner = getattr(self.loading, "scanner", None)
        if scanner and scanner.isRunning():
            QTimer.singleShot(80, lambda: self._on_loading_complete(games_list))
            return
        self.sidebar.show()
        self.home.set_games(games_list)
        self.search.set_games(games_list)
        
        self._on_collections_changed(list(userdata.get_collections()))
        self.library_view.refresh()
        self._library_monitor.refresh()
        
        self._transition_to(self.home)
        self._update_section_nav()
        self.home.setFocus()

        from core.assets import _api_key
        if _api_key():
            self._start_artwork_fetch(games_list)
        if self._scan_pending:
            self._scan_pending = False
            QTimer.singleShot(250, self._start_scan)
        else:
            self.nav_scan.setEnabled(False)
            self._scan_cooldown.start()

    def _on_collections_changed(self, collection_names):
        platforms = sorted({g.get("platform", "").upper() for g in self.home.games if g.get("platform") and str(g.get("platform")).casefold() not in ("switch", "pc")})
        current = self._sections[self._section_index] if self._sections and self._section_index < len(self._sections) else "HOME"
        self._sections = ["HOME"] + platforms + [f"collection:{name}" for name in collection_names] + ["SEARCH", "SETTINGS"]
        self._section_index = self._sections.index(current) if current in self._sections else 0
        self._update_section_nav()

    def _start_artwork_fetch(self, games_list):
        if self._artwork_thread and self._artwork_thread.isRunning():
            self._artwork_thread.requestInterruption()
            self._artwork_thread.wait(5000)

        self._artwork_thread = ArtworkFetcherThread(games_list)
        self._artwork_thread.art_ready.connect(self._on_art_ready)
        self._artwork_thread.start()

    def _on_art_ready(self, key, cover, hero, logo):
        self.home.update_card_art(key, cover or None, hero or None, logo or None)
        self.search.update_game_art(key, cover or None)

    def _section_next(self):
        if self.quit_container.isVisible(): return
        self._section_index = (self._section_index + 1) % len(self._sections)
        self._apply_section()

    def _section_prev(self):
        if self.quit_container.isVisible(): return
        self._section_index = (self._section_index - 1) % len(self._sections)
        self._apply_section()

    def _apply_section(self):
        sec = self._sections[self._section_index]
        if sec == 'SEARCH':
            self._show_search(update_idx=False)
        elif sec == 'SETTINGS':
            self._show_settings(update_idx=False)
        else:
            self._show_home(update_idx=False)
            if sec == 'HOME':
                self.home.platform_tab.set_current_tab(0)
            else:
                tabs = self.home.platform_tab.tab_values
                if sec in tabs:
                    self.home.platform_tab.set_current_tab(tabs.index(sec))
        self._update_section_nav()
                    
    def _update_section_nav(self):
        self.home.set_section_label(self._sections, self._section_index)

    def _show_search(self, update_idx=True):
        if update_idx and 'SEARCH' in self._sections:
            self._section_index = self._sections.index('SEARCH')
            self._update_section_nav()
        self._transition_to(self.search)
        # Search opens directly on the live fuzzy-results page. The virtual
        # keyboard is an optional controller input layer over that page.
        self.search.show_results_mode()

    def _open_search_result(self, game_dict):
        self._return_to_search_after_detail = True
        self._transition_to(self.home)
        self.home._show_game_details(game_dict)

    def _return_to_search_results(self):
        if not self._return_to_search_after_detail:
            return
        self._return_to_search_after_detail = False
        if "SEARCH" in self._sections:
            self._section_index = self._sections.index("SEARCH")
            self._update_section_nav()
        self._transition_to(self.search)
        self.search.show_results_mode()

    def _show_settings(self, update_idx=True):
        if update_idx and 'SETTINGS' in self._sections:
            self._section_index = self._sections.index('SETTINGS')
            self._update_section_nav()
        self._transition_to(self.settings_view)

    def _show_account(self):
        self._transition_to(self.account_view)
        self.account_view.setFocus()

    def _show_library(self):
        self._transition_to(self.library_view)
        self.library_view.refresh()
        self.library_view.setFocus()
        
    def _show_quit(self):
        self.quit_container.show()
        self.quit_container.raise_()
        self.quit_dialog.btn_cancel.setFocus(Qt.PopupFocusReason)
        
    def _hide_quit(self):
        self.quit_container.hide()
        self.home._restore_focus()
        if QApplication.focusWidget() is None:
            self.home.setFocus()

    def _show_home(self, update_idx=True):
        if update_idx and 'HOME' in self._sections:
            self._section_index = self._sections.index('HOME')
            self._update_section_nav()
            self.home.platform_tab.set_current_tab(0)
        self._transition_to(self.home)
        self.home.setFocus()

    def _transition_to(self, widget):
        if self.stack.currentWidget() != widget:
            self.stack.setCurrentWidget(widget)
            self._update_sidebar_active(widget)

    def _update_sidebar_active(self, widget):
        if not hasattr(self, "nav_home"):
            return
        active = {
            self.nav_home: widget is self.home,
            self.nav_search: widget is self.search,
            self.nav_library: widget is self.library_view,
            self.nav_scan: False,
            self.nav_settings: widget is self.settings_view,
            self.nav_account: widget is self.account_view,
            self.nav_quit: False,
        }
        for button, selected in active.items():
            button.setProperty("active", selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _focus_sidebar(self, direction=1):
        """Activate the adjacent side-navigation destination from a trigger."""
        buttons = [self.nav_home, self.nav_search, self.nav_library, self.nav_settings, self.nav_account]
        current = QApplication.focusWidget()
        if current in buttons:
            index = buttons.index(current)
        else:
            active = self.stack.currentWidget()
            index = next((i for i, button in enumerate(buttons)
                          if (i == 0 and active is self.home)
                          or (i == 1 and active is self.search)
                          or (i == 2 and active is self.library_view)
                          or (i == 4 and active is self.settings_view)
                          or (i == 5 and active is self.account_view)), 0)
            index = (index + direction) % len(buttons)
        self.sidebar.set_expanded(True)
        # Trigger presses are direct navigation commands: activate the target
        # destination immediately instead of leaving focus on the navbar and
        # requiring a second arrow/confirm action.
        buttons[index].click()

    def refresh_theme(self):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        if hasattr(self, "_accent_cursor"):
            self._accent_cursor.set_accent(palette["ACCENT"])
        app = QApplication.instance()
        if app:
            qt_palette = app.palette()
            qt_palette.setColor(QPalette.Highlight, QColor(palette["ACCENT"]))
            qt_palette.setColor(QPalette.Link, QColor(palette["ACCENT2"]))
            app.setPalette(qt_palette)
        self.sidebar.setStyleSheet(
            f"_AutoHideSidebar {{ background: #000000; border-right: 1px solid {palette['SURFACE']}; }}"
        )
        self.sidebar._set_visual_state(self.sidebar._expanded)
        self._update_sidebar_active(self.stack.currentWidget())
        self.home.refresh_theme()
        if hasattr(self.loading, "refresh_theme"):
            self.loading.refresh_theme()
        if hasattr(self.search, "refresh_theme"):
            self.search.refresh_theme()

    def _launch_game(self, game_dict):
        minimize = config.settings.get("minimize_on_launch", False)
        if minimize:
            self.showMinimized()
        # If not minimizing, stay visible in fullscreen — no change needed

        try:
            if self._active_session:
                self._active_session.kill()
                
            launcher = EmulatorLauncher(
                str(config.emulators_file),
                resource_root=config.project_root,
            )
            process = launcher.launch(game_dict)
            
            if process:
                game_key = game_dict.get("key")
                self._active_session = GameSession(game_key, process)
                self._active_session.session_ended.connect(self._on_session_ended)
                self._active_session.start()
                
                self.home.set_now_playing(game_dict)
                
        except Exception as e:
            QMessageBox.warning(
                self,
                "Phasm",
                f"Could not launch {game_dict.get('title', 'game')}.\n\n{e}",
            )

            
    def _on_session_ended(self, game_key, duration):
        # Always restore the window - fullscreen if it was fullscreen before
        if self.isMinimized():
            if config.settings.get("fullscreen", True):
                self.showFullScreen()
            else:
                self.showNormal()
        
        # Re-activate so controller focus works immediately
        self.activateWindow()
        self.raise_()
        
        userdata.add_playtime(game_key, duration)
        
        # find the game dict
        game_dict = None
        for g in self.home.games:
            if g.get("key") == game_key:
                game_dict = g
                break
                
        if game_dict:
            userdata.add_recently_played(game_key, game_dict.get("title", ""), game_dict.get("platform", ""))
            
            pt_seconds = userdata.get_playtime(game_key)
            mins = pt_seconds // 60
            if mins < 1:
                pt_str = "<1m"
            elif mins < 60:
                pt_str = f"{mins}m"
            else:
                h = mins // 60
                m = mins % 60
                if m == 0:
                    pt_str = f"{h}h"
                else:
                    pt_str = f"{h}h {m}m"
            
            self.home.set_now_playing(None)
            self.home.status_playing.setText(f"[ {game_dict.get('title')} ] — played {int(duration // 60)} min")
            
        self._active_session = None
        self.home.setFocus()
        self.home._build_home_tab() # Refresh recent tab


    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()

        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
                config.settings["fullscreen"] = False
            else:
                self.showFullScreen()
                config.settings["fullscreen"] = True
            config.save_settings()

        elif key == Qt.Key_F and (mod & Qt.ControlModifier):
            if self.stack.currentWidget() == self.home:
                self._show_search()

        elif key == Qt.Key_S and not (mod & Qt.ControlModifier) and not (mod & Qt.AltModifier):
            if self.stack.currentWidget() == self.home:
                self._show_settings()

        elif key == Qt.Key_Escape:
            cur = self.stack.currentWidget()
            # Escape/B is never a quit command. Quit is intentionally limited
            # to the navbar mouse button and controller Menu/Start (Ctrl+Esc).
            if cur != self.home:
                self._show_home()
            else:
                super().keyPressEvent(event)

        else:
            super().keyPressEvent(event)
