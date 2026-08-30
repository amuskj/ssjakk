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


def compute_week_rating_swings(games):
    """Per-account first-vs-last rating this week, ordered by end_time --
    powers the "biggest rating gain" storyline. Draws and losses count too;
    this is about rating movement, not results."""
    by_user = {}
    for g in games:
        et = g.get("end_time")
        if not et:
            continue
        for side in ("white", "black"):
            info = g.get(side, {})
            u = (info.get("username") or "").lower()
            rating = info.get("rating")
            if u and rating is not None:
                by_user.setdefault(u, []).append((et, rating))
    swings = []
    for u, pts in by_user.items():
        pts.sort(key=lambda x: x[0])
        if len(pts) >= 2:
            swings.append({"username": u, "gain": pts[-1][1] - pts[0][1],
                           "fromRating": pts[0][1], "toRating": pts[-1][1]})
    return swings


def compute_form(all_games, n=5):
    """Each person's last n arena results, oldest first ('W'/'L'/'D'),
    merged across alt accounts by actual chronological order (not just
    concatenated per-username) -- powers the little form-pill row on the
    Sunday Standings tab and the player detail card."""
    per_person_pts = {}
    for g in all_games:
        et = g.get("end_time") or 0
        res = outcome(g)
        for side in ("white", "black"):
            u = (g.get(side, {}).get("username") or "").lower()
            if not u:
                continue
            p = person_for(u)
            code = "D" if res == "draw" else ("W" if res == side else "L")
            per_person_pts.setdefault(p, []).append((et, code))
    result = {}
    for p, pts in per_person_pts.items():
        pts.sort(key=lambda x: x[0])
        result[p] = [c for _, c in pts[-n:]]
    return result


def compute_active_streaks(all_games):
    """Longest *current* (still-active, most-recent-games-back) win streak
    per person across every arena game played so far, chronologically."""
    per_user = {}
    for g in sorted(all_games, key=lambda g: g.get("end_time") or 0):
        res = outcome(g)
        for side in ("white", "black"):
            u = (g.get(side, {}).get("username") or "").lower()
            if not u:
                continue
            per_user.setdefault(u, []).append(res == side)

    per_person = {}
    for u, results in per_user.items():
        p = person_for(u)
        per_person.setdefault(p, []).extend(results)

    streaks = {}
    for p, results in per_person.items():
        streak = 0
        for is_win in reversed(results):
            if is_win:
                streak += 1
            else:
                break
        streaks[p] = streak
    return streaks


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

    # Reuse avatars + profile facts (join date, league, current ratings)
    # already fetched into data.json by refresh.py, if present, rather than
    # hitting the Chess.com profile API a second time here.
    profile_by_person = {}
    try:
        with open("data.json") as f:
            profile_by_person = {p["id"]: p for p in json.load(f).get("players", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    for p in players.values():
        src = profile_by_person.get(p["id"], {})
        p["avatar"] = src.get("avatar")
        p["joined"] = src.get("joined")
        p["league"] = src.get("league")
        p["ratings"] = src.get("ratings")

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
    games_by_tid = {}
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
        games_by_tid[tid] = games
        all_games.extend(games)
        if SERIES.get(series, {}).get("cumulative", True):
            weeks.append(week)
        else:
            special_events.append(week)
    weeks.sort(key=lambda w: w["date"] or "")
    special_events.sort(key=lambda w: w["date"] or "")

    players, edges = build_arena_graph(all_games)
    form_by_person = compute_form(all_games)
    for p in players:
        p["form"] = form_by_person.get(p["id"], [])

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
        a["form"] = form_by_person.get(a["person"], [])
        cumulative.append(a)
    cumulative.sort(key=lambda a: (-a["firsts"], -a["podiums"], a["avgPlace"] or 99))

    # ---- this week's storylines: biggest upset (already computed per-week
    # above), biggest rating gain, longest active win streak among this
    # week's players, and whether the cumulative #1 changed -- surfaced as
    # a callout on the site and fed into the automated Discord recap. ----
    storylines = None
    if weeks:
        latest = weeks[-1]
        latest_games = games_by_tid.get(latest["id"], [])

        rating_gain = None
        gains = [s for s in compute_week_rating_swings(latest_games) if s["gain"] > 0]
        if gains:
            best = max(gains, key=lambda s: s["gain"])
            p = person_for(best["username"])
            rating_gain = {
                "person": p, "displayName": DISPLAY_NAMES.get(p, p),
                "gain": best["gain"], "fromRating": best["fromRating"], "toRating": best["toRating"],
            }

        streak_entry = None
        streaks = compute_active_streaks(all_games)
        latest_participants = {s["person"] for s in latest["standings"]}
        eligible = {p: n for p, n in streaks.items() if p in latest_participants and n >= 2}
        if eligible:
            top_p = max(eligible, key=eligible.get)
            streak_entry = {"person": top_p, "displayName": DISPLAY_NAMES.get(top_p, top_p), "length": eligible[top_p]}

        new_leader = None
        if len(weeks) >= 2:
            prior_agg = {}
            for w in weeks[:-1]:
                for s in w["standings"]:
                    a = prior_agg.setdefault(s["person"], {"firsts": 0, "podiums": 0, "placeSum": 0, "weeksPlayed": 0})
                    a["weeksPlayed"] += 1
                    a["placeSum"] += s["place"] or 0
                    if s["place"] == 1:
                        a["firsts"] += 1
                    if s["place"] and s["place"] <= 3:
                        a["podiums"] += 1
            prior_ranked = sorted(
                prior_agg.items(),
                key=lambda kv: (-kv[1]["firsts"], -kv[1]["podiums"],
                                 (kv[1]["placeSum"] / kv[1]["weeksPlayed"]) if kv[1]["weeksPlayed"] else 99),
            )
            prior_leader = prior_ranked[0][0] if prior_ranked else None
            current_leader = cumulative[0]["person"] if cumulative else None
            if prior_leader and current_leader and prior_leader != current_leader:
                new_leader = {
                    "person": current_leader, "displayName": DISPLAY_NAMES.get(current_leader, current_leader),
                    "previousPerson": prior_leader, "previousDisplayName": DISPLAY_NAMES.get(prior_leader, prior_leader),
                }

        storylines = {
            "week": latest["id"],
            "weekDate": latest["date"],
            "upset": latest.get("upset"),
            "ratingGain": rating_gain,
            "streak": streak_entry,
            "newLeader": new_leader,
        }

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks,
        "cumulative": cumulative,
        "specialEvents": special_events,
        "players": players,
        "edges": edges,
        "storylines": storylines,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    print(f"\nWrote {OUT_FILE}: {len(weeks)} Hopen weeks, {len(special_events)} special events, {len(cumulative)} players.")


if __name__ == "__main__":
    main()
