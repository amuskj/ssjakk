#!/usr/bin/env python3
"""
SSJakk leaderboard data refresh.

Pulls every club member's public Chess.com game history, tallies lifetime
head-to-head records between members, and writes data.json next to this
script (which index.html loads at page load). Along the way it also
records each member's own blitz rating over time (one point per calendar
day, from every blitz game they've played, not just club games) and writes
that to ratings.json, which powers the Trends tab's "Lifetime Rating"
chart — no extra API calls, since this script already pages through every
member's full archive history for the head-to-head tally.

Run it whenever you want the site's numbers to catch up to reality:

    python refresh.py

Then commit + push data.json and ratings.json (and index.html/CNAME if you
changed them):

    git add data.json ratings.json
    git commit -m "Refresh leaderboard data"
    git push

GitHub Pages redeploys automatically a few seconds after the push.

Requires: pip install requests
"""

import json
import sys
import time
from datetime import datetime, timezone

import requests

from config import (
    USERNAMES,
    USERNAME_TO_PERSON,
    DISPLAY_NAMES,
    AVATAR_ACCOUNT_OVERRIDE,
    HEADERS,
    compute_nemesis,
)

# Roster lives in config.py now (shared with backfill_sunday.py) — edit that
# file when the club roster changes, not here.

OUT_FILE = "data.json"
RATINGS_OUT_FILE = "ratings.json"
MIN_GAMES_FOR_NEMESIS = 5
RATING_TIME_CLASS = "blitz"


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"  ! {url} -> HTTP {r.status_code}", file=sys.stderr)
        return None
    return r.json()


def fetch_avatar(username):
    data = get_json(f"https://api.chess.com/pub/player/{username.lower()}")
    return (data or {}).get("avatar")


def outcome(game):
    if game["white"]["result"] == "win":
        return "white"
    if game["black"]["result"] == "win":
        return "black"
    return "draw"


def main():
    member_set = {u.lower() for u in USERNAMES}
    seen_games = set()
    h2h = {}  # (userA, userB) sorted -> {p1,p2,p1Wins,p2Wins,draws}
    # username(lower) -> {"YYYY-MM-DD": (end_time, rating)} — that user's own
    # rating on the last RATING_TIME_CLASS game they played each day, across
    # every opponent (not just club members). Free to collect here since
    # we're already paging through every archive for h2h purposes.
    ratings_by_username = {u.lower(): {} for u in USERNAMES}

    for username in USERNAMES:
        u_lower = username.lower()
        print(f"Fetching archives for {username}...")
        archives = get_json(f"https://api.chess.com/pub/player/{u_lower}/games/archives")
        if not archives:
            continue
        for archive_url in archives["archives"]:
            data = get_json(archive_url)
            if not data:
                continue
            for g in data.get("games", []):
                white = g.get("white", {})
                black = g.get("black", {})
                wu, bu = white.get("username", "").lower(), black.get("username", "").lower()

                if g.get("time_class") == RATING_TIME_CLASS and g.get("end_time"):
                    side = white if wu == u_lower else black if bu == u_lower else None
                    if side is not None and side.get("rating") is not None:
                        et = g["end_time"]
                        d = datetime.fromtimestamp(et, tz=timezone.utc).strftime("%Y-%m-%d")
                        bucket = ratings_by_username[u_lower]
                        cur = bucket.get(d)
                        if cur is None or et > cur[0]:
                            bucket[d] = (et, side["rating"])

                if wu not in member_set or bu not in member_set or wu == bu:
                    continue
                gid = g.get("uuid") or g.get("url")
                if gid in seen_games:
                    continue
                seen_games.add(gid)

                pair = tuple(sorted([wu, bu]))
                rec = h2h.setdefault(pair, {"p1": pair[0], "p2": pair[1], "p1Wins": 0, "p2Wins": 0, "draws": 0})
                res = outcome(g)
                if res == "draw":
                    rec["draws"] += 1
                else:
                    winner = wu if res == "white" else bu
                    if winner == rec["p1"]:
                        rec["p1Wins"] += 1
                    else:
                        rec["p2Wins"] += 1
            time.sleep(0.05)  # be polite

    # ---- merge username-level records into person-level records ----
    person_edges = {}
    for (u1, u2), rec in h2h.items():
        p1, p2 = USERNAME_TO_PERSON.get(u1, u1), USERNAME_TO_PERSON.get(u2, u2)
        if p1 == p2:
            continue  # alt-account self-play, excluded
        key = tuple(sorted([p1, p2]))
        merged = person_edges.setdefault(key, {"p1": key[0], "p2": key[1], "p1Wins": 0, "p2Wins": 0, "draws": 0})
        src_wins, tgt_wins = rec["p1Wins"], rec["p2Wins"]
        if p1 == key[0]:
            merged["p1Wins"] += src_wins
            merged["p2Wins"] += tgt_wins
        else:
            merged["p1Wins"] += tgt_wins
            merged["p2Wins"] += src_wins
        merged["draws"] += rec["draws"]

    edges = []
    for rec in person_edges.values():
        rec["total"] = rec["p1Wins"] + rec["p2Wins"] + rec["draws"]
        edges.append(rec)

    # ---- per-person aggregates ----
    person_ids = sorted(set(USERNAME_TO_PERSON.values()))
    persons = {p: {"id": p, "accounts": [], "displayName": DISPLAY_NAMES.get(p, p),
                   "totalGames": 0, "wins": 0, "losses": 0, "draws": 0} for p in person_ids}
    for u, p in USERNAME_TO_PERSON.items():
        persons[p]["accounts"].append(u)

    per_opp = {p: {} for p in person_ids}
    for rec in edges:
        n = rec["total"]
        persons[rec["p1"]]["totalGames"] += n
        persons[rec["p1"]]["wins"] += rec["p1Wins"]
        persons[rec["p1"]]["losses"] += rec["p2Wins"]
        persons[rec["p1"]]["draws"] += rec["draws"]
        persons[rec["p2"]]["totalGames"] += n
        persons[rec["p2"]]["wins"] += rec["p2Wins"]
        persons[rec["p2"]]["losses"] += rec["p1Wins"]
        persons[rec["p2"]]["draws"] += rec["draws"]
        per_opp[rec["p1"]][rec["p2"]] = {"wins": rec["p1Wins"], "losses": rec["p2Wins"], "draws": rec["draws"], "total": n}
        per_opp[rec["p2"]][rec["p1"]] = {"wins": rec["p2Wins"], "losses": rec["p1Wins"], "draws": rec["draws"], "total": n}

    nemesis_map, _ = compute_nemesis(person_ids, edges)
    for p in person_ids:
        persons[p]["nemesis"] = nemesis_map[p]["nemesis"]
        persons[p]["nemesisScore"] = nemesis_map[p]["nemesisScore"]
        favorite, favorite_rate = None, -1
        for opp, rec in per_opp[p].items():
            if rec["total"] < MIN_GAMES_FOR_NEMESIS:
                continue
            rate = (rec["wins"] + rec["draws"] * 0.5) / rec["total"]
            if rate > favorite_rate:
                favorite_rate, favorite = rate, opp
        persons[p]["favorite"] = favorite
        persons[p]["favoriteScore"] = per_opp[p].get(favorite) if favorite else None

    # ---- avatars ----
    print("Fetching avatars...")
    for p in person_ids:
        account = AVATAR_ACCOUNT_OVERRIDE.get(p, persons[p]["accounts"][0])
        persons[p]["avatar"] = fetch_avatar(account)

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "players": list(persons.values()),
        "edges": edges,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    print(f"\nWrote {OUT_FILE}: {len(persons)} players, {len(edges)} rivalries, "
          f"{sum(e['total'] for e in edges)} games total.")

    # ---- lifetime rating history (merge alt accounts into one person,
    # taking whichever side played later on days both played) ----
    ratings_by_person = {}
    for u_lower, day_map in ratings_by_username.items():
        p = USERNAME_TO_PERSON.get(u_lower, u_lower)
        bucket = ratings_by_person.setdefault(p, {})
        for d, (et, rating) in day_map.items():
            cur = bucket.get(d)
            if cur is None or et > cur[0]:
                bucket[d] = (et, rating)

    ratings_players = {
        p: [[et, rating] for et, rating in sorted(bucket.values(), key=lambda x: x[0])]
        for p, bucket in ratings_by_person.items()
    }
    ratings_out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "timeClass": RATING_TIME_CLASS,
        "displayNames": {p: DISPLAY_NAMES.get(p, p) for p in ratings_players},
        "players": ratings_players,
    }
    with open(RATINGS_OUT_FILE, "w") as f:
        json.dump(ratings_out, f, indent=None)

    total_points = sum(len(v) for v in ratings_players.values())
    print(f"Wrote {RATINGS_OUT_FILE}: {len(ratings_players)} players, "
          f"{total_points} daily {RATING_TIME_CLASS} rating points.")


if __name__ == "__main__":
    main()
