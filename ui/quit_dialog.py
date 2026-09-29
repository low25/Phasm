from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QColor, QPainter

class QuitDialog(QWidget):
    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(40)
        
        lbl = QLabel("QUIT PHASM?")
        lbl.setStyleSheet("color: white; font-size: 32px; font-weight: bold; letter-spacing: 2px;")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)
        btn_layout.setAlignment(Qt.AlignCenter)
        
        self.btn_yes = QPushButton("YES, QUIT")
        self.btn_yes.setCursor(Qt.PointingHandCursor)
        self.btn_yes.setFocusPolicy(Qt.StrongFocus)
        self.btn_yes.setStyleSheet("""
            QPushButton { background: #1e1e2e; color: #ef4444; font-weight: bold; font-size: 18px; padding: 15px 30px; border: 2px solid transparent; border-radius: 8px; }
            QPushButton:focus { border: 2px solid #ef4444; }
        """)
        self.btn_yes.clicked.connect(self.confirmed.emit)
        
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFocusPolicy(Qt.StrongFocus)
        self.btn_cancel.setStyleSheet("""
            QPushButton { background: #1e1e2e; color: white; font-weight: bold; font-size: 18px; padding: 15px 30px; border: 2px solid transparent; border-radius: 8px; }
            QPushButton:focus { border: 2px solid #7c3aed; }
        """)
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self.btn_yes.installEventFilter(self)
        self.btn_cancel.installEventFilter(self)
        
        btn_layout.addWidget(self.btn_yes)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        self.btn_cancel.setFocus()
        
    def showEvent(self, event):
        self.btn_cancel.setFocus()
        super().showEvent(event)

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self.cancelled.emit()
        elif k == Qt.Key_Left:
            self.btn_yes.setFocus()
        elif k == Qt.Key_Right:
            self.btn_cancel.setFocus()
        elif k in (Qt.Key_Enter, Qt.Key_Return):
            if self.btn_yes.hasFocus():
                self.btn_yes.click()
            else:
                self.btn_cancel.click()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and obj in (self.btn_yes, self.btn_cancel):
            key = event.key()
            if key == Qt.Key_Left:
                self.btn_yes.setFocus()
                return True
            if key == Qt.Key_Right:
                self.btn_cancel.setFocus()
                return True
            if key in (Qt.Key_Enter, Qt.Key_Return):
                obj.click()
                return True
            if key == Qt.Key_Escape:
                self.cancelled.emit()
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(5, 5, 10, 240))
        painter.end()
