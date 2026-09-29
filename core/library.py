"""Helpers for normalizing and querying library entries."""

from pathlib import Path
import re
import time


_STEAM_STATE = {"checked_at": 0.0, "appids": set()}

_STEAM_TOOL_APPIDS = {
    "228980",   # Steamworks Common Redistributables
    "1070560",  # Steam Linux Runtime 1.0
    "1391110",  # Steam Linux Runtime 2.0
    "1628350",  # Steam Linux Runtime 3.0
    "2180100",  # Proton Hotfix
}


def steam_installed_appids():
    """Return AppIDs with manifests in any registered Steam library."""
    now = time.monotonic()
    if now - _STEAM_STATE["checked_at"] < 2.0:
        return _STEAM_STATE["appids"]

    home = Path.home()
    roots = {
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".local" / "share" / "steam",
    }
    for root in tuple(roots):
        folders = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = folders.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"([^"\\]*(?:\\.[^"\\]*)*)"', text):
            roots.add(Path(value.replace("\\\\", "/")))

    installed = set()
    for root in roots:
        steamapps = root / "steamapps"
        if not steamapps.is_dir():
            continue
        installed.update(
            manifest.stem.removeprefix("appmanifest_")
            for manifest in steamapps.glob("appmanifest_*.acf")
        )
    _STEAM_STATE.update(checked_at=now, appids=installed)
    return installed


def game_is_installed(game):
    """Return the installed state without assuming missing PC metadata is true."""
    launch_uri = str(game.get("launch_uri", ""))
    is_steam = str(game.get("source", "")).casefold() == "steam" or launch_uri.casefold().startswith("steam://")
    appid = str(game.get("source_id", "")).strip()
    if not appid and is_steam:
        appid = launch_uri.rsplit("/", 1)[-1].strip()
    if is_steam and appid:
        installed = appid in steam_installed_appids()
        game["is_installed"] = installed
        return installed

    if "is_installed" in game:
        return bool(game["is_installed"])

    if str(game.get("platform", "")).casefold() != "pc":
        return True

    if launch_uri.casefold().startswith("steam://install/"):
        return False

    path = str(game.get("path", ""))
    installed = bool(path) and Path(path).expanduser().exists()

    # Cards query this during painting; retain inferred legacy state so a
    # large library does not repeatedly hit the filesystem while animating.
    game["is_installed"] = installed
    return installed


def is_steam_game(game):
    """Whether an entry is a Steam-managed game or tool."""
    launch_uri = str(game.get("launch_uri", ""))
    return (
        str(game.get("source", "")).casefold() == "steam"
        or launch_uri.casefold().startswith("steam://")
    )


def is_steam_tool(game):
    """Hide Steam runtimes, Proton, and redistributable helper packages."""
    if not is_steam_game(game):
        return False
    appid = str(game.get("source_id", "")).strip()
    title = " ".join(str(game.get("title", "")).casefold().replace("_", " ").split())
    path = str(game.get("path", "")).casefold().replace("_", " ")
    return (
        appid in _STEAM_TOOL_APPIDS
        or "steamworks common redistributable" in title
        or "steam linux runtime" in title
        or "steam runtime" in title
        or "proton" in title
        or "steamlinuxruntime" in path
        or "proton" in path
    )


def should_show_game(game):
    """Only expose real games; Steam entries must also be installed."""
    if is_steam_tool(game):
        return False
    return not is_steam_game(game) or game_is_installed(game)
