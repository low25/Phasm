import json
from pathlib import Path
import threading
import os
import shutil

class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self.project_root = Path(__file__).parent.parent.resolve()
        bundled_config_dir = self.project_root / "config"
        self.data_dir = self.project_root
        if os.environ.get("PHASM_APPIMAGE") or os.environ.get("APPIMAGE"):
            xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            self.config_dir = xdg_config / "Phasm"
            self.config_dir.mkdir(parents=True, exist_ok=True)
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            self.data_dir = xdg_data / "Phasm"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            bundled_cache = self.project_root / "cache"
            self.cache_dir = self.data_dir / "cache"
            if not self.cache_dir.exists() and bundled_cache.exists():
                try:
                    shutil.copytree(bundled_cache, self.cache_dir)
                except OSError:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
            else:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Copy bundled defaults once. Subsequent launches read and write
            # only the user's writable directory, so AppImage rebuilds do not
            # overwrite collections, favorites, or settings.
            for filename in ("settings.json", "userdata.json", "library.json", "emulators.json"):
                destination = self.config_dir / filename
                source = bundled_config_dir / filename
                if not destination.exists() and source.exists():
                    try:
                        shutil.copy2(source, destination)
                    except OSError:
                        pass
        else:
            self.config_dir = bundled_config_dir
            self.cache_dir = self.project_root / "cache"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.settings_file = self.config_dir / "settings.json"
        self.userdata_file = self.config_dir / "userdata.json"
        self.library_file = self.config_dir / "library.json"
        self.emulators_file = self.config_dir / "emulators.json"

        self.settings = {
            "steamgriddb": {"enabled": False, "api_key": ""},
            "rawg": {"enabled": False, "api_key": ""},
            "sound": {
                "enabled": True,
                "volume": 80,
                "effects": {"enabled": True, "volume": 80},
                "music": {"enabled": True, "volume": 60},
            },
            "fullscreen": True,
            "minimize_on_launch": False,
            "show_empty_platforms": False,
            "hero_orientation": "vertical",
            "hero_width": 360,
            "hero_height": 260,
            "accent": "Violet",
            "background_mode": "hero_full"
        }
        self.userdata = {"favorites": [], "recently_played": []}
        self.library = {"libraries": {}}
        self.emulators = {}

        self.load_all()

    def load_json(self, path, default_data):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Update default data recursively
                    if isinstance(default_data, dict):
                        merged = default_data.copy()
                        merged.update(data)
                        return merged
                    return data
            except Exception as e:
                print(f"[WARN] Error loading {path}: {e}")
        return default_data

    def save_json(self, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"[ERR] Error saving {path}: {e}")

    def load_all(self):
        self.settings = self.load_json(self.settings_file, self.settings)
        self.settings.pop("theme", None)
        self.settings["background_mode"] = "hero_full"
        self.userdata = self.load_json(self.userdata_file, self.userdata)
        self.library = self.load_json(self.library_file, self.library)
        self.emulators = self.load_json(self.emulators_file, self.emulators)

    def save_settings(self):
        self.save_json(self.settings_file, self.settings)

    def save_userdata(self):
        self.save_json(self.userdata_file, self.userdata)

    def save_library(self):
        self.save_json(self.library_file, self.library)

    def save_emulators(self):
        self.save_json(self.emulators_file, self.emulators)

config = ConfigManager()
