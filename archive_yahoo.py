"""Archive your Yahoo Fantasy league data (read-only, personal, non-commercial use).

Fantasy data provided by Yahoo Fantasy.

Setup (once):
    1. Create an app at https://developer.yahoo.com/apps/create/
       (Installed Application, redirect URI https://localhost:8080, Fantasy Sports: Read)
    2. Put YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET in a .env file next to this script.

Usage:
    python3 archive_yahoo.py               # sign in (first time) and list your NFL leagues
    python3 archive_yahoo.py 461.l.123456  # archive that league (use the key printed above)

Output: data/raw/yahoo/<timestamp>/*.json
Tokens are stored in .yahoo_token.json. Keep it and .env out of git.
"""
import base64
import json
import re
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
TOKEN_FILE = Path(".yahoo_token.json")


# ---------- configuration ----------

def load_env(path: Path = Path(".env")) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = load_env()
CLIENT_ID = ENV.get("YAHOO_CLIENT_ID", "")
CLIENT_SECRET = ENV.get("YAHOO_CLIENT_SECRET", "")
REDIRECT_URI = ENV.get("YAHOO_REDIRECT_URI", "https://localhost:8080")


# ---------- OAuth 2.0 ----------

def _basic_auth() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _request_token(data: dict) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data=data,
        headers={"Authorization": _basic_auth(),
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"Token request failed ({resp.status_code}): {resp.text}")
    token = resp.json()
    token["obtained_at"] = time.time()
    TOKEN_FILE.write_text(json.dumps(token))
    return token


def first_sign_in() -> dict:
    url = AUTH_URL + "?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    })
    print("\nA browser window will open. Sign in to Yahoo and click Agree.")
    print("You'll land on a localhost page that fails to load. That's expected.")
    print("Copy the FULL address from the browser's address bar and paste it here.\n")
    print(f"If no browser opens, visit:\n{url}\n")
    webbrowser.open(url)
    pasted = input("Paste the address (or just the code): ").strip()
    code = parse_qs(urlparse(pasted).query).get("code", [pasted])[0]
    return _request_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    })


def get_token() -> dict:
    if not TOKEN_FILE.exists():
        return first_sign_in()
    token = json.loads(TOKEN_FILE.read_text())
    # Access tokens last about an hour; refresh a few minutes early.
    if time.time() - token["obtained_at"] > token.get("expires_in", 3600) - 300:
        token = _request_token({
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "redirect_uri": REDIRECT_URI,
        })
    return token


# ---------- API calls ----------

def api_get(path: str) -> dict:
    token = get_token()
    resp = requests.get(
        f"{API}/{path}",
        params={"format": "json"},
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=30,
    )
    if resp.status_code != 200:
        # Show Yahoo's own explanation instead of a bare status code.
        sys.exit(f"Yahoo API error {resp.status_code} for {path}:\n{resp.text[:2000]}")
    time.sleep(0.5)  # be polite: "reasonable request volume"
    return resp.json()


def find_all(data: dict, field: str) -> list:
    """Yahoo's JSON is deeply nested; pull every value of a field by name."""
    # Matches both string values ("9") and bare numbers (9).
    return re.findall(rf'"{field}":\s*"?([^",}}\]]+)"?', json.dumps(data))


def save(folder: Path, name: str, data) -> None:
    (folder / f"{name}.json").write_text(json.dumps(data))
    print(f"saved {name}")


# ---------- main ----------

def list_leagues() -> None:
    data = api_get("users;use_login=1/games;game_keys=nfl/leagues")
    keys, names = find_all(data, "league_key"), find_all(data, "name")
    if not keys:
        print("No current-season NFL leagues found for this Yahoo account.")
        return
    print("\nYour NFL leagues this season:")
    for key, name in zip(keys, names):
        print(f"  {key}   {name}")
    print("\nNext: python3 archive_yahoo.py <league_key>")


def archive_league(league_key: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    folder = Path("data/raw/yahoo") / stamp
    folder.mkdir(parents=True, exist_ok=True)

    league = api_get(f"league/{league_key}")
    save(folder, "league", league)
    current_week = int(find_all(league, "current_week")[0])

    save(folder, "settings", api_get(f"league/{league_key}/settings"))
    save(folder, "standings", api_get(f"league/{league_key}/standings"))
    save(folder, "transactions", api_get(f"league/{league_key}/transactions"))
    teams = api_get(f"league/{league_key}/teams")
    save(folder, "teams", teams)
    team_keys = sorted(set(find_all(teams, "team_key")))

    for week in range(1, current_week + 1):
        save(folder, f"scoreboard_week{week}",
             api_get(f"league/{league_key}/scoreboard;week={week}"))
        for team_key in team_keys:
            team_id = team_key.split(".t.")[-1]
            save(folder, f"roster_team{team_id}_week{week}",
                 api_get(f"team/{team_key}/roster;week={week}"))

    print(f"\ndone: weeks 1-{current_week}, {len(team_keys)} teams -> {folder}")


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Missing YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET in .env")
    if len(sys.argv) > 1:
        archive_league(sys.argv[1])
    else:
        list_leagues()


if __name__ == "__main__":
    main()