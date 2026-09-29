import json
import re
import requests
from pathlib import Path
from core.assets import fetch_cover, fetch_hero, fetch_logo
from core.config import config
from core.userdata import is_favorite

def enrich_game(game_dict: dict) -> dict:
    title = game_dict.get("title", "")
    platform = game_dict.get("platform", "")
    
    # Generate unique key
    path = game_dict.get("path", "")
    game_key = f"{platform}::{path}"
    
    try:
        cover_path = fetch_cover(title, platform)
    except Exception:
        cover_path = None
        
    try:
        hero_path = fetch_hero(title, platform)
    except Exception:
        hero_path = None
        
    try:
        logo_path = fetch_logo(title, platform)
    except Exception:
        logo_path = None

    rawg = _fetch_rawg(title)
    if rawg:
        cover_path = cover_path or _download_rawg_image(rawg.get("cover_image"), "covers", title, platform)
        hero_path = hero_path or _download_rawg_image(rawg.get("hero_image"), "heroes", title, platform)
        rawg["screenshots"] = [
            path for i, image in enumerate(rawg.get("screenshots", []))
            if (path := _download_rawg_image(image, "screenshots", f"{title}_{i}", platform))
        ]
        
    enriched = dict(game_dict)
    enriched.update({
        "key": game_key,
        "cover_path": cover_path,
        "hero_path": hero_path,
        "logo_path": logo_path,
        "description": rawg.get("description", "") if rawg else "",
        "year": rawg.get("year", "") if rawg else "",
        "developer": rawg.get("developer", "") if rawg else "",
        "screenshots": rawg.get("screenshots", []) if rawg else [],
        "is_favorite": is_favorite(game_key)
    })
    _save_local_metadata(enriched)
    
    return enriched

def _save_local_metadata(game):
    path = config.cache_dir / "metadata" / "games.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        existing[game.get("key", "")] = {
            key: game.get(key, "") for key in
            ("title", "platform", "description", "year", "developer", "cover_path", "hero_path", "logo_path", "icon_path", "screenshots")
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass


def _rawg_key():
    rawg = config.settings.get("rawg", {})
    return rawg.get("api_key", "").strip() if rawg.get("enabled", False) else ""


def _rawg_slug(title, platform):
    value = re.sub(r"[^a-z0-9]+", "_", f"{title}_{platform}".lower()).strip("_")
    return value or "game"


def _fetch_rawg(title):
    key = _rawg_key()
    if not key or not title:
        return {}
    cache_dir = config.cache_dir / "metadata"
    cache_path = cache_dir / f"{re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        response = requests.get(
            "https://api.rawg.io/api/games",
            params={"key": key, "search": title, "page_size": 1}, timeout=8,
        )
        if response.status_code != 200:
            return {}
        results = response.json().get("results", [])
        if not results:
            return {}
        game = results[0]
        detail = requests.get(
            f"https://api.rawg.io/api/games/{game['id']}",
            params={"key": key}, timeout=8,
        )
        data = detail.json() if detail.status_code == 200 else game
        developers = data.get("developers") or []
        result = {
            "description": data.get("description_raw") or "",
            "year": str((data.get("released") or "")[:4]),
            "developer": developers[0].get("name", "") if developers else "",
            "cover_image": data.get("background_image") or "",
            "hero_image": data.get("background_image_additional") or data.get("background_image") or "",
            "screenshots": [s.get("image") for s in (data.get("short_screenshots") or [])[:3] if s.get("image")],
        }
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    except Exception:
        return {}


def _download_rawg_image(url, kind, title, platform):
    if not url:
        return None
    slug = _rawg_slug(title, platform)
    dest = config.cache_dir / "artwork" / kind / f"{slug}.jpg"
    if dest.exists():
        return str(dest)
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
            return str(dest)
    except Exception:
        pass
    return None
