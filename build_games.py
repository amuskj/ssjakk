#!/usr/bin/env python3
"""
SSJakk full game log builder.

Pulls every individual game from every known "Hopen Arena" tournament -
both players, ratings at the time, result, a direct Chess.com link, the
opening played, move count, and how much clock time each side had left at
the end - plus accuracy scores on the (small) subset of games where someone
has actually run Chess.com's "Game Review" on them. Writes games.json next
to this script, which index.html's Trends tab loads at page load.

Run it after each Sunday session (same TOURNAMENT_IDS list in config.py
that backfill_sunday.py uses - update it there once, both scripts pick it
up):

    python build_games.py
    git add games.json build_games.py
    git commit -m "Add <date> game log"
    git push

Requires: pip install requests

Note on accuracy: Chess.com only computes it when someone runs Game Review
on that specific game, so most games will have accuracyWhite/accuracyBlack
== null. That's expected, not a bug - the site shows it opportunistically
wherever it exists instead of requiring it.
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests

from config import USERNAMES, USERNAME_TO_PERSON, DISPLAY_NAMES, HEADERS, TOURNAMENT_IDS, extract_id

OUT_FILE = "games.json"
PGN_CACHE_FILE = ".game_pgns_cache.json"

CLK_RE = re.compile(r"\{\[%clk\s+([0-9:.]+)\]\}")


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"  ! {url} -> HTTP {r.status_code}", file=sys.stderr)
        return None
    return r.json()


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def parse_clk(s):
    if not s:
        return None
    parts = [float(x) for x in s.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def opening_name_from_eco(eco_url):
    if not eco_url:
        return None
    slug = eco_url.rstrip("/").split("/")[-1]
    parts = slug.split("-")
    name_parts = []
    for part in parts:
        if part and part[0].isdigit():
            break
        name_parts.append(part)
    return " ".join(name_parts) if name_parts else slug.replace("-", " ")


def build_game_record(g, tid, tournament_name, date):
    id_match = re.search(r"live/(\d+)", g.get("url", ""))
    gid = id_match.group(1) if id_match else g.get("url")

    white, black = g["white"], g["black"]
    wu, bu = white["username"].lower(), black["username"].lower()
    if white["result"] == "win":
        result = "white"
    elif black["result"] == "win":
        result = "black"
    else:
        result = "draw"

    clocks = CLK_RE.findall(g.get("pgn", ""))
    white_clocks, black_clocks = clocks[0::2], clocks[1::2]

    return {
        "id": gid,
        "tournamentId": tid,
        "tournamentName": tournament_name,
        "date": date,
        "endTime": g.get("end_time"),
        "white": {
            "username": wu, "person": person_for(wu),
            "displayName": DISPLAY_NAMES.get(person_for(wu), wu),
            "rating": white.get("rating"),
        },
        "black": {
            "username": bu, "person": person_for(bu),
            "displayName": DISPLAY_NAMES.get(person_for(bu), bu),
            "rating": black.get("rating"),
        },
        "result": result,
        "url": g.get("url"),
        "timeControl": g.get("time_control"),
        "timeClass": g.get("time_class"),
        "openingName": opening_name_from_eco(g.get("eco")),
        "moveCount": (len(clocks) + 1) // 2,
        "finalClockWhite": parse_clk(white_clocks[-1]) if white_clocks else None,
        "finalClockBlack": parse_clk(black_clocks[-1]) if black_clocks else None,
        "accuracyWhite": None,
        "accuracyBlack": None,
    }


def main():
    games = []
    pgn_by_id = {}
    for entry in TOURNAMENT_IDS:
        tid = extract_id(entry)
        print(f"Fetching {tid}...")
        meta = get_json(f"https://api.chess.com/pub/tournament/{tid}")
        round_data = get_json(f"https://api.chess.com/pub/tournament/{tid}/1")
        if not meta or not round_data:
            continue
        finish_time = meta.get("finish_time")
        date = (
            datetime.fromtimestamp(finish_time, tz=timezone.utc).strftime("%Y-%m-%d")
            if finish_time else None
        )
        for g in round_data.get("games", []):
            record = build_game_record(g, tid, meta.get("name"), date)
            games.append(record)
            if g.get("pgn"):
                pgn_by_id[record["id"]] = g["pgn"]

    # Opportunistic accuracy: only present when someone ran Game Review.
    # Only worth checking the months our known tournaments actually fall in.
    months = sorted({g["date"][:7].replace("-", "/") for g in games if g["date"]})
    accuracy_by_url = {}
    for username in USERNAMES:
        for ym in months:
            print(f"Checking accuracy: {username} {ym}...")
            data = get_json(f"https://api.chess.com/pub/player/{username.lower()}/games/{ym}")
            if not data:
                continue
            for g in data.get("games", []):
                if g.get("accuracies"):
                    accuracy_by_url[g["url"]] = g["accuracies"]

    for g in games:
        acc = accuracy_by_url.get(g["url"])
        if acc:
            g["accuracyWhite"] = acc.get("white")
            g["accuracyBlack"] = acc.get("black")

    games.sort(key=lambda g: g["endTime"] or 0)

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "games": games,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    with open(PGN_CACHE_FILE, "w") as f:
        json.dump(pgn_by_id, f)

    with_acc = sum(1 for g in games if g["accuracyWhite"] is not None)
    print(f"\nWrote {OUT_FILE}: {len(games)} games, {with_acc} with accuracy data.")
    print(f"Wrote {PGN_CACHE_FILE}: {len(pgn_by_id)} PGNs (scratch file for find_brilliancies.py, not committed).")


if __name__ == "__main__":
    main()
