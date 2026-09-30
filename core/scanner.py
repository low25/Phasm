from pathlib import Path

from core.library import game_is_installed, should_show_game


GAME_EXTENSIONS = {
    "PS1": {
        ".cue",
        ".bin",
    },
    "PS2": {
        ".iso",
        ".chd",
        ".cso",
        ".mdf",
    },
    "PS3": {
        ".iso",
    },
    "PS4": {
        ".pkg",
    },
    "Switch": {
        ".nsp",
        ".xci",
        ".nsz",
    },
}


def scan_library(libraries):
    games = []

    for platform, directory in libraries.items():
        if platform == "__games__":
            continue
        directories = directory if isinstance(directory, (list, tuple)) else [directory]
        for folder in directories:
            if folder:
                games.extend(_scan_library_directory(platform, folder))

    for item in libraries.get("__games__", []):
        if not should_show_game(item):
            continue
        path = Path(item.get("path", "")).expanduser()
        if path.exists() or (item.get("platform", "").casefold() == "pc" and item.get("launch_uri")):
            game = {
                "title": item.get("title") or clean_title(path.stem if path.is_file() else path.name),
                "platform": item.get("platform", "PS2"),
                "path": str(path),
                "type": item.get("type", "file"),
            }
            # Preserve launcher-specific data for imported PC games. Keep
            # explicit False values: they mean the owned game is not installed.
            for field in ("source", "source_id", "launch_uri"):
                if item.get(field) is not None:
                    game[field] = item[field]
            game["is_installed"] = game_is_installed(item)
            games.append(game)

    unique = {}
    for game in games:
        unique[game.get("path")] = game
    return list(unique.values())


def _scan_library_directory(platform, directory):
    root = Path(directory).expanduser()
    if not root.exists():
        print(f"[WARN] Library not found: {root}")
        return []

    print(f"[SCAN] {platform}: {root}")
    if platform == "PS3":
        return scan_ps3(root)
    if platform == "PS4":
        return scan_ps4(root)
    if platform == "PS1":
        return scan_ps1(root)
    return scan_files(root, platform)


def scan_files(root, platform):
    games = []
    extensions = GAME_EXTENSIONS.get(str(platform), set())
    if not extensions:
        print(f"[WARN] Unsupported platform skipped: {platform}")
        return games

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in extensions:
            continue

        # MDF + MDS belong to the same PS2 disc.
        if path.suffix.lower() == ".mdf":
            mds = path.with_suffix(".mds")
            launch_path = mds if mds.exists() else path
        else:
            launch_path = path

        games.append({
            "title": clean_title(path.stem),
            "platform": platform,
            "path": str(launch_path),
            "type": "file",
        })

    return games


def scan_ps3(root):
    games = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # PS3 ISO
        if path.suffix.lower() == ".iso":
            games.append({
                "title": clean_title(path.stem),
                "platform": "PS3",
                "path": str(path),
                "type": "file",
            })

        # Extracted PS3 game
        elif path.name.upper() == "PS3_DISC.SFB":
            game_dir = path.parent

            games.append({
                "title": clean_title(game_dir.name),
                "platform": "PS3",
                "path": str(game_dir),
                "type": "directory",
            })

    return games


def scan_ps1(root):
    """Scan PS1 CUE/BIN and CHD layouts.

    Each immediate child directory of the configured PS1 library is treated
    as one game.  A CUE file is preferred because it preserves the complete
    disc track layout; BIN and CHD are used as fallbacks.  CHD files may also
    be placed directly in the configured PS1 library.
    """
    games = []

    # A CHD can be stored directly in PS1Games, unlike CUE/BIN layouts which
    # use one folder per game.
    for path in sorted(
        (path for path in root.iterdir() if path.is_file() and path.suffix.casefold() == ".chd"),
        key=lambda path: path.name.casefold(),
    ):
        games.append({
            "title": clean_title(path.stem),
            "platform": "PS1",
            "path": str(path),
            "type": "file",
        })

    for game_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
        game_files = (path for path in game_dir.iterdir() if path.is_file())
        cue_files = sorted((path for path in game_files if path.suffix.casefold() == ".cue"), key=lambda path: path.name.casefold())
        # Re-enumerate because the generator above is consumed by cue_files.
        bin_files = sorted(
            (path for path in game_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".bin"),
            key=lambda path: path.name.casefold(),
        )
        chd_files = sorted(
            (path for path in game_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".chd"),
            key=lambda path: path.name.casefold(),
        )
        launch_path = cue_files[0] if cue_files else (bin_files[0] if bin_files else (chd_files[0] if chd_files else None))
        if launch_path is None:
            continue

        games.append({
            "title": clean_title(game_dir.name),
            "platform": "PS1",
            "path": str(launch_path),
            "type": "file",
        })

    return games


def scan_ps4(root):
    games = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # PS4 PKG
        if path.suffix.lower() == ".pkg":
            games.append({
                "title": clean_title(path.stem),
                "platform": "PS4",
                "path": str(path),
                "type": "file",
            })

        # Extracted PS4 game
        elif path.name.lower() == "eboot.bin":
            game_dir = path.parent
            # Just go up one level or use the dir name if we want to avoid getting sys_modules or something.
            # Typically eboot.bin is in sce_sys or root of game dir. Let's just use parent dir name.
            games.append({
                "title": clean_title(game_dir.name),
                "platform": "PS4",
                "path": str(game_dir),
                "type": "directory",
            })

    return games


def clean_title(name):
    return name.replace("_", " ").strip()
