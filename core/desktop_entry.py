"""Linux desktop launcher entries for games in the user's library."""

import os
import re
import hashlib
import shutil
import subprocess
from pathlib import Path

from core.config import config
from core.launcher import EmulatorLauncher
from core.assets import slugify


def _desktop_dir():
    user_dirs = Path.home() / ".config" / "user-dirs.dirs"
    if user_dirs.exists():
        for line in user_dirs.read_text(encoding="utf-8").splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                value = value.replace("$HOME", str(Path.home()))
                return Path(os.path.expandvars(value)).expanduser()
    return Path.home() / "Desktop"


def _desktop_arg(value):
    # Desktop Entry uses double-quoted arguments (not shell single quotes).
    value = str(value)
    value = value.replace("%", "%%")
    if re.fullmatch(r"[A-Za-z0-9_./:+%=-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _game_icon(game):
    """Return the selected icon, including icons restored from the artwork cache."""
    configured = str(game.get("icon_path", "")).strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = config.project_root / path
        if path.exists():
            return path

    slug = f"{slugify(game.get('title', ''))}_{str(game.get('platform', '')).lower()}"
    icon_dir = config.cache_dir / "artwork" / "icons"
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = icon_dir / f"{slug}{suffix}"
        if candidate.exists():
            return candidate
    return config.project_root / "assets" / "icon.svg"


def _entry_name(game):
    title = str(game.get("title", "Game")).strip() or "Game"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip(".-") or "game"
    game_key = re.sub(r"[^A-Za-z0-9._-]+", "-", str(game.get("key", ""))).strip(".-")
    if game_key:
        filename = f"{filename}-{game_key[:24]}"
    return title, filename


def _entry_directories():
    desktop = _desktop_dir()
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return desktop, data_home / "applications"


def _matching_entries(game):
    title, filename = _entry_name(game)
    matches = set()
    for directory in _entry_directories():
        for candidate in directory.glob("*.desktop") if directory.exists() else ():
            if candidate.name == f"{filename}.desktop":
                matches.add(candidate)
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            if f"Name={title}\n" in content:
                matches.add(candidate)
    return matches


def desktop_entry_exists(game):
    return bool(_matching_entries(game))


def remove_desktop_entry(game):
    """Remove all Desktop/app-menu entries belonging to this game."""
    removed = False
    for entry in _matching_entries(game):
        try:
            entry.unlink()
            removed = True
        except OSError:
            pass
    return removed


def _launcher_icon_path(game, source, data_home):
    """Copy artwork to a content-addressed path to defeat desktop icon caches."""
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        icon_dir = data_home / "icons" / "phasm-games"
        icon_dir.mkdir(parents=True, exist_ok=True)
        target = icon_dir / f"{_entry_name(game)[1]}-{digest}{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        return target
    except OSError:
        return source


def create_desktop_entry(game):
    """Create/update direct launchers on Desktop and in the app menu."""
    title, filename = _entry_name(game)
    destination, applications_dir = _entry_directories()
    destination.mkdir(parents=True, exist_ok=True)
    entry_path = destination / f"{filename}.desktop"

    command = EmulatorLauncher(
        str(config.emulators_file), resource_root=config.project_root
    ).command_for(game)
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    icon_source = _game_icon(game)
    icon = str(_launcher_icon_path(game, icon_source, data_home))
    lines = [
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        f"Name={title}",
        f"Exec={' '.join(_desktop_arg(part) for part in command)}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=Game;",
        "StartupNotify=true",
        "",
    ]
    content = "\n".join(lines)
    entry_path.write_text(content, encoding="utf-8")
    entry_path.chmod(0o755)

    # Application menus index the per-user applications directory, not the
    # Desktop directory. Keep a separate copy so both surfaces work.
    applications_dir.mkdir(parents=True, exist_ok=True)
    menu_entry = applications_dir / entry_path.name
    menu_entry.write_text(content, encoding="utf-8")
    menu_entry.chmod(0o755)
    # Repair entries created by older Phasm builds that used only the title
    # as their filename and therefore may still point at Phasm's icon.
    for directory in (destination, applications_dir):
        for legacy in directory.glob("*.desktop"):
            if legacy == entry_path or legacy == menu_entry:
                continue
            try:
                old_content = legacy.read_text(encoding="utf-8")
            except OSError:
                continue
            if f"Name={title}\n" in old_content:
                legacy.write_text(content, encoding="utf-8")
                legacy.chmod(0o755)
    updater = shutil.which("update-desktop-database")
    if updater:
        try:
            subprocess.run([updater, str(applications_dir)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return entry_path
