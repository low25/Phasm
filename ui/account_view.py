from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget, QInputDialog, QLineEdit)

from core import accounts


class AccountView(QWidget):
    closed = Signal()
    accounts_changed = Signal()
    steam_login_finished = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 42, 48, 42)
        layout.setSpacing(18)
        title = QLabel("ACCOUNTS")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #f8fafc; letter-spacing: 2px;")
        layout.addWidget(title)
        intro = QLabel("Sign in with Steam to import your owned games into Phasm.")
        intro.setStyleSheet("color: #9f94b8; font-size: 14px;")
        layout.addWidget(intro)
        note = QLabel("Login opens in your browser. Phasm never sees or stores your Steam password. A Steam Web API key is required to read your library.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #7c6f99; padding: 12px; background: #100e1b; border: 1px solid #2b2342; border-radius: 8px;")
        layout.addWidget(note)
        self.rows = {}
        self._add_provider(layout, "Steam", "Login through Steam OpenID and import your owned games", "#1b75bb")
        layout.addStretch()
        self.status = QLabel("")
        self.status.setStyleSheet("color: #c084fc; font-size: 13px;")
        layout.addWidget(self.status)
        back = QPushButton("BACK")
        back.clicked.connect(self.closed.emit)
        layout.addWidget(back, 0, Qt.AlignLeft)
        self.steam_login_finished.connect(self._finish_steam_login)
        self._refresh()

    def _add_provider(self, parent_layout, provider, description, color):
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #12101e; border: 1px solid #30264c; border-radius: 12px; }")
        row = QHBoxLayout(frame)
        row.setContentsMargins(18, 16, 18, 16)
        copy = QVBoxLayout()
        label = QLabel(provider.upper())
        label.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: bold;")
        detail = QLabel(description)
        detail.setStyleSheet("color: #a99fba;")
        copy.addWidget(label)
        copy.addWidget(detail)
        row.addLayout(copy, 1)
        state = QLabel()
        button = QPushButton()
        button.clicked.connect(lambda _=False, p=provider: self._toggle(p))
        row.addWidget(state)
        row.addWidget(button)
        parent_layout.addWidget(frame)
        self.rows[provider] = (state, button)

    def _refresh(self):
        for provider, (state, button) in self.rows.items():
            connected = accounts.is_connected(provider)
            state.setText("CONNECTED" if connected else "NOT CONNECTED")
            state.setStyleSheet(f"color: {'#86efac' if connected else '#8f86a8'}; font-size: 12px;")
            button.setText("DISCONNECT" if connected else "LOGIN WITH STEAM")

    def _toggle(self, provider):
        if accounts.is_connected(provider):
            accounts.disconnect(provider)
            self.status.setText(f"{provider} disconnected.")
            self._refresh()
            self.accounts_changed.emit()
            return
        self.status.setText("Opening Steam login in your browser…")
        self.rows[provider][1].setEnabled(False)
        accounts.start_steam_login(self._steam_login_callback)

    def _steam_login_callback(self, steamid, error):
        self.steam_login_finished.emit(steamid, error)

    def _finish_steam_login(self, steamid, error):
        self.rows["Steam"][1].setEnabled(True)
        if error:
            self.status.setText(f"Steam login failed: {error}")
            return
        api_key, accepted = QInputDialog.getText(
            self, "Steam Web API key", "Enter your Steam Web API key:", QLineEdit.Password,
        )
        if not accepted or not api_key.strip():
            self.status.setText("Steam login completed, but no API key was provided.")
            return
        imported = accounts.save_steam_account(steamid, api_key.strip())
        self.status.setText(f"{len(imported)} Steam game(s) imported. Refreshing the library…")
        self._refresh()
        self.accounts_changed.emit()
