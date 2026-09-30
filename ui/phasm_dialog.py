from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.config import config
from ui.theme import get_theme_colors


class PhasmMessageDialog(QDialog):
    """Frameless, application-modal message/confirmation dialog."""

    def __init__(self, parent, title, message, confirm=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("phasmMessageDialog")
        palette = get_theme_colors(accent_name=config.settings.get("accent"))
        self.setStyleSheet(
            f"QDialog#phasmMessageDialog {{ background: {palette['PANEL']}; border: 1px solid {palette['ACCENT']}; border-radius: 14px; }}"
            f"QLabel {{ color: {palette['TEXT']}; }} QLabel#dialogTitle {{ color: {palette['ACCENT2']}; font-size: 19px; font-weight: bold; letter-spacing: 1px; }}"
            f"QPushButton {{ background: {palette['SURFACE']}; color: {palette['TEXT']}; border: 1px solid {palette['ACCENT']}; border-radius: 7px; padding: 8px 18px; font-weight: bold; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {palette['ACCENT']}; color: {palette['ACCENT_TEXT']}; }}"
        )
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        heading = QLabel(str(title).upper())
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        body = QLabel(str(message))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setMinimumHeight(52)
        layout.addWidget(body)
        buttons = QHBoxLayout()
        buttons.addStretch()
        if confirm:
            cancel = QPushButton("CANCEL")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)
        action = QPushButton("YES" if confirm else "OK")
        action.setDefault(True)
        action.clicked.connect(self.accept)
        buttons.addWidget(action)
        layout.addLayout(buttons)
        action.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.adjustSize()
            self.move(parent.geometry().center() - self.rect().center())


def show_message(parent, title, message):
    return PhasmMessageDialog(parent, title, message).exec()


def confirm_message(parent, title, message):
    return PhasmMessageDialog(parent, title, message, confirm=True).exec() == QDialog.Accepted
