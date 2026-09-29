"""Launcher account connectors.

Steam uses browser OpenID plus its Web API.
"""
import threading
import re
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

from core.config import config
from core.library import steam_installed_appids

_STEAM_EXCLUDED = ("steam linux runtime", "linux runtime", "proton", "steamworks",
                   "common redistributables", "redistributable", "software development kit",
                   " sdk", "dedicated server", "runtime")


def _is_steam_game(game):
    name = str(game.get("name", "")).strip().casefold()
    return bool(name) and not any(term in name for term in _STEAM_EXCLUDED)


def _vdf_values(path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    return {key.lower(): value for key, value in re.findall(r'"([^"\\]+)"\s+"([^"\\]*)"', text)}


def _steam_installed_appids():
    return steam_installed_appids()


def import_steam_games(steam_games, installed_appids=None):
    installed_appids = installed_appids or set()
    imported = {}
    for game in steam_games or []:
        if not _is_steam_game(game):
            continue
        appid = str(game.get("appid", "")).strip()
        if not appid:
            continue
        is_installed = appid in installed_appids
        uri = f"steam://rungameid/{appid}" if is_installed else f"steam://install/{appid}"
        imported[f"Steam::{appid}"] = {
            "title": game.get("name", f"Steam game {appid}"), "platform": "PC",
            "path": uri, "type": "launcher", "source": "Steam",
            "source_id": appid, "launch_uri": uri, "is_installed": is_installed,
        }
    return list(imported.values())


def fetch_steam_owned_games(steamid, api_key):
    response = requests.get(
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/",
        params={"key": api_key, "steamid": steamid, "format": "json",
                "include_appinfo": 1, "include_played_free_games": 1},
        timeout=15,
    )
    response.raise_for_status()
    games = response.json().get("response", {}).get("games")
    if games is None:
        raise ValueError("Steam returned no games. Make sure your game details are public.")
    return games


class _SteamCallback(BaseHTTPRequestHandler):
    result = None

    def do_GET(self):  # noqa: N802
        _SteamCallback.result = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        body = b"<h2>Phasm Steam login complete.</h2><p>You can close this window.</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def start_steam_login(callback):
    """Open Steam login and call callback(steamid, error) on a worker thread."""
    def run():
        server = HTTPServer(("127.0.0.1", 0), _SteamCallback)
        port = server.server_address[1]
        return_to = f"http://127.0.0.1:{port}/steam/callback"
        params = {"openid.ns": "http://specs.openid.net/auth/2.0",
                  "openid.mode": "checkid_setup", "openid.return_to": return_to,
                  "openid.realm": f"http://127.0.0.1:{port}/",
                  "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
                  "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
        _SteamCallback.result = None
        webbrowser.open("https://steamcommunity.com/openid/login?" + urllib.parse.urlencode(params))
        server.timeout = 180
        while _SteamCallback.result is None:
            server.handle_request()
        query = _SteamCallback.result
        server.server_close()
        if query.get("openid.mode", [""])[0] != "id_res":
            callback(None, "Steam login was cancelled.")
            return
        try:
            verify = {key: values[0] for key, values in query.items() if values}
            verify["openid.mode"] = "check_authentication"
            result = requests.post("https://steamcommunity.com/openid/login", data=verify, timeout=15)
            if "is_valid:true" not in result.text.replace(" ", "").casefold():
                raise ValueError("Steam could not verify the OpenID response.")
            steamid = verify.get("openid.claimed_id", "").rsplit("/", 1)[-1]
            if not steamid.isdigit():
                raise ValueError("Steam returned an invalid account id.")
            callback(steamid, None)
        except Exception as exc:
            callback(None, str(exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def sync_accounts():
    accounts = config.userdata.setdefault("accounts", {})
    imported = []
    steam = accounts.get("Steam", {})
    if steam.get("steamid") and steam.get("api_key"):
        try:
            imported.extend(import_steam_games(
                fetch_steam_owned_games(steam["steamid"], steam["api_key"]),
                _steam_installed_appids(),
            ))
        except Exception as exc:
            print(f"[ACCOUNTS] Steam sync failed: {exc}")
    config.library["games"] = imported
    config.save_library()
    return imported


def save_steam_account(steamid, api_key):
    accounts = config.userdata.setdefault("accounts", {})
    accounts["Steam"] = {"steamid": str(steamid), "api_key": str(api_key), "connected": True}
    config.save_userdata()
    return sync_accounts()


def disconnect(provider):
    config.userdata.setdefault("accounts", {}).pop(provider, None)
    config.save_userdata()
    return sync_accounts()


def is_connected(provider):
    return bool(config.userdata.get("accounts", {}).get(provider, {}).get("connected"))
