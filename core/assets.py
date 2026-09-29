import re
import requests
from pathlib import Path
from core.config import config


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _api_key() -> str:
    return config.settings.get("steamgriddb", {}).get("api_key", "").strip()


def _headers():
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else None


class SteamGridDB:
    BASE = "https://www.steamgriddb.com/api/v2"

    @classmethod
    def search_game(cls, title: str):
        games = cls.search_games(title, limit=1)
        return games[0]["id"] if games else None

    @classmethod
    def search_games(cls, title: str, limit: int = 5):
        h = _headers()
        if not h:
            return []
        try:
            r = requests.get(
                f"{cls.BASE}/search/autocomplete/{requests.utils.quote(title)}",
                headers=h, timeout=6,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])[:limit]
                return [{"id": item["id"], "name": item.get("name", "")} for item in data]
        except Exception:
            pass
        return []

    @classmethod
    def fetch_url(cls, endpoint: str, game_id: int, params: dict = None):
        urls = cls.fetch_urls(endpoint, game_id, params)
        return urls[0] if urls else None

    @classmethod
    def fetch_urls(cls, endpoint: str, game_id: int, params: dict = None, limit: int = 5):
        h = _headers()
        if not h:
            return []
        try:
            url = f"{cls.BASE}/{endpoint}/game/{game_id}"
            r = requests.get(url, headers=h, params=params or {}, timeout=6)
            if r.status_code == 200:
                data = r.json().get("data", [])
                return [item["url"] for item in data[:limit] if item.get("url")]
        except Exception:
            pass
        return []


def _download(url: str, dest: Path) -> Path | None:
    if not url:
        return None
    try:
        r = requests.get(url, stream=True, timeout=15)
        if r.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return dest
    except Exception:
        pass
    return None


def download_custom_artwork(kind: str, title: str, platform: str, url: str) -> str | None:
    """Download a user-selected image over the normal cached artwork slot."""
    slug = f"{slugify(title)}_{platform.lower()}"
    directory = {"cover": "covers", "hero": "heroes", "logo": "logos", "icon": "icons"}.get(kind)
    if not directory or not url:
        return None
    cache_dir = _cache_dir(directory)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        old = cache_dir / f"{slug}{ext}"
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass
    ext = Path(url.split("?")[0]).suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    result = _download(url, cache_dir / f"{slug}{ext}")
    return str(result) if result else None


def _cache_dir(kind: str) -> Path:
    return config.cache_dir / "artwork" / kind


def _cached_path(kind: str, slug: str) -> Path | None:
    d = _cache_dir(kind)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = d / f"{slug}{ext}"
        if p.exists():
            return p
    return None


def fetch_cover(game_title: str, platform: str) -> str | None:
    slug = f"{slugify(game_title)}_{platform.lower()}"

    cached = _cached_path("covers", slug)
    if cached:
        return str(cached)

    if not _api_key():
        return None

    game_id = SteamGridDB.search_game(game_title)
    if not game_id:
        return None

    url = SteamGridDB.fetch_url("grids", game_id, {"dimensions": "600x900"})
    if not url:
        url = SteamGridDB.fetch_url("grids", game_id)
    if not url:
        return None

    ext = Path(url.split("?")[0]).suffix or ".png"
    dest = _cache_dir("covers") / f"{slug}{ext}"
    result = _download(url, dest)
    return str(result) if result else None


def fetch_hero(game_title: str, platform: str) -> str | None:
    slug = f"{slugify(game_title)}_{platform.lower()}"

    cached = _cached_path("heroes", slug)
    if cached:
        return str(cached)

    if not _api_key():
        return None

    game_id = SteamGridDB.search_game(game_title)
    if not game_id:
        return None

    url = SteamGridDB.fetch_url("heroes", game_id)
    if not url:
        return None

    ext = Path(url.split("?")[0]).suffix or ".png"
    dest = _cache_dir("heroes") / f"{slug}{ext}"
    result = _download(url, dest)
    return str(result) if result else None


def fetch_logo(game_title: str, platform: str) -> str | None:
    slug = f"{slugify(game_title)}_{platform.lower()}"

    cached = _cached_path("logos", slug)
    if cached:
        return str(cached)

    if not _api_key():
        return None

    game_id = SteamGridDB.search_game(game_title)
    if not game_id:
        return None

    url = SteamGridDB.fetch_url("logos", game_id)
    if not url:
        return None

    ext = Path(url.split("?")[0]).suffix or ".png"
    dest = _cache_dir("logos") / f"{slug}{ext}"
    result = _download(url, dest)
    return str(result) if result else None
