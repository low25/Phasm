from core.config import config
import time

def toggle_favorite(game_key: str):
    if game_key in config.userdata["favorites"]:
        config.userdata["favorites"].remove(game_key)
    else:
        config.userdata["favorites"].append(game_key)
    config.save_userdata()

def is_favorite(game_key: str) -> bool:
    return game_key in config.userdata["favorites"]

def add_recently_played(game_key: str, game_title: str, platform: str):
    rp = config.userdata.get("recently_played", [])
    
    # Remove if it exists to move it to top
    rp = [g for g in rp if g.get("key") != game_key]
    
    # Add to front
    rp.insert(0, {
        "key": game_key,
        "title": game_title,
        "platform": platform,
        "last_played": time.time(),
    })
    
    # Keep only top 20
    rp = rp[:20]
    config.userdata["recently_played"] = rp
    config.save_userdata()

def get_recently_played() -> list:
    return config.userdata.get("recently_played", [])

def get_last_played(game_key: str):
    for game in config.userdata.get("recently_played", []):
        if game.get("key") == game_key:
            return game.get("last_played")
    return None

def get_favorites_keys() -> set:
    return set(config.userdata.get("favorites", []))

def add_playtime(game_key: str, seconds: float):
    pt = config.userdata.setdefault("playtime", {})
    game_pt = pt.setdefault(game_key, {"total_seconds": 0, "sessions": 0})
    game_pt["total_seconds"] += seconds
    game_pt["sessions"] += 1
    config.save_userdata()

def get_playtime(game_key: str) -> int:
    pt = config.userdata.get("playtime", {})
    return int(pt.get(game_key, {}).get("total_seconds", 0))

def get_session_count(game_key: str) -> int:
    pt = config.userdata.get("playtime", {})
    return pt.get(game_key, {}).get("sessions", 0)

def clear_playtime():
    if "playtime" in config.userdata:
        config.userdata["playtime"] = {}
        config.save_userdata()


def get_collections() -> dict:
    """Return the user-created collection name -> game-key mapping."""
    collections = config.userdata.setdefault("collections", {})
    return collections


def reorder_collections(names: list[str]):
    """Persist collection tab order while preserving all collection data."""
    collections = get_collections()
    ordered = {name: collections[name] for name in names if name in collections}
    ordered.update({name: games for name, games in collections.items() if name not in ordered})
    config.userdata["collections"] = ordered
    config.save_userdata()


def get_collection_view(name: str) -> str:
    views = config.userdata.setdefault("collection_views", {})
    return "list" if views.get(name) == "list" else "grid"


def set_collection_view(name: str, view: str):
    views = config.userdata.setdefault("collection_views", {})
    views[name] = "list" if view == "list" else "grid"
    config.save_userdata()


def create_collection(name: str) -> str | None:
    name = " ".join(str(name).strip().split())
    if not name or name.upper() == "HOME":
        return None
    collections = get_collections()
    existing = next((key for key in collections if key.casefold() == name.casefold()), None)
    if existing:
        return existing
    collections[name] = []
    config.save_userdata()
    return name


def delete_collection(name: str):
    collections = get_collections()
    if name in collections:
        del collections[name]
        config.userdata.setdefault("collection_views", {}).pop(name, None)
        config.save_userdata()


def rename_collection(old_name: str, new_name: str) -> str | None:
    """Rename a collection while preserving its games and display preference."""
    new_name = " ".join(str(new_name).strip().split())
    collections = get_collections()
    if old_name not in collections or not new_name or new_name.upper() == "HOME":
        return None

    duplicate = next(
        (name for name in collections
         if name != old_name and name.casefold() == new_name.casefold()),
        None,
    )
    if duplicate is not None:
        return None

    collections[new_name] = collections.pop(old_name)
    views = config.userdata.setdefault("collection_views", {})
    if old_name in views:
        views[new_name] = views.pop(old_name)
    config.save_userdata()
    return new_name


def add_to_collection(name: str, game_key: str):
    collections = get_collections()
    if name not in collections:
        return
    if game_key not in collections[name]:
        collections[name].append(game_key)
        config.save_userdata()


def remove_from_collection(name: str, game_key: str):
    collections = get_collections()
    if name in collections and game_key in collections[name]:
        collections[name].remove(game_key)
        config.save_userdata()


def move_to_collection(name: str, game_key: str):
    """Move a game to one collection, removing it from other collections."""
    collections = get_collections()
    if name not in collections:
        return
    changed = False
    for collection_games in collections.values():
        while game_key in collection_games:
            collection_games.remove(game_key)
            changed = True
    if game_key not in collections[name]:
        collections[name].append(game_key)
        changed = True
    if changed:
        config.save_userdata()
