"""Snapshot Sleeper data for one point in time.

Usage:
    pip install requests
    python archive_sleeper.py                    # trending + injury snapshots only
    python archive_sleeper.py SLEEPER_LEAGUE_ID  # also saves a Sleeper league's data

A Sleeper league ID is in the URL: sleeper.com/leagues/<LEAGUE_ID>/...
(Yahoo leagues use a separate script; Sleeper's trending data is still useful.)
Run it before kickoff on game days (and again Tuesday morning after waivers).
Output: data/raw/sleeper/<timestamp>/*.json  (this becomes your "raw zone" later)
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.sleeper.app/v1"


def get(path: str):
    resp = requests.get(f"{BASE}/{path}", timeout=30)
    resp.raise_for_status()
    time.sleep(0.2)  # stay far below Sleeper's 1000 calls/minute limit
    return resp.json()


def save(folder: Path, name: str, data) -> None:
    (folder / f"{name}.json").write_text(json.dumps(data))
    print(f"saved {name}")


def main() -> None:
    # League ID is optional: without it, only league-independent data is saved.
    league_id = sys.argv[1] if len(sys.argv) > 1 else None

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    folder = Path("data/raw/sleeper") / stamp
    folder.mkdir(parents=True, exist_ok=True)

    state = get("state/nfl")  # current season and week
    save(folder, "nfl_state", state)
    season, week = state["season"], state["week"]

    # Snapshot-only data: can't be fetched for the past later.
    save(folder, "trending_add", get("players/nfl/trending/add?lookback_hours=24&limit=100"))
    save(folder, "trending_drop", get("players/nfl/trending/drop?lookback_hours=24&limit=100"))

    # Full player list incl. injury status (~5MB). Sleeper asks: max once per day.
    players_today = Path("data/raw/sleeper") / f"players_{stamp[:10]}.json"
    if not players_today.exists():
        players_today.write_text(json.dumps(get("players/nfl")))
        print(f"saved {players_today.name}")

    # League data (only for Sleeper leagues; retrievable later this season).
    if league_id:
        save(folder, "league", get(f"league/{league_id}"))
        save(folder, "users", get(f"league/{league_id}/users"))
        save(folder, "rosters", get(f"league/{league_id}/rosters"))
        for w in range(1, int(week) + 1):
            save(folder, f"matchups_week{w}", get(f"league/{league_id}/matchups/{w}"))
            save(folder, f"transactions_week{w}", get(f"league/{league_id}/transactions/{w}"))

    print(f"done: season {season}, week {week} -> {folder}")


if __name__ == "__main__":
    main()
