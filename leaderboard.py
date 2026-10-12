
import os
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

import requests

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()
MESSAGE_FILE = Path("message_id.txt")
SESSION = str(uuid.uuid4())

HEADERS = {
    "User-Agent": "RobloxTabLeaderboard/1.0",
}

EXPLORE_URL = (
    "https://apis.roblox.com/explore-api/v1/"
    "get-sort-content"
)

GAMES_URL = "https://games.roblox.com/v1/games"


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def find_universe_ids(data):
    """Extract game universe IDs while preserving chart order."""
    ids = []
    seen = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ("universeid", "universe_id"):
                    try:
                        game_id = int(value)
                        if game_id not in seen:
                            seen.add(game_id)
                            ids.append(game_id)
                    except (TypeError, ValueError):
                        pass

                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

        elif isinstance(obj, str) and obj.startswith(("{", "[")):
            try:
                walk(json.loads(obj))
            except json.JSONDecodeError:
                pass

    walk(data)
    return ids


def get_top_games():
    discovery = get_json(
        EXPLORE_URL,
        {
            "sessionId": SESSION,
            "sortId": "top-playing-now",
            "device": "all",
            "country": "all",
            "maxRows": 100,
        },
    )

    ids = find_universe_ids(discovery)

    print("Chart response keys:", list(discovery.keys()))
    print("Unique universe IDs found:", len(ids))

    if not ids:
        raise RuntimeError(
            "No game IDs found in Roblox's chart response. "
            "The API response may have changed."
        )

    # Fetch metadata in batches, keeping the original chart order.
    games_by_id = {}

    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]

        data = get_json(
            GAMES_URL,
            {"universeIds": ",".join(map(str, batch))},
        )

        for game in data.get("data", []):
            games_by_id[game["id"]] = game

    games = []

    for universe_id in ids:
        game = games_by_id.get(universe_id)

        if game and isinstance(game.get("playing"), (int, float)):
            games.append(game)

    # Rank by the latest live player count.
    games.sort(
        key=lambda game: game["playing"],
        reverse=True,
    )

    print("Games with player counts:", len(games))

    for game in games[:10]:
        print(
            f'{game.get("name", "Unknown")}: '
            f'{int(game["playing"]):,} players'
        )

    return games[:10]


def make_embed(games):
    lines = []

    for rank, game in enumerate(games, 1):
        name = game.get("name", "Unknown game")
        name = name.replace("[", "").replace("]", "")

        place_id = game.get("rootPlaceId")
        link = (
            f"https://www.roblox.com/games/{place_id}"
            if place_id
            else "https://www.roblox.com/charts/top-playing-now"
        )

        players = int(game["playing"])

        lines.append(
            f"**{rank}. [{name}]({link})** — "
            f"👥 {players:,} playing"
        )

    return {
        "title": "🏆 Top 10 Roblox Games Right Now",
        "description": "\n".join(lines),
        "color": 0x00A2FF,
        "footer": {
            "text": (
                "Roblox Tab • Worldwide chart • "
                "Refreshes every 10 minutes"
            )
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def publish(embed):
    message_id = (
        MESSAGE_FILE.read_text().strip()
        if MESSAGE_FILE.exists()
        else ""
    )

    if message_id:
        url = f"{WEBHOOK}/messages/{message_id}"

        response = requests.patch(
            url,
            json={"embeds": [embed]},
            timeout=25,
        )

        if response.status_code != 404:
            response.raise_for_status()
            print("Updated existing leaderboard.")
            return

        print("Old message missing; creating a replacement.")

    response = requests.post(
        WEBHOOK,
        params={"wait": "true"},
        json={"embeds": [embed]},
        timeout=25,
    )
    response.raise_for_status()

    message_id = response.json()["id"]
    MESSAGE_FILE.write_text(message_id + "\n")

    print("Created leaderboard:", message_id)


if __name__ == "__main__":
    games = get_top_games()

    if not games:
        raise RuntimeError("Roblox returned no games.")

    publish(make_embed(games))
