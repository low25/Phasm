COLORS = {
    "BG": "#0a0a0f",
    "SURFACE": "#12121a",
    "ACCENT": "#7c3aed",
    "ACCENT2": "#c084fc",
    "TEXT": "#e2e8f0",
    "TEXT_DIM": "#64748b",
    "HIGHLIGHT": "#a855f7"
}
from core.config import config
from PySide6.QtGui import QColor


def accent_text_color(value):
    color = QColor(str(value))
    if not color.isValid():
        return "#ffffff"
    # Perceived luminance: use dark text on pale/white accents.
    luminance = (0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()) / 255
    return "#0a0a0f" if luminance >= 0.62 else "#ffffff"

ACCENT_PRESETS = {
    "Violet": ("#7c3aed", "#c084fc", "#a855f7"),
    "Cyan": ("#0891b2", "#67e8f9", "#22d3ee"),
    "Emerald": ("#059669", "#6ee7b7", "#34d399"),
    "Rose": ("#e11d48", "#fda4af", "#fb7185"),
    "Amber": ("#d97706", "#fcd34d", "#fbbf24"),
}


def get_theme_colors(theme_name=None, accent_name="Violet"):
    # One fixed launcher theme; keep theme_name for compatibility with old callers.
    theme = {"BG": "#0a0a0f", "SURFACE": "#12121a", "PANEL": "#100e1b", "TEXT_DIM": "#64748b"}
    preset = ACCENT_PRESETS.get(accent_name)
    if preset:
        accent, accent2, highlight = preset
    else:
        # Settings can store any RGBA value selected by QColorDialog, not only
        # one of the legacy named presets.
        color = QColor(str(accent_name))
        if not color.isValid():
            color = QColor("#7c3aed")
        alpha = color.alpha() < 255
        accent = color.name(QColor.HexArgb) if alpha else color.name()
        accent2_color = color.lighter(135)
        highlight_color = color.lighter(115)
        accent2 = accent2_color.name(QColor.HexArgb) if alpha else accent2_color.name()
        highlight = highlight_color.name(QColor.HexArgb) if alpha else highlight_color.name()
    return {
        "BG": theme["BG"], "SURFACE": theme["SURFACE"], "PANEL": theme["PANEL"],
        "ACCENT": accent, "ACCENT2": accent2, "HIGHLIGHT": highlight,
        "TEXT": "#e2e8f0", "TEXT_DIM": theme["TEXT_DIM"],
        "ACCENT_TEXT": accent_text_color(accent),
    }

def get_stylesheet() -> str:
    COLORS = get_theme_colors(accent_name=config.settings.get("accent", "Violet"))
    return f"""
    QMainWindow {{
        background-color: {COLORS["BG"]};
    }}
    QWidget {{
        color: {COLORS["TEXT"]};
        font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    }}
    QPushButton {{
        background-color: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        border: 1px solid #24243a;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 16px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: #1a1a24;
        border: 1px solid #4c3a78;
        color: {COLORS["TEXT"]};
    }}
    QPushButton:focus {{
        background-color: #211b38;
        border: 2px solid {COLORS["HIGHLIGHT"]};
        color: {COLORS["TEXT"]};
    }}
    QLabel {{
        background: transparent;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        border: none;
        background: {COLORS["BG"]};
        width: 8px;
        margin: 0px 0px 0px 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {COLORS["ACCENT"]};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        border: none;
        background: {COLORS["BG"]};
        height: 8px;
        margin: 0px 0px 0px 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: {COLORS["ACCENT"]};
        min-width: 20px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QLineEdit {{
        background-color: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        border: 1px solid {COLORS["TEXT_DIM"]};
        padding: 8px 12px;
        font-size: 16px;
        border-radius: 4px;
    }}
    QLineEdit:focus {{
        border: 2px solid {COLORS["HIGHLIGHT"]};
        background-color: #181626;
    }}
    QComboBox {{
        background-color: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        border: 1px solid {COLORS["TEXT_DIM"]};
        padding: 8px 12px;
        font-size: 16px;
        border-radius: 4px;
    }}
    QComboBox:focus {{
        border: 2px solid {COLORS["HIGHLIGHT"]};
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        selection-background-color: {COLORS["ACCENT"]};
        selection-color: #ffffff;
        border: 1px solid {COLORS["ACCENT"]};
    }}
    QCheckBox {{
        font-size: 16px;
        spacing: 10px;
    }}
    QCheckBox::indicator {{
        width: 20px;
        height: 20px;
        border: 1px solid {COLORS["TEXT_DIM"]};
        border-radius: 10px;
        background: {COLORS["SURFACE"]};
    }}
    QCheckBox::indicator:checked {{
        background: {COLORS["ACCENT"]};
        border: 1px solid {COLORS["ACCENT"]};
        image: none;
    }}
    QSpinBox, QDoubleSpinBox {{
        background: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        border: 1px solid {COLORS["TEXT_DIM"]};
        padding: 4px 6px;
        font-size: 13px;
    }}
    QSlider::groove:horizontal {{
        border: none;
        height: 6px;
        background: #252238;
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {COLORS["ACCENT"]};
        width: 20px;
        margin: -7px 0;
        border-radius: 10px;
        border: 2px solid #e9d5ff;
    }}
    QMessageBox {{
        background: {COLORS["PANEL"]};
        color: {COLORS["TEXT"]};
    }}
    QMessageBox QPushButton {{
        background: {COLORS["SURFACE"]};
        color: {COLORS["TEXT"]};
        border: 1px solid {COLORS["ACCENT"]};
        border-radius: 6px;
        padding: 8px 18px;
    }}
    QMessageBox QPushButton:hover, QMessageBox QPushButton:focus {{
        background: {COLORS["ACCENT"]};
        color: #ffffff;
    }}
    """
