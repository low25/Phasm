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

        emulators = {}
        nested = config.get("emulators", {})
        if isinstance(nested, dict):
            emulators.update(nested)

        # Settings files from older versions stored selected paths at the top
        # level. Apply those overrides so existing installations keep working.
        for platform, value in config.items():
            if platform == "emulators":
                continue
            if isinstance(value, str) and value.strip():
                arguments = ["-g", "{game}"] if platform == "PS4" else ["{game}"]
                emulators[platform] = {
                    "command": value.strip(),
                    "arguments": arguments,
                }
        return emulators

    def launch(self, game):
        return subprocess.Popen(
            self.command_for(game), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def command_for(self, game):
        """Build the exact command used to launch a game."""
        if game.get("platform") == "PC":
            uri = game.get("launch_uri")
            if not uri:
                raise ValueError("This PC game has no launcher URL")
            return ["xdg-open", uri]
        platform = game["platform"]

        emulator = self.emulators.get(platform)
        if not isinstance(emulator, dict) or not emulator.get("command", "").strip():
            raise ValueError(f"No emulator configured for {platform}")

        command = [emulator["command"]]

        # Use the exact path selected in Settings. Only bundled relative
        # defaults are resolved against Phasm; an absolute user path must not
        # be rewritten.
        if command[0] != "flatpak":
            executable = Path(command[0]).expanduser()
            if not executable.is_absolute():
                executable = self.project_root / executable
            command[0] = str(executable)

        for argument in emulator.get("arguments", ["{game}"]):
            command.append(argument.replace("{game}", game["path"]))

        print(f"[LAUNCH] {' '.join(command)}")
        return command
