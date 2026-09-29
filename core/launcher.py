import json
import subprocess
from pathlib import Path


class EmulatorLauncher:
    def __init__(self, config_path="config/emulators.json", resource_root=None):
        self.config_path = Path(config_path)
        self.project_root = Path(resource_root).resolve() if resource_root else self.config_path.parent.parent.resolve()
        self.emulators = self._load_config()

    def _load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as file:
            config = json.load(file)

        emulators = config["emulators"]
        # Settings stores user-selected emulator paths at the top level for
        # compatibility with the settings file. Apply those overrides to the
        # runtime command table in both source and AppImage launches.
        for platform, value in config.items():
            if platform in emulators and isinstance(value, str) and value.strip():
                emulators[platform]["command"] = value.strip()
        return emulators

    def launch(self, game):
        if game.get("platform") == "PC":
            uri = game.get("launch_uri")
            if not uri:
                raise ValueError("This PC game has no launcher URL")
            return subprocess.Popen(["xdg-open", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        platform = game["platform"]

        if platform not in self.emulators:
            raise ValueError(f"No emulator configured for {platform}")

        emulator = self.emulators[platform]

        command = [emulator["command"]]

        # Resolve local emulator paths relative to Phasm.
        if command[0] != "flatpak":
            command[0] = str(self.project_root / command[0])

        for argument in emulator["arguments"]:
            command.append(argument.replace("{game}", game["path"]))

        print(f"[LAUNCH] {' '.join(command)}")

        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
