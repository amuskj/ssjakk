#!/usr/bin/env python3
"""
SSJakk Sunday Standings backfill / refresh.

Pulls full results (standings + per-game ratings) for every known
tournament, tallies a cumulative Sunday leaderboard from the regular
"hopen" series, finds each week's biggest rating upset, and writes
sunday.json next to this script (which index.html loads at page load for
the Sunday Standings tab). A tournament in any other series (a one-off
memorial or holiday arena) is kept out of that cumulative leaderboard and
written to its own "specialEvents" list instead, so it gets its own
section/podium on the site without skewing the regular-season standings.

Run it after each Sunday session — add that week's tournament to
TOURNAMENTS in config.py, then:

    python backfill_sunday.py
    git add sunday.json backfill_sunday.py
    git commit -m "Add <date> Sunday arena results"
    git push

Requires: pip install requests
"""

import json
import sys
from datetime import datetime, timezone

import requests

from config import (
    USERNAME_TO_PERSON,
    DISPLAY_NAMES,
    HEADERS,
    TOURNAMENTS,
    SERIES,
    extract_id,
    compute_nemesis,
)

# Add this week's tournament (id or full URL, plus its series) to
# TOURNAMENTS in config.py after every Sunday session — build_games.py
# reads the same list, so it only needs updating in one place. A regular
# week uses series "hopen"; a one-off event gets its own series key (see
# the comment above TOURNAMENTS in config.py) and shows up here as its own
# "special event" instead of feeding the main Sunday podium/leaderboard.

OUT_FILE = "sunday.json"


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"  ! {url} -> HTTP {r.status_code}", file=sys.stderr)
        return None
    return r.json()


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def outcome(g):
    if g["white"]["result"] == "win":
        return "white"
    if g["black"]["result"] == "win":
        return "black"
    return "draw"


def build_arena_graph(all_games):
    """Person-merged head-to-head graph scoped to just these arena games
    (mirrors refresh.py's lifetime version, but only over Sunday arenas)."""
    h2h = {}
    for g in all_games:
        wu, bu = g["white"]["username"].lower(), g["black"]["username"].lower()
        if wu == bu:
            continue
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

    person_edges = {}
    for (u1, u2), rec in h2h.items():
        p1, p2 = person_for(u1), person_for(u2)
        if p1 == p2:
            continue
        key = tuple(sorted([p1, p2]))
        merged = person_edges.setdefault(key, {"p1": key[0], "p2": key[1], "p1Wins": 0, "p2Wins": 0, "draws": 0})
        sw, tw = rec["p1Wins"], rec["p2Wins"]
        if p1 == key[0]:
            merged["p1Wins"] += sw
            merged["p2Wins"] += tw
        else:
            merged["p1Wins"] += tw
            merged["p2Wins"] += sw
        merged["draws"] += rec["draws"]

    edges = []
    for rec in person_edges.values():
        rec["total"] = rec["p1Wins"] + rec["p2Wins"] + rec["draws"]
        edges.append(rec)

    person_ids = sorted({person_for(g["white"]["username"]) for g in all_games} |
                         {person_for(g["black"]["username"]) for g in all_games})
    players = {p: {"id": p, "displayName": DISPLAY_NAMES.get(p, p),
                   "totalGames": 0, "wins": 0, "losses": 0, "draws": 0} for p in person_ids}
    for rec in edges:
        n = rec["total"]
        players[rec["p1"]]["totalGames"] += n
        players[rec["p1"]]["wins"] += rec["p1Wins"]
        players[rec["p1"]]["losses"] += rec["p2Wins"]
        players[rec["p1"]]["draws"] += rec["draws"]
        players[rec["p2"]]["totalGames"] += n
        players[rec["p2"]]["wins"] += rec["p2Wins"]
        players[rec["p2"]]["losses"] += rec["p1Wins"]
        players[rec["p2"]]["draws"] += rec["draws"]

    # Reuse avatars already fetched into data.json by refresh.py, if present.
    avatar_by_person = {}
    try:
        with open("data.json") as f:
            avatar_by_person = {p["id"]: p.get("avatar") for p in json.load(f).get("players", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    for p in players.values():
        p["avatar"] = avatar_by_person.get(p["id"])

    nemesis_map, _ = compute_nemesis(person_ids, edges)
    for p in players.values():
        p["nemesis"] = nemesis_map[p["id"]]["nemesis"]
        p["nemesisScore"] = nemesis_map[p["id"]]["nemesisScore"]

    return list(players.values()), edges


def process_tournament(tid):
    meta = get_json(f"https://api.chess.com/pub/tournament/{tid}")
    if not meta:
        return None
    round_data = get_json(f"https://api.chess.com/pub/tournament/{tid}/1")
    if not round_data:
        return None

    standings = []
    for p in round_data.get("players", []):
        uname = p["username"].lower()
        standings.append({
            "person": person_for(uname),
            "username": uname,
            "displayName": DISPLAY_NAMES.get(person_for(uname), uname),
            "points": p.get("points", 0),
            "place": p.get("place_finish"),
        })
    standings.sort(key=lambda s: s["place"] if s["place"] is not None else 999)

    # Biggest rating upset this week: decisive game where the lower-rated
    # player won, ranked by rating gap.
    best_upset = None
    for g in round_data.get("games", []):
        white, black = g.get("white", {}), g.get("black", {})
        if white.get("result") == "win":
            winner, loser = white, black
        elif black.get("result") == "win":
            winner, loser = black, white
        else:
            continue  # draw of some kind
        gap = (loser.get("rating") or 0) - (winner.get("rating") or 0)
        if gap > 0 and (best_upset is None or gap > best_upset["gap"]):
            wu, lu = winner["username"].lower(), loser["username"].lower()
            best_upset = {
                "gap": gap,
                "winnerPerson": person_for(wu),
                "winnerUsername": wu,
                "winnerDisplayName": DISPLAY_NAMES.get(person_for(wu), wu),
                "winnerRating": winner.get("rating"),
                "loserPerson": person_for(lu),
                "loserUsername": lu,
                "loserDisplayName": DISPLAY_NAMES.get(person_for(lu), lu),
                "loserRating": loser.get("rating"),
                "gameUrl": g.get("url"),
            }

    finish_time = meta.get("finish_time")
    start_time = meta.get("start_time")
    date = (
        datetime.fromtimestamp(finish_time, tz=timezone.utc).strftime("%Y-%m-%d")
        if finish_time else None
    )
    settings = meta.get("settings") or {}
    duration_sec = (finish_time - start_time) if (finish_time and start_time) else None

    week = {
        "id": tid,
        "name": meta.get("name"),
        "date": date,
        "playerCount": len(standings),
        "standings": standings,
        "upset": best_upset,
        "timeControl": settings.get("time_control"),
        "timeClass": settings.get("time_class"),
        "durationSec": duration_sec,
    }
    return week, round_data.get("games", [])


def main():
    weeks = []
    special_events = []
    all_games = []
    for t in TOURNAMENTS:
        tid = extract_id(t["id"])
        series = t.get("series", "hopen")
        print(f"Fetching {tid} ({series})...")
        result = process_tournament(tid)
        if not result:
            continue
        week, games = result
        week["series"] = series
        week["seriesLabel"] = SERIES.get(series, {}).get("label", series)
        all_games.extend(games)
        if SERIES.get(series, {}).get("cumulative", True):
            weeks.append(week)
        else:
            special_events.append(week)
    weeks.sort(key=lambda w: w["date"] or "")
    special_events.sort(key=lambda w: w["date"] or "")

    players, edges = build_arena_graph(all_games)

    # ---- cumulative Sunday leaderboard ----
    agg = {}
    for w in weeks:
        for s in w["standings"]:
            a = agg.setdefault(s["person"], {
                "person": s["person"],
                "displayName": s["displayName"],
                "weeksPlayed": 0,
                "totalPoints": 0,
                "firsts": 0,
                "podiums": 0,
                "placeSum": 0,
            })
            a["weeksPlayed"] += 1
            a["totalPoints"] += s["points"]
            a["placeSum"] += s["place"] or 0
            if s["place"] == 1:
                a["firsts"] += 1
            if s["place"] and s["place"] <= 3:
                a["podiums"] += 1

    cumulative = []
    for a in agg.values():
        a["avgPlace"] = round(a["placeSum"] / a["weeksPlayed"], 2) if a["weeksPlayed"] else None
        del a["placeSum"]
        cumulative.append(a)
    cumulative.sort(key=lambda a: (-a["firsts"], -a["podiums"], a["avgPlace"] or 99))

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks,
        "cumulative": cumulative,
        "specialEvents": special_events,
        "players": players,
        "edges": edges,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    print(f"\nWrote {OUT_FILE}: {len(weeks)} Hopen weeks, {len(special_events)} special events, {len(cumulative)} players.")


if __name__ == "__main__":
    main()
