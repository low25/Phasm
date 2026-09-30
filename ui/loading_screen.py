from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QPointF, QRect, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QLinearGradient, QPixmap, QIcon
import random

_LOADING_ICON = None

from core.scanner import scan_library
from core.config import config
from core.metadata import cached_game, enrich_game, save_metadata_cache
from ui.sound_manager import sound_manager
from ui.theme import get_theme_colors

class ScannerThread(QThread):
    progress = Signal(str, int)
    scan_complete = Signal(list)

    def run(self):
        try:
            entries = []
            libraries = config.library.get("libraries", {})
            if isinstance(libraries, dict):
                for platform, value in libraries.items():
                    folders = value if isinstance(value, (list, tuple)) else [value]
                    entries.extend((platform, folder) for folder in folders if folder)
            standalone = config.library.get("games", [])
            if isinstance(standalone, list) and standalone:
                entries.append(("__games__", standalone))

            total_entries = max(1, len(entries))
            self.progress.emit("STARTING...", 0)
            games = []
            for i, (platform, path) in enumerate(entries):
                if self.isInterruptionRequested():
                    return
                label = "ADDED GAMES" if platform == "__games__" else platform
                self.progress.emit(f"SCANNING {label}...", int(i / total_entries * 45))
                try:
                    games.extend(scan_library({platform: path}))
                except Exception as exc:
                    print(f"[SCAN] Skipping {label}: {exc}")

            self.progress.emit("ENRICHING METADATA...", 45)
            enriched = []
            total_games = max(1, len(games))
            for i, game in enumerate(games):
                if self.isInterruptionRequested():
                    return
                # A rescan still enumerates library folders so additions and
                # removals are detected, but existing entries are restored
                # directly from the local cache.  Network enrichment only runs
                # for a game that has not been seen before.
                cached = cached_game(game)
                if cached is not None:
                    enriched.append(cached)
                    phase = "USING CACHED GAMES..."
                else:
                    try:
                        enriched.append(enrich_game(game))
                    except Exception as exc:
                        print(f"[SCAN] Could not enrich {game.get('path', '')}: {exc}")
                        enriched.append(dict(game))
                    phase = "ENRICHING NEW GAMES..."
                self.progress.emit(
                    f"{phase} {i + 1}/{len(games)}",
                    45 + int(((i + 1) / total_games) * 54),
                )

            save_metadata_cache()

            self.progress.emit("DONE!", 100)
            self.scan_complete.emit(enriched)
        except Exception as exc:
            print(f"[SCAN] Fatal scan error: {exc}")
            self.progress.emit("SCAN RECOVERED", 100)
            self.scan_complete.emit([])

class LoadingScreen(QWidget):
    loading_complete = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_text = "INITIALIZING..."
        self.progress_val = 0
        self._loading_phase = 0
        self._icon_angle = 0.0
        self._icon_returning = False
        self._finish_games = None
        self.accent = QColor(get_theme_colors(accent_name=config.settings.get("accent"))["ACCENT"])
        
        self.particles = []
        for _ in range(20):
            self.particles.append({
                "x": random.uniform(0, 1920),
                "y": random.uniform(0, 1080),
                "dx": random.uniform(-0.5, 0.5),
                "dy": random.uniform(-0.5, 0.5),
                "size": random.uniform(2, 5)
            })
            
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(32)
        self.anim_timer.timeout.connect(self.update_anim)
        
        self.scanline_offset = 0

    def start_loading(self):
        scanner = getattr(self, "scanner", None)
        if scanner and scanner.isRunning():
            return
        self._icon_angle = 0.0
        self._icon_returning = False
        self._finish_games = None
        self.anim_timer.start()
        sound_manager.play("startup")
        
        self.scanner = ScannerThread()
        self.scanner.progress.connect(self.on_progress)
        self.scanner.scan_complete.connect(self.on_finished)
        self.scanner.start()

    def refresh_theme(self):
        self.accent = QColor(get_theme_colors(accent_name=config.settings.get("accent"))["ACCENT"])
        self.update()

    def update_anim(self):
        self.scanline_offset = (self.scanline_offset + 1) % 4
        self._loading_phase = (self._loading_phase + 7) % 440
        if self._icon_returning:
            self._icon_angle *= 0.72
            if abs(self._icon_angle) < 0.5:
                self._icon_angle = 0.0
                self._icon_returning = False
        else:
            self._icon_angle = (self._icon_angle + 5.0) % 360.0
        for p in self.particles:
            p["x"] += p["dx"]
            p["y"] += p["dy"]
            if p["x"] < 0: p["x"] = self.width()
            if p["x"] > self.width(): p["x"] = 0
            if p["y"] < 0: p["y"] = self.height()
            if p["y"] > self.height(): p["y"] = 0
        self.update()

    def on_progress(self, text, val):
        self.status_text = text
        self.progress_val = max(0, min(100, val))
        self.update()

    def on_finished(self, games):
        if self._finish_games is not None:
            return
        self._finish_games = games
        self._icon_returning = True
        self.anim_timer.start()
        QTimer.singleShot(320, self._complete_loading)

    def _complete_loading(self):
        games = self._finish_games
        self._finish_games = None
        self._icon_angle = 0.0
        self.anim_timer.stop()
        self.loading_complete.emit(games or [])

    def stop_loading(self):
        self.anim_timer.stop()
        scanner = getattr(self, "scanner", None)
        if scanner and scanner.isRunning():
            scanner.requestInterruption()
            scanner.wait(5000)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor("#0a0a0f"))

        # Particles
        painter.setPen(Qt.NoPen)
        particle_color = QColor(self.accent)
        particle_color.setAlpha(80)
        painter.setBrush(particle_color)
        for p in self.particles:
            painter.drawEllipse(QPointF(p["x"], p["y"]), p["size"], p["size"])

        cx = self.width() / 2
        cy = self.height() / 2
        content_width = min(720, max(300, self.width() - 64))

        # The icon is the only branding element; keeping text out of this
        # bounded area prevents vertical clipping at compact resolutions.
        global _LOADING_ICON
        if _LOADING_ICON is None:
            icon_path = config.project_root / "assets" / "icon.svg"
            _LOADING_ICON = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        icon = _LOADING_ICON
        icon_rect = QRectF(cx - 56, cy - 154, 112, 112)
        if not icon.isNull():
            # Draw into a fixed square centered on the screen so the SVG can
            # never be clipped by an oversized text/layout rectangle.
            painter.save()
            painter.translate(cx, cy - 98)
            painter.rotate(self._icon_angle)
            # Use QRect here instead of QRectF.  Some PySide6 builds expose
            # the QRectF overload inconsistently; the failed overload leaves
            # this painter active and repeated paint events can crash Qt.
            icon_pixmap = icon.pixmap(112, 112)
            icon_painter = QPainter(icon_pixmap)
            icon_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            icon_painter.fillRect(icon_pixmap.rect(), self.accent)
            icon_painter.end()
            painter.drawPixmap(QRect(-56, -56, 112, 112), icon_pixmap)
            painter.restore()

        font = QFont("DejaVu Sans", 15, QFont.Bold)
        font.setPixelSize(15)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        painter.setFont(font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(QRectF(cx - content_width / 2, cy - 35, content_width, 28), Qt.AlignCenter, "PS2  •  PS3  •  PS4  •  SWITCH")

        # Loading Bar Background
        bar_w = min(440, max(220, int(self.width() * 0.64)))
        bar_h = 12
        bx = int(cx - bar_w / 2)
        by = int(cy + 58)
        painter.setPen(QColor("#393047"))
        painter.setBrush(QColor("#17151f"))
        painter.drawRoundedRect(bx, by, bar_w, bar_h, 4, 4)

        # Loading Bar Fill
        fill_w = int(bar_w * (self.progress_val / 100.0))
        grad = QLinearGradient(bx, by, bx + bar_w, by)
        accent_end = self.accent.lighter(135)
        grad.setColorAt(0, self.accent)
        grad.setColorAt(1, accent_end)
        if fill_w > 0:
            painter.save()
            painter.setClipRect(bx, by, fill_w, bar_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(bx, by, fill_w, bar_h, 6, 6)
            # Moving highlight makes activity visible while metadata is loading.
            shine_x = bx + self._loading_phase - 40
            shine = QLinearGradient(shine_x, by, shine_x + 80, by)
            shine.setColorAt(0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 255, 255, 145))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(shine)
            painter.drawRoundedRect(bx, by, fill_w, bar_h, 6, 6)
            painter.restore()
        else:
            # Indeterminate shimmer remains visible before the scanner reports progress.
            shine_x = bx + self._loading_phase - 40
            shine = QLinearGradient(shine_x, by, shine_x + 80, by)
            shine.setColorAt(0, self.accent)
            shine.setColorAt(1, accent_end)
            painter.save()
            painter.setClipRect(bx, by, bar_w, bar_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(shine)
            painter.drawRoundedRect(shine_x, by, 80, bar_h, 4, 4)
            painter.restore()

        # Status Text
        font.setPointSize(12)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.setPen(QColor("#e2e8f0"))
        painter.drawText(QRectF(cx - content_width / 2, cy + 5, content_width, 28), Qt.AlignCenter, self.status_text)
        painter.setPen(accent_end)
        percent_font = QFont("DejaVu Sans", 11, QFont.Bold)
        painter.setFont(percent_font)
        painter.drawText(QRectF(cx - content_width / 2, cy + 83, content_width, 24), Qt.AlignCenter, f"{self.progress_val}%")

        # Scanlines
        painter.setPen(QColor(0, 0, 0, 40))
        for y in range(self.scanline_offset, self.height(), 4):
            painter.drawLine(0, y, self.width(), y)
            painter.drawLine(0, y+1, self.width(), y+1)
        painter.end()
