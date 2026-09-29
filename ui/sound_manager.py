import time
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput
from pathlib import Path
from core.config import config

class SoundManager:
    # Minimum milliseconds between two plays of the same sound.
    # Prevents duplicate triggers when multiple code paths fire for one event.
    _COOLDOWN_MS = 70

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.resolve()
        self.sounds_dir = self.project_root / "assets" / "sounds"
        self.sounds = {}
        self._audio_outputs = {}
        self._last_played: dict[str, float] = {}
        sound_settings = config.settings.get("sound", {})
        legacy_enabled = bool(sound_settings.get("enabled", True))
        legacy_volume = float(sound_settings.get("volume", 80))
        effects = sound_settings.get("effects", {})
        music = sound_settings.get("music", {})
        self.effects_enabled = bool(effects.get("enabled", legacy_enabled))
        self.effects_volume = max(0.0, min(1.0, float(effects.get("volume", legacy_volume)) / 100.0))
        self.music_enabled = bool(music.get("enabled", True))
        self.music_volume = max(0.0, min(1.0, float(music.get("volume", 60)) / 100.0))
        self.enabled = self.effects_enabled
        self.volume = self.effects_volume

        # The new focus/hover MP3 replaces the old navigation effect.
        self.load_sound("navigate", "focus⁄hover.mp3")
        self.load_sound("select")
        self.load_sound("back")
        # The play action uses the dedicated play sound for both button press
        # and emulator launch, with the older launch asset no longer preferred.
        self.load_sound("launch", "play.mp3")
        self.load_sound("startup")
        self.load_sound("error")
        self._setup_ambience()

    def load_sound(self, name, filename=None):
        if filename:
            path = self.sounds_dir / filename
        else:
            # Prefer a replacement MP3 when supplied, otherwise retain the
            # original WAV asset as a fallback.
            mp3_path = self.sounds_dir / f"{name}.mp3"
            path = mp3_path if mp3_path.exists() else self.sounds_dir / f"{name}.wav"
        if path.exists():
            if path.suffix.lower() == ".mp3":
                effect = QMediaPlayer()
                output = QAudioOutput()
                output.setVolume(self.effects_volume if self.effects_enabled else 0.0)
                effect.setAudioOutput(output)
                effect.setSource(QUrl.fromLocalFile(str(path)))
                self._audio_outputs[name] = output
            else:
                effect = QSoundEffect()
                effect.setSource(QUrl.fromLocalFile(str(path)))
                effect.setVolume(self.effects_volume if self.effects_enabled else 0.0)
            self.sounds[name] = effect
        else:
            self.sounds[name] = None

    def _setup_ambience(self):
        path = self.sounds_dir / "ambience.mp3"
        self.ambience = None
        self.ambience_output = None
        if not path.exists():
            return
        self.ambience = QMediaPlayer()
        self.ambience_output = QAudioOutput()
        self.ambience_output.setVolume(self.music_volume if self.music_enabled else 0.0)
        self.ambience.setAudioOutput(self.ambience_output)
        self.ambience.setSource(QUrl.fromLocalFile(str(path)))
        self.ambience.setLoops(QMediaPlayer.Loops.Infinite)
        if self.music_enabled:
            self.ambience.play()

    def play(self, name):
        if not self.effects_enabled:
            return
        now = time.monotonic() * 1000  # ms
        last = self._last_played.get(name, 0.0)
        # Focus/hover navigation should respond to every card immediately.
        # Other effects retain the small duplicate-trigger guard.
        if now - last < self._COOLDOWN_MS:
            return
        self._last_played[name] = now

        effect = self.sounds.get(name)
        if effect:
            if name == "navigate" and name in self._audio_outputs:
                output = self._audio_outputs[name]
                output.setVolume(self.effects_volume if self.effects_enabled else 0.0)
                effect.stop()
                effect.setPosition(0)
                effect.play()
                return
            effect.stop()   # restart cleanly instead of stacking
            effect.play()

    def set_volume(self, value):
        self.set_effects_volume(value)

    def set_effects_volume(self, value):
        self.effects_volume = max(0.0, min(1.0, float(value) / 100.0))
        self.volume = self.effects_volume
        for name, effect in self.sounds.items():
            if effect:
                output = self._audio_outputs.get(name)
                if output:
                    output.setVolume(self.effects_volume if self.effects_enabled else 0.0)
                else:
                    effect.setVolume(self.effects_volume if self.effects_enabled else 0.0)

    def set_music_volume(self, value):
        self.music_volume = max(0.0, min(1.0, float(value) / 100.0))
        if self.ambience_output:
            self.ambience_output.setVolume(self.music_volume if self.music_enabled else 0.0)

    def set_enabled(self, enabled):
        self.set_effects_enabled(enabled)

    def set_effects_enabled(self, enabled):
        self.effects_enabled = bool(enabled)
        self.enabled = self.effects_enabled
        for name, effect in self.sounds.items():
            if effect:
                output = self._audio_outputs.get(name)
                if output:
                    output.setVolume(self.effects_volume if self.effects_enabled else 0.0)
                else:
                    effect.setVolume(self.effects_volume if self.effects_enabled else 0.0)

    def set_music_enabled(self, enabled):
        self.music_enabled = bool(enabled)
        if self.ambience_output:
            self.ambience_output.setVolume(self.music_volume if self.music_enabled else 0.0)
            if self.music_enabled:
                self.ambience.play()
            else:
                self.ambience.pause()

sound_manager = SoundManager()
