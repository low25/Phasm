from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import config
from ui.theme import get_theme_colors


PLATFORMS = ("PS1", "PS2", "PS3", "PS4", "Switch")


class LibraryView(QWidget):
    """Manage multiple folders per platform."""

    rescan_requested = Signal()
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.folder_lists = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("GAME LIBRARY")
        title.setStyleSheet("font-size: 24px; font-weight: bold; letter-spacing: 2px; color: #f8fafc;")
        header.addWidget(title)
        header.addStretch()
        back = QPushButton("←  BACK")
        back.setFocusPolicy(Qt.StrongFocus)
        back.clicked.connect(self.closed.emit)
        header.addWidget(back)
        layout.addLayout(header)

        self.folder_panel = QGridLayout()
        self.folder_panel.setHorizontalSpacing(10)
        self.folder_panel.setVerticalSpacing(10)
        layout.addLayout(self.folder_panel)
        self.refresh_theme()
        self.refresh()

    def refresh(self):
        while self.folder_panel.count():
            item = self.folder_panel.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.folder_lists.clear()
        libraries = config.library.setdefault("libraries", {})
        for platform in PLATFORMS:
            row = QFrame()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 7, 10, 7)
            row_layout.setSpacing(5)
            title_row = QHBoxLayout()
            label = QLabel(f"{platform} FOLDERS")
            label.setStyleSheet("font-weight: bold; letter-spacing: 1.5px; color: #f8fafc;")
            title_row.addWidget(label)
            title_row.addStretch()
            add = QPushButton("+ ADD FOLDER")
            add.setFixedHeight(28)
            add.setFocusPolicy(Qt.StrongFocus)
            add.clicked.connect(lambda checked=False, p=platform: self._add_folder(p))
            title_row.addWidget(add)
            remove = QPushButton("REMOVE")
            remove.setFixedHeight(28)
            remove.setFocusPolicy(Qt.StrongFocus)
            remove.clicked.connect(lambda checked=False, p=platform: self._remove_folder(p))
            title_row.addWidget(remove)
            row_layout.addLayout(title_row)

            listing = QListWidget()
            listing.setFocusPolicy(Qt.StrongFocus)
            listing.setMinimumHeight(62)
            listing.setMaximumHeight(76)
            values = libraries.get(platform, [])
            if isinstance(values, str):
                values = [values] if values else []
            for folder in values:
                listing.addItem(str(folder))
            row_layout.addWidget(listing)
            self.folder_lists[platform] = listing
            row.setMinimumHeight(116)
            position = PLATFORMS.index(platform)
            self.folder_panel.addWidget(row, position // 2, position % 2)
        self.folder_panel.setColumnStretch(0, 1)
        self.folder_panel.setColumnStretch(1, 1)

    def refresh_theme(self):
        colors = get_theme_colors(accent_name=config.settings.get("accent"))
        self.setStyleSheet(
            f"QLabel {{ color: {colors['TEXT']}; }} QListWidget {{ background: {colors['BG']}; color: {colors['TEXT']}; border: 1px solid {colors['PANEL']}; border-radius: 0px; padding: 2px; }}"
            f"QListWidget::item {{ padding: 3px 5px; }} QListWidget::item:selected {{ background: {colors['ACCENT']}; color: white; }}"
            f"QPushButton {{ background: {colors['SURFACE']}; color: {colors['TEXT']}; border: 1px solid {colors['ACCENT']}; border-radius: 2px; padding: 5px 9px; font-size: 11px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {colors['ACCENT']}; color: white; }}"
            f"QFrame {{ background: {colors['SURFACE']}; border: 1px solid {colors['PANEL']}; border-radius: 0px; }}"
        )
    def _add_folder(self, platform):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        folder = QFileDialog.getExistingDirectory(
            self, f"Add {platform} Game Folder", "", options=options
        )
        if folder:
            listing = self.folder_lists[platform]
            if folder not in [listing.item(i).text() for i in range(listing.count())]:
                listing.addItem(folder)
            self._save_folders()

    def _remove_folder(self, platform):
        listing = self.folder_lists[platform]
        row = listing.currentRow()
        if row >= 0:
            listing.takeItem(row)
            self._save_folders()

    def _save_folders(self):
        libraries = {}
        for platform, listing in self.folder_lists.items():
            values = [listing.item(i).text().strip() for i in range(listing.count()) if listing.item(i).text().strip()]
            if values:
                libraries[platform] = values
        config.library["libraries"] = libraries
        config.save_library()


    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
