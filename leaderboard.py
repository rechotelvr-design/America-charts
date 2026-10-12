
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()
MESSAGE_FILE = Path("message_id.txt")

US_CHART_URL = (
    "https://rivalducks.com/apps/radar/charts/"
    "top-playing-now?country=us"
)
GAMES_URL = "https://games.roblox.com/v1/games"

HEADERS = {
    "User-Agent": "RobloxTabAmericaLeaderboard/1.0",
}


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_us_chart_ids():
    """Extract game universe IDs in order from the US chart page."""
    response = requests.get(
        US_CHART_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    # Rival Ducks game links contain the universe ID in the URL slug.
    pattern = re.compile(
        r"""href\s*=\s*["']([^"']*/apps/radar/games/
        (\d+)-[^"']*)["']""",
        re.IGNORECASE | re.VERBOSE,
    )

    ids = []
    seen = set()

    for match in pattern.finditer(html):
        game_url = urljoin(US_CHART_URL, match.group(1))
        universe_id = int(match.group(2))

        if "rivalducks.com/apps/radar/games/" not in game_url:
            continue

        if universe_id not in seen:
            seen.add(universe_id)
            ids.append(universe_id)

        if len(ids) >= 10:
            break

    if len(ids) < 10:
        raise RuntimeError(
            f"Only found {len(ids)} unique game IDs on the US chart. "
            "Rival Ducks may have changed its page structure or "
            "may not be returning the chart rows in its HTML."
        )

    print("US chart game IDs:", ids)
    return ids


def get_top_games():
    # The order comes from the US chart, not global player counts.
    ids = get_us_chart_ids()
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

    if len(games) < 10:
        raise RuntimeError(
            f"Roblox returned player counts for only {len(games)} "
            "of the 10 US chart games. Refusing to publish an "
            "incomplete leaderboard."
        )

    for rank, game in enumerate(games, 1):
        print(
            f'{rank}. {game.get("name", "Unknown")}: '
            f'{int(game["playing"]):,} worldwide players'
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
            f"🌎 {players:,} worldwide playing"
        )

    return {
        "title": "🇺🇸 US Top 10 Roblox Games",
        "description": "\n".join(lines),
        "color": 0x00A2FF,
        "footer": {
            "text": (
                "Rival Ducks US chart ranking • "
                "Worldwide player counts • Updates every 10 minutes"
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
            timeout=30,
        )

        if response.status_code != 404:
            response.raise_for_status()
            print("Updated existing USA leaderboard.")
            return

        print("Saved message was not found; creating a replacement.")

    response = requests.post(
        WEBHOOK,
        params={"wait": "true"},
        json={"embeds": [embed]},
        timeout=30,
    )
    response.raise_for_status()

    message_id = response.json()["id"]
    MESSAGE_FILE.write_text(message_id + "\n")

    print("Created USA leaderboard:", message_id)


if __name__ == "__main__":
    games = get_top_games()
    publish(make_embed(games))
