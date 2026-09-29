from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget, QAbstractSpinBox,
                               QPushButton, QScrollArea, QLineEdit, QCheckBox,
                               QFileDialog, QSpinBox, QColorDialog)
from PySide6.QtWidgets import QSlider, QApplication
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QPoint, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QImage
from core.config import config
from core import userdata
from ui.sound_manager import sound_manager
from ui.theme import ACCENT_PRESETS, accent_text_color, get_stylesheet, get_theme_colors


class _ColorWheel(QWidget):
    changed = Signal(QColor)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._wheel_image = None
        self._wheel_image_key = None
        self.setMinimumSize(260, 260)
        self.setMouseTracking(True)

    def set_color(self, color):
        self._color = QColor(color)
        if self._wheel_image_key != (self.size(), max(1, self._color.value())):
            self._wheel_image = None
        self.update()

    def color(self):
        return QColor(self._color)

    def _pick(self, point):
        center = self.rect().center()
        radius = min(self.width(), self.height()) * 0.44
        dx = point.x() - center.x()
        dy = point.y() - center.y()
        distance = min(radius, max(0.0, (dx * dx + dy * dy) ** 0.5))
        hue = int((__import__('math').degrees(__import__('math').atan2(dy, dx)) + 90) % 360)
        saturation = int(max(0.0, min(1.0, distance / radius)) * 255)
        self._color = QColor.fromHsv(hue, saturation, max(1, self._color.value()), self._color.alpha())
        self.changed.emit(self._color)
        self.update()

    def mousePressEvent(self, event):
        self._pick(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position().toPoint())

    def paintEvent(self, event):
        painter = QPainter(self)
        center = self.rect().center()
        radius = min(self.width(), self.height()) * 0.44
        # Paint the same HSV model used by _pick(). The old conical/radial
        # gradient stack only approximated HSV: its translucent black edge
        # made the displayed color darker than the selected QColor.
        value = max(1, self._color.value())
        image_key = (self.size(), value)
        if self._wheel_image_key != image_key:
            image = QImage(self.size(), QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            radius_squared = radius * radius
            left = max(0, int(center.x() - radius))
            right = min(self.width() - 1, int(center.x() + radius))
            top = max(0, int(center.y() - radius))
            bottom = min(self.height() - 1, int(center.y() + radius))
            for y in range(top, bottom + 1):
                dy = y - center.y()
                for x in range(left, right + 1):
                    dx = x - center.x()
                    distance_squared = dx * dx + dy * dy
                    if distance_squared > radius_squared:
                        continue
                    distance = distance_squared ** 0.5
                    hue = int((__import__('math').degrees(__import__('math').atan2(dy, dx)) + 90) % 360)
                    saturation = int(min(1.0, distance / radius) * 255)
                    image.setPixelColor(x, y, QColor.fromHsv(hue, saturation, value))
            self._wheel_image = image
            self._wheel_image_key = image_key
        else:
            image = self._wheel_image
        painter.drawImage(0, 0, image)
        hue = self._color.hue() if self._color.hue() >= 0 else 0
        sat = self._color.saturationF()
        angle = __import__('math').radians(hue - 90)
        marker = QPointF(center) + QPointF(__import__('math').cos(angle) * radius * sat,
                                           __import__('math').sin(angle) * radius * sat)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("white"), 3))
        painter.drawEllipse(marker, 8, 8)
        painter.setPen(QPen(QColor("black"), 1))
        painter.drawEllipse(marker, 10, 10)
        painter.end()


class _AccentPickerOverlay(QWidget):
    finished = Signal(bool, QColor)

    def __init__(self, initial, palette, parent=None):
        super().__init__(parent)
        self._color = QColor(initial)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#accentPicker {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 12px; }}"
            f"QLabel {{ color: {palette['TEXT']}; }}"
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; border: 1px solid {palette['PANEL']}; border-radius: 7px; padding: 9px 16px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; border-color: {palette['ACCENT2']}; }}"
        )
        self.setObjectName("accentPicker")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        title = QLabel("CHOOSE ACCENT COLOR")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {palette['ACCENT2']}; letter-spacing: 1px;")
        layout.addWidget(title)
        self.wheel = _ColorWheel(self._color, self)
        self.wheel.changed.connect(self._color_changed)
        layout.addWidget(self.wheel, 1, Qt.AlignCenter)
        self.preview = QLabel(self._color.name(QColor.HexRgb).upper())
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"background: {self._color.name()}; color: {accent_text_color(self._color.name())}; padding: 9px; border-radius: 6px; font-weight: bold;")
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(lambda: self.finished.emit(False, self._color))
        apply = QPushButton("APPLY")
        apply.clicked.connect(lambda: self.finished.emit(True, self._color))
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        layout.addLayout(buttons)

    def _color_changed(self, color):
        self._color = QColor(color)
        self.preview.setText(self._color.name(QColor.HexRgb).upper())
        self.preview.setStyleSheet(f"background: {self._color.name()}; color: {accent_text_color(self._color.name())}; padding: 9px; border-radius: 6px; font-weight: bold;")


class _OptionOverlay(QWidget):
    def __init__(self, host, target, options, palette):
        super().__init__(host)
        self.host = host
        self.target = target
        self.options = options
        self._previous_focus = QApplication.focusWidget()
        self.setStyleSheet("background: transparent;")
        self.panel = QFrame(self)
        self.panel.setObjectName("settingsOptions")
        self.panel.setFixedWidth(max(280, target.width()))
        self.panel.setStyleSheet(
            f"QFrame#settingsOptions {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 8px; }}"
            f"QPushButton {{ background: transparent; color: {palette['TEXT']}; border: none; border-radius: 6px; padding: 10px 12px; text-align: left; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
        )
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(6, 6, 6, 6)
        for index, option in enumerate(options):
            button = QPushButton(option, self.panel)
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(lambda checked=False, i=index: self._select(i))
            layout.addWidget(button)

    def open_at(self):
        self.setGeometry(self.host.rect())
        point = self.mapFromGlobal(self.target.mapToGlobal(QPoint(0, self.target.height() + 6)))
        self.panel.adjustSize()
        self.panel.move(max(8, min(point.x(), self.width() - self.panel.width() - 8)),
                        max(8, min(point.y(), self.height() - self.panel.height() - 8)))
        self.show()
        self.raise_()
        self.panel.findChild(QPushButton).setFocus(Qt.PopupFocusReason)

    def _select(self, index):
        self.target._set_index(index)
        self.close_overlay()

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.close_overlay()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
            event.accept()
            return
        super().keyPressEvent(event)

    def close_overlay(self):
        if getattr(self.host, "_settings_option_overlay", None) is self:
            self.host._settings_option_overlay = None
        if self._previous_focus is not None and self._previous_focus.isVisible():
            self._previous_focus.setFocus(Qt.OtherFocusReason)
        self.deleteLater()


class _InAppSelect(QPushButton):
    currentIndexChanged = Signal(int)

    def __init__(self, host, options, parent=None):
        super().__init__(parent or host)
        self._host = host
        self._options = list(options)
        self._index = 0
        self.setFocusPolicy(Qt.StrongFocus)
        self.clicked.connect(self._open_options)
        self._refresh_text()

    def addItems(self, options):
        self._options.extend(options)
        self._refresh_text()

    def setCurrentIndex(self, index):
        self._set_index(index, emit=False)

    def currentIndex(self):
        return self._index

    def _set_index(self, index, emit=True):
        self._index = max(0, min(len(self._options) - 1, int(index)))
        self._refresh_text()
        if emit:
            self.currentIndexChanged.emit(self._index)

    def _refresh_text(self):
        if self._options:
            self.setText(self._options[self._index])

    def _open_options(self):
        old = getattr(self._host, "_settings_option_overlay", None)
        if old is not None:
            old.close_overlay()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        overlay = _OptionOverlay(self._host, self, self._options, palette)
        self._host._settings_option_overlay = overlay
        overlay.open_at()

    def wheelEvent(self, event):
        # Selector values should change only through the in-app option panel.
        event.ignore()


class _NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        # Prevent accidental value changes while the pointer is passing over
        # the compact hero dimension controls.
        event.ignore()

class SettingsView(QWidget):
    closed = Signal()
    rescan_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 28, 28, 24)
        
        header_layout = QHBoxLayout()
        title = QLabel("SETTINGS")
        title.setStyleSheet("font-size: 30px; font-weight: bold; letter-spacing: 3px; color: #f8fafc;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFocusPolicy(Qt.NoFocus)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(8, 8, 16, 20)
        self.layout.setSpacing(20)
        content.setMinimumWidth(0)
        self.scroll.setWidget(content)
        main_layout.addWidget(self.scroll)
        # Retain section labels for programmatic scrolling; the old icon
        # shortcut row was removed from the visible settings UI.
        self._section_labels = {}

        self._build_ui()
        self._organize_settings_tabs()
        self._style_settings_controls()
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(260)
        self._settings_save_timer.timeout.connect(self._auto_save)
        self._toggle_boxes = self.findChildren(QCheckBox)
        for toggle in self._toggle_boxes:
            toggle.stateChanged.connect(lambda state, control=toggle: self._update_toggle_color(control, state))
            self._update_toggle_color(toggle, toggle.checkState())
        
        self._connect_auto_save()
        

    def _build_ui(self):
        self._add_section("GAME LIBRARIES")
        self.lib_inputs = {}
        for p in ["PS2", "PS3", "PS4", "Switch"]:
            row = QHBoxLayout()
            label = QLabel(f"{p} Library:")
            label.setFixedWidth(130)
            row.addWidget(label)
            current_library = config.library.get("libraries", {}).get(p, "")
            if isinstance(current_library, (list, tuple)):
                current_library = current_library[0] if current_library else ""
            inp = QLineEdit(str(current_library))
            inp.setFocusPolicy(Qt.StrongFocus)
            inp.setMinimumWidth(0)
            row.addWidget(inp, 1)
            btn_br = QPushButton("📁")
            btn_br.setToolTip("Choose library folder")
            btn_br.setAccessibleName(f"Choose {p} library folder")
            btn_br.setCursor(Qt.PointingHandCursor)
            btn_br.setFixedWidth(50)
            btn_br.setFocusPolicy(Qt.StrongFocus)
            btn_br.clicked.connect(lambda checked, i=inp: self._browse_dir(i))
            row.addWidget(btn_br)
            self.lib_inputs[p] = inp
            self.layout.addLayout(row)

        self._add_section("EMULATORS")
        self.emu_inputs = {}
        for p in ["PS2", "PS3", "PS4", "Switch"]:
            row = QHBoxLayout()
            label = QLabel(f"{p} Emulator:")
            label.setFixedWidth(130)
            row.addWidget(label)
            inp = QLineEdit(config.emulators.get(p, ""))
            inp.setFocusPolicy(Qt.StrongFocus)
            inp.setMinimumWidth(0)
            row.addWidget(inp, 1)
            btn_br = QPushButton("📁")
            btn_br.setToolTip("Choose emulator executable")
            btn_br.setAccessibleName(f"Choose {p} emulator executable")
            btn_br.setCursor(Qt.PointingHandCursor)
            btn_br.setFixedWidth(50)
            btn_br.setFocusPolicy(Qt.StrongFocus)
            btn_br.clicked.connect(lambda checked, i=inp: self._browse_file(i))
            row.addWidget(btn_br)
            self.emu_inputs[p] = inp
            self.layout.addLayout(row)

        self._add_section("APPEARANCE")
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Accent:"))
        self.accent_select = QPushButton()
        self.accent_select.setText("CHOOSE COLOR")
        self.accent_select.setFocusPolicy(Qt.StrongFocus)
        self.accent_select.clicked.connect(self._choose_accent)
        self._set_accent_button(config.settings.get("accent", "#7c3aed"))
        theme_row.addWidget(self.accent_select, 1)
        self.layout.addLayout(theme_row)

        self.chk_fs = QCheckBox("Fullscreen Mode")
        self.chk_fs.setChecked(config.settings.get("fullscreen", True))
        self.chk_fs.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.chk_fs)

        self.chk_custom_cursor = QCheckBox("Use custom accent cursor")
        self.chk_custom_cursor.setChecked(config.settings.get("custom_cursor", True))
        self.chk_custom_cursor.setFocusPolicy(Qt.StrongFocus)
        self.chk_custom_cursor.stateChanged.connect(self._custom_cursor_changed)
        self.layout.addWidget(self.chk_custom_cursor)
        
        row = QHBoxLayout()
        label = QLabel("SteamGridDB API Key:")
        label.setFixedWidth(150)
        row.addWidget(label)
        self.inp_api = QLineEdit(config.settings.get("steamgriddb", {}).get("api_key", ""))
        self.inp_api.setFocusPolicy(Qt.StrongFocus)
        self.inp_api.setMinimumWidth(0)
        row.addWidget(self.inp_api, 1)
        self.chk_sgdb = QCheckBox("Enable SteamGridDB")
        self.chk_sgdb.setChecked(config.settings.get("steamgriddb", {}).get("enabled", False))
        self.chk_sgdb.setFocusPolicy(Qt.StrongFocus)
        self.layout.addLayout(row)
        self.layout.addWidget(self.chk_sgdb)

        rawg_row = QHBoxLayout()
        rawg_label = QLabel("RAWG API Key:")
        rawg_label.setFixedWidth(150)
        rawg_row.addWidget(rawg_label)
        self.inp_rawg = QLineEdit(config.settings.get("rawg", {}).get("api_key", ""))
        self.inp_rawg.setEchoMode(QLineEdit.Password)
        self.inp_rawg.setMinimumWidth(0)
        rawg_row.addWidget(self.inp_rawg, 1)
        self.chk_rawg = QCheckBox("Enable RAWG metadata")
        self.chk_rawg.setChecked(config.settings.get("rawg", {}).get("enabled", False))
        self.chk_rawg.setFocusPolicy(Qt.StrongFocus)
        self.layout.addLayout(rawg_row)
        self.layout.addWidget(self.chk_rawg)
        attribution = QLabel("RAWG data is free for personal use with attribution and a "
                             "<a href='https://rawg.io/apidocs'>RAWG backlink</a>.")
        attribution.setOpenExternalLinks(True)
        attribution.setStyleSheet("color: #8b7aa8; font-size: 11px;")
        self.layout.addWidget(attribution)

        self._add_section("HERO DISPLAY")
        hero_row = QVBoxLayout()
        orientation_row = QHBoxLayout()
        orientation_row.addWidget(QLabel("Orientation:"))
        self.hero_orientation = _InAppSelect(self, ["Vertical side panel", "Horizontal banner"])
        self.hero_orientation.setCurrentIndex(0 if config.settings.get("hero_orientation", "vertical") == "vertical" else 1)
        orientation_row.addWidget(self.hero_orientation, 1)
        hero_row.addLayout(orientation_row)
        self.layout.addLayout(hero_row)

        self._add_section("SOUND")
        sound_cfg = config.settings.get("sound", {})
        effects_cfg = sound_cfg.get("effects", {})
        music_cfg = sound_cfg.get("music", {})
        legacy_volume = int(sound_cfg.get("volume", 80))

        effects_row = QHBoxLayout()
        effects_row.addWidget(QLabel("Sound effects volume:"))
        self.effects_volume = QSlider(Qt.Horizontal)
        self.effects_volume.setRange(0, 100)
        self.effects_volume.setValue(int(effects_cfg.get("volume", legacy_volume)))
        self.effects_volume.setFocusPolicy(Qt.StrongFocus)
        effects_row.addWidget(self.effects_volume, 1)
        self.effects_volume_value = QLabel(f"{self.effects_volume.value()}%")
        self.effects_volume.valueChanged.connect(lambda value: self.effects_volume_value.setText(f"{value}%"))
        effects_row.addWidget(self.effects_volume_value)
        self.layout.addLayout(effects_row)
        self.chk_effects = QCheckBox("Enable sound effects")
        self.chk_effects.setChecked(effects_cfg.get("enabled", sound_cfg.get("enabled", True)))
        self.chk_effects.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.chk_effects)

        music_row = QHBoxLayout()
        music_row.addWidget(QLabel("Music volume:"))
        self.music_volume = QSlider(Qt.Horizontal)
        self.music_volume.setRange(0, 100)
        self.music_volume.setValue(int(music_cfg.get("volume", 60)))
        self.music_volume.setFocusPolicy(Qt.StrongFocus)
        music_row.addWidget(self.music_volume, 1)
        self.music_volume_value = QLabel(f"{self.music_volume.value()}%")
        self.music_volume.valueChanged.connect(lambda value: self.music_volume_value.setText(f"{value}%"))
        music_row.addWidget(self.music_volume_value)
        self.layout.addLayout(music_row)
        self.chk_music = QCheckBox("Enable music / ambience")
        self.chk_music.setChecked(music_cfg.get("enabled", True))
        self.chk_music.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.chk_music)

        self._add_section("GENERAL")
        self.chk_min = QCheckBox("Minimize on Launch")
        self.chk_min.setChecked(config.settings.get("minimize_on_launch", False))
        self.chk_min.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.chk_min)
        
        self._add_section("PLAYTIME")
        self.btn_clear_pt = QPushButton("♻")
        self.btn_clear_pt.setFixedSize(52, 44)
        self.btn_clear_pt.setToolTip("Clear playtime data")
        self.btn_clear_pt.setAccessibleName("Clear playtime data")
        self.btn_clear_pt.setCursor(Qt.PointingHandCursor)
        self.btn_clear_pt.setFocusPolicy(Qt.StrongFocus)
        self.btn_clear_pt.setStyleSheet("background-color: #7f1d1d; color: white; padding: 10px;")
        self.btn_clear_pt.clicked.connect(self._clear_playtime)
        self.layout.addWidget(self.btn_clear_pt)

        self.layout.addStretch()

    def _organize_settings_tabs(self):
        """Move the existing settings sections into focused modern tabs."""
        groups = {
            "LIBRARIES": "LIBRARY",
            "EMULATORS": "LIBRARY",
            "APPEARANCE": "APPEARANCE",
            "HERO DISPLAY": "APPEARANCE",
            "SOUND": "AUDIO",
            "GENERAL": "GENERAL",
            "PLAYTIME": "GENERAL",
        }
        pages = {}
        page_layouts = {}
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        for name in ("LIBRARY", "APPEARANCE", "AUDIO", "GENERAL"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(12, 6, 12, 12)
            page_layout.setSpacing(8)
            pages[name] = page
            page_layouts[name] = page_layout
            tabs.addTab(page, name)

        current = "LIBRARY"
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                section_name = next((name for name, label in self._section_labels.items() if label is widget), None)
                if section_name in groups:
                    current = groups[section_name]
                page_layouts[current].addWidget(widget)
            elif item.layout() is not None:
                page_layouts[current].addLayout(item.layout())
            elif item.spacerItem() is not None:
                page_layouts[current].addItem(item)
        self.layout.addWidget(tabs)
        self._settings_tabs = tabs
        self._settings_pages = pages
        page_layouts["AUDIO"].setContentsMargins(12, 2, 12, 10)
        page_layouts["AUDIO"].setSpacing(5)

    def _add_section(self, text):
        lbl = QLabel(text)
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        lbl.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {palette['ACCENT2']}; "
            "letter-spacing: 2px; margin-top: 8px; padding-bottom: 6px; "
            f"border-bottom: 1px solid {palette['PANEL']};"
        )
        self.layout.addWidget(lbl)
        self._section_labels[text] = lbl

    def _preview_theme(self):
        config.settings["accent"] = self.accent_select.property("accentHex") or "#7c3aed"
        config.settings["background_mode"] = "hero_full"
        QApplication.instance().setStyleSheet(get_stylesheet())
        window = self.window()
        if hasattr(window, "refresh_theme"):
            window.refresh_theme()
        for toggle in getattr(self, "_toggle_boxes", []):
            self._update_toggle_color(toggle, toggle.checkState())
        self._style_settings_controls()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        for label in self._section_labels.values():
            section_name = next((name for name, item in self._section_labels.items() if item is label), "")
            margin = 0 if section_name in {"LIBRARIES", "APPEARANCE", "SOUND", "GENERAL"} else 6
            label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {palette['ACCENT2']}; "
                f"letter-spacing: 2px; margin-top: {margin}px; padding-bottom: 5px; "
                f"border-bottom: 1px solid {palette['PANEL']};"
            )
        home = getattr(window, "home", None)
        if home:
            home.refresh_theme()
            for row in home._rows:
                for card in getattr(row, "cards", []):
                    card.inner.update()
        self._auto_save()

    def _connect_auto_save(self):
        """Persist each setting as soon as its control changes."""
        for inp in self.lib_inputs.values():
            inp.editingFinished.connect(lambda: self._auto_save(rescan=True))
        for inp in self.emu_inputs.values():
            inp.editingFinished.connect(self._auto_save)
        for control in (
            self.chk_fs, self.chk_sgdb, self.chk_rawg, self.chk_effects,
            self.chk_music, self.chk_min,
        ):
            control.stateChanged.connect(lambda _state: self._auto_save())
        for control in (self.inp_api, self.inp_rawg):
            control.textChanged.connect(lambda _text: self._auto_save())
        self.hero_orientation.currentIndexChanged.connect(lambda _value: self._auto_save())
        for control in (self.effects_volume, self.music_volume):
            control.valueChanged.connect(lambda _value: self._queue_auto_save())

    def _update_toggle_color(self, control, state):
        checked = bool(state)
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        color = palette["ACCENT"] if checked else palette["SURFACE"]
        border = palette["ACCENT2"] if checked else palette["TEXT_DIM"]
        control.setStyleSheet(
            "QCheckBox { spacing: 10px; color: #e2e8f0; }"
            f"QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 10px; "
            f"background: {color}; border: 2px solid {border}; }}"
        )

    def _style_settings_controls(self):
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        accent_text = palette["ACCENT_TEXT"]
        first_sections = {"LIBRARIES", "APPEARANCE", "SOUND", "GENERAL"}
        for name, label in self._section_labels.items():
            margin = 0 if name in first_sections else 6
            label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {palette['ACCENT2']}; "
                f"letter-spacing: 2px; margin-top: {margin}px; padding-bottom: 5px; "
                f"border-bottom: 1px solid {palette['PANEL']};"
            )
        line_style = (
            f"QLineEdit {{ background: rgba(0, 0, 0, 153); color: {palette['TEXT']}; "
            f"border: 1px solid {palette['PANEL']}; border-radius: 7px; padding: 9px 12px; }}"
            f"QLineEdit:focus {{ border: 2px solid {palette['ACCENT']}; }}"
        )
        spin_style = (
            f"QSpinBox {{ background: rgba(0, 0, 0, 153); color: {palette['TEXT']}; "
            f"border: 1px solid {palette['PANEL']}; border-radius: 7px; padding: 5px 6px; font-size: 13px; min-width: 0px; }}"
            f"QSpinBox:focus {{ border: 2px solid {palette['ACCENT']}; }}"
            f"QSpinBox QLineEdit {{ color: {palette['TEXT']}; background: transparent; padding: 0px; font-size: 13px; }}"
        )
        slider_style = (
            f"QSlider::groove:horizontal {{ background: rgba(0, 0, 0, 153); height: 7px; border-radius: 4px; }}"
            f"QSlider::handle:horizontal {{ background: {palette['ACCENT']}; width: 24px; height: 24px; margin: -9px 0; border-radius: 12px; border: 2px solid {accent_text}; }}"
            f"QSlider::sub-page:horizontal {{ background: {palette['ACCENT']}; border-radius: 4px; }}"
        )
        for control in self.findChildren(QLineEdit):
            control.setStyleSheet(line_style)
        for control in self.findChildren(QSpinBox):
            control.setStyleSheet(spin_style)
        for control in self.findChildren(QSlider):
            control.setMinimumHeight(32)
            control.setStyleSheet(slider_style)
        if hasattr(self, "_settings_tabs"):
            self._settings_tabs.setStyleSheet(
                f"QTabWidget::pane {{ background: rgba(0, 0, 0, 80); border: 1px solid {palette['PANEL']}; border-radius: 10px; }}"
                f"QTabBar::tab {{ background: rgba(0, 0, 0, 120); color: {palette['TEXT_DIM']}; padding: 11px 18px; margin-right: 4px; border-radius: 7px; font-weight: bold; }}"
                f"QTabBar::tab:selected, QTabBar::tab:hover {{ background: {palette['ACCENT']}; color: {accent_text}; }}"
            )
        self.hero_orientation.setStyleSheet(
            f"QPushButton {{ background: rgba(0, 0, 0, 153); color: {palette['TEXT']}; "
            f"border: 1px solid {palette['PANEL']}; border-radius: 7px; padding: 8px 12px; text-align: left; font-size: 13px; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {accent_text}; border-color: {palette['ACCENT2']}; }}"
        )

    def _queue_auto_save(self):
        self._settings_save_timer.start()

    def _custom_cursor_changed(self, state):
        enabled = bool(state)
        config.settings["custom_cursor"] = enabled
        window = self.window()
        if hasattr(window, "set_custom_cursor_enabled"):
            window.set_custom_cursor_enabled(enabled)
        self._update_toggle_color(self.chk_custom_cursor, state)
        self._auto_save()

    def _set_accent_button(self, value):
        if str(value) in ACCENT_PRESETS:
            value = ACCENT_PRESETS[str(value)][0]
        color = QColor(str(value))
        if not color.isValid():
            color = QColor("#7c3aed")
        hex_color = color.name(QColor.HexArgb if color.alpha() < 255 else QColor.HexRgb).upper()
        self.accent_select.setProperty("accentHex", hex_color)
        self.accent_select.setText(hex_color)
        self.accent_select.setStyleSheet(
            f"QPushButton {{ background: {hex_color}; color: {accent_text_color(hex_color)}; border: 1px solid white; "
            "font-weight: bold; padding: 8px 14px; }"
            f"QPushButton:hover, QPushButton:focus {{ background: {color.lighter(115).name(QColor.HexRgb)}; }}"
        )

    def _choose_accent(self):
        current = QColor(self.accent_select.property("accentHex") or "#7c3aed")
        old_dialog = getattr(self, "_color_dialog", None)
        if old_dialog is not None and old_dialog.isVisible():
            old_dialog.raise_()
            return
        previous_focus = QApplication.focusWidget()
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        dialog = _AccentPickerOverlay(current, palette, self)
        dialog.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        dialog.setGeometry(self.rect().adjusted(
            max(20, self.width() // 5), max(20, self.height() // 6),
            -max(20, self.width() // 5), -max(20, self.height() // 6),
        ))
        self._color_dialog = dialog

        def finish(result):
            if result:
                color = dialog._color
                self._set_accent_button(color.name(QColor.HexArgb) if color.alpha() < 255 else color.name())
                self._preview_theme()
            self._color_dialog = None
            if previous_focus is not None and previous_focus.isVisible() and previous_focus.isEnabled():
                previous_focus.setFocus(Qt.OtherFocusReason)
            dialog.deleteLater()

        dialog.finished.connect(finish)
        dialog.show()
        dialog.raise_()
        dialog.setFocus()

    def _jump_to_section(self, name):
        label = self._section_labels.get(name)
        if label:
            self.scroll.ensureWidgetVisible(label, 0, 18)
        
    def _clear_playtime(self):
        userdata.clear_playtime()

    def _browse_dir(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text() or "/")
        if d:
            line_edit.setText(d)
            self._auto_save(rescan=True)

    def _browse_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(self, "Select File", line_edit.text() or "/")
        if f:
            line_edit.setText(f)
            self._auto_save()

    def _auto_save(self, rescan=False):
        self.save_settings(rescan=rescan, close=False)

    def save_settings(self, rescan=True, close=False):
        new_libs = {}
        old_libs = config.library.get("libraries", {})
        for p, inp in self.lib_inputs.items():
            if inp.text().strip():
                value = inp.text().strip()
                previous = old_libs.get(p, "")
                if isinstance(previous, (list, tuple)) and previous:
                    new_libs[p] = [value, *[str(folder) for folder in previous[1:]]]
                else:
                    new_libs[p] = value
        config.library["libraries"] = new_libs
        
        for p, inp in self.emu_inputs.items():
            if inp.text().strip():
                config.emulators[p] = inp.text().strip()
                
        config.settings["fullscreen"] = self.chk_fs.isChecked()
        config.settings["custom_cursor"] = self.chk_custom_cursor.isChecked()
        config.settings["minimize_on_launch"] = self.chk_min.isChecked()
        config.settings["hero_orientation"] = "vertical" if self.hero_orientation.currentIndex() == 0 else "horizontal"
        config.settings["accent"] = self.accent_select.property("accentHex") or "#7c3aed"
        config.settings["background_mode"] = "hero_full"
        config.settings["sound"] = {
            "enabled": self.chk_effects.isChecked(),
            "volume": self.effects_volume.value(),
            "effects": {
                "enabled": self.chk_effects.isChecked(),
                "volume": self.effects_volume.value(),
            },
            "music": {
                "enabled": self.chk_music.isChecked(),
                "volume": self.music_volume.value(),
            },
        }
        sound_manager.set_effects_volume(self.effects_volume.value())
        sound_manager.set_effects_enabled(self.chk_effects.isChecked())
        sound_manager.set_music_volume(self.music_volume.value())
        sound_manager.set_music_enabled(self.chk_music.isChecked())
        QApplication.instance().setStyleSheet(get_stylesheet())
        # The application stylesheet is refreshed on every auto-save. Reapply
        # the compact settings control metrics afterward so spin-box text does
        # not regain the larger global padding while editing.
        self._style_settings_controls()
        
        sgdb = config.settings.get("steamgriddb", {})
        sgdb["api_key"] = self.inp_api.text().strip()
        sgdb["enabled"] = self.chk_sgdb.isChecked()
        config.settings["steamgriddb"] = sgdb
        config.settings["rawg"] = {
            "api_key": self.inp_rawg.text().strip(),
            "enabled": self.chk_rawg.isChecked(),
        }

        config.save_library()
        config.save_emulators()
        config.save_settings()
        
        window = self.window()
        if window is not None and hasattr(window, "home"):
            if self.chk_fs.isChecked() and not window.isFullScreen():
                window.showFullScreen()
            elif not self.chk_fs.isChecked() and window.isFullScreen():
                window.showNormal()
            window.home.apply_hero_settings(
                config.settings.get("hero_orientation", "vertical"),
                config.settings.get("hero_width", 360),
                config.settings.get("hero_height", 260),
            )
        if rescan:
            self.rescan_requested.emit()
        if close:
            self.closed.emit()

    def close_settings(self):
        self.closed.emit()

    def scroll_by_page(self, direction):
        bar = self.scroll.verticalScrollBar()
        amount = max(80, self.scroll.viewport().height() * 2 // 3)
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(260)
        animation.setStartValue(bar.value())
        animation.setEndValue(bar.value() + direction * amount)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation = animation
        animation.start()

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self.close_settings()
        elif k == Qt.Key_Up:
            self.focusPreviousChild()
            self.scroll.ensureWidgetVisible(self.focusWidget())
        elif k == Qt.Key_Down:
            self.focusNextChild()
            self.scroll.ensureWidgetVisible(self.focusWidget())
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            fw = self.focusWidget()
            if isinstance(fw, QPushButton):
                fw.click()
            elif isinstance(fw, QCheckBox):
                fw.toggle()
        else:
            super().keyPressEvent(event)
