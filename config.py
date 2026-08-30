"""
Shared roster configuration for SSJakk leaderboard scripts (refresh.py,
backfill_sunday.py, build_games.py).

Edit this file when the club roster changes - all scripts import from here so the
mapping only needs to be updated in one place.
"""

import re

# Every Chess.com username currently in the club (case-insensitive).
USERNAMES = [
    "deluludvig",
    "efdalen",
    "IdaMuren",
    "Lateks12",
    "martinaces",
    "noodle_addict1987",
    "parasosialist",
    "rookvg",
    "Shortking1996",
    "Skjellstad",
    "stinemartolini",
]

# Map each username to a person id. Give two usernames the same person id
# if they're alt accounts of the same human (games between a person's own
# alt accounts are dropped, not counted as a "rivalry").
USERNAME_TO_PERSON = {
    "deluludvig": "deluludvig",
    "efdalen": "efdalen",
    "idamuren": "idamuren",
    "lateks12": "lateks12",
    "martinaces": "martin",
    "shortking1996": "martin",
    "noodle_addict1987": "noodle_addict1987",
    "parasosialist": "parasosialist",
    "rookvg": "rookvg",
    "skjellstad": "skjellstad",
    "stinemartolini": "stinemartolini",
}

# What to show on the dashboard for each person id (first names, per club preference).
DISPLAY_NAMES = {
    "deluludvig": "Ludvig",
    "efdalen": "Erik",
    "idamuren": "Ida",
    "lateks12": "Michael",
    "martin": "Martin",
    "noodle_addict1987": "Didrik",
    "parasosialist": "Mathias",
    "rookvg": "Isak",
    "skjellstad": "Amund",
    "stinemartolini": "Stine",
}

# Which account's Chess.com profile picture to show for a merged person.
# (Only needed for person ids with more than one account.)
AVATAR_ACCOUNT_OVERRIDE = {
    "martin": "shortking1996",
}

HEADERS = {"User-Agent": "SSJakk-Leaderboard/1.0 (contact: a.skjellstad@gmail.com)"}

# ---------------------------------------------------------------------------
# Every tournament played so far, oldest first. Each entry can use a full
# tournament URL or just the id (the part after /tournament/ or
# /tournament/live/arena/ in the URL) — both forms work.
#
# `series` groups a tournament with others of its kind. "hopen" is the
# regular weekly series — its weeks feed the cumulative Sunday Standings
# podium/leaderboard. Anything else (a one-off memorial arena, a holiday
# tournament, etc.) gets its own series key: give it a short slug, add an
# entry for it in SERIES below (cumulative: False keeps it out of the main
# leaderboard math and shows it as its own "special event" card instead),
# and it's handled the same way any future one-off will be — no other code
# changes needed. All arena games, from every series, still count toward
# the arena-only head-to-head graph, the Rivalry tab (lifetime, unaffected
# by this list), and everything on the Trends tab.
#
# Shared by backfill_sunday.py and build_games.py, so a new week (or a new
# one-off event) only needs adding here.
# ---------------------------------------------------------------------------
TOURNAMENTS = [
    {"id": "hopen-31162139", "series": "hopen"},
    {"id": "hopen-31181223", "series": "hopen"},
    {"id": "hopen-arena-31263405", "series": "hopen"},
    {"id": "hopen-arena-31263415", "series": "hopen"},
    {"id": "hopen-arena-31051706", "series": "hopen"},
    {"id": "hopen-31068160", "series": "hopen"},
    {"id": "bjorn-jens-memorial-31068698", "series": "bjorn-jens-memorial"},
]

# Metadata per series. `cumulative: True` means the series' weeks count
# toward the main Sunday Standings podium and leaderboard math; `False`
# means it gets its own "special event" section instead, kept separate.
SERIES = {
    "hopen": {"label": "Hopen Arena", "cumulative": True},
    "bjorn-jens-memorial": {"label": "Bjørn Jens Memorial Arena", "cumulative": False},
}

# Backward-compatible flat id list — build_games.py just wants every game
# from every series regardless of cumulative status, so it reads this.
TOURNAMENT_IDS = [t["id"] for t in TOURNAMENTS]


def extract_id(entry):
    m = re.search(r"tournament/(?:live/arena/)?([a-z0-9\-]+)", entry, re.I)
    return m.group(1) if m else entry


def compute_nemesis(person_ids, edges, thresholds=(5, 3, 1)):
    """For each person, find the opponent whose head-to-head record sits
    closest to an even 50/50 split - not who beats them the most (that's
    a bad matchup, not a rivalry), but the one they can never shake either
    way. Falls back to a smaller minimum-game-count if nobody clears the
    first threshold (useful for the smaller Sunday-arena-only sample).
    Shared by refresh.py (lifetime) and backfill_sunday.py (arena-only) so
    both scopes use the exact same definition of "nemesis"."""
    per_opp = {p: {} for p in person_ids}
    for rec in edges:
        p1, p2 = rec["p1"], rec["p2"]
        if p1 not in per_opp or p2 not in per_opp:
            continue
        per_opp[p1][p2] = {"wins": rec["p1Wins"], "losses": rec["p2Wins"], "draws": rec["draws"], "total": rec["total"]}
        per_opp[p2][p1] = {"wins": rec["p2Wins"], "losses": rec["p1Wins"], "draws": rec["draws"], "total": rec["total"]}

    result = {}
    for p in person_ids:
        nemesis, best_closeness, best_total = None, 2, -1
        for min_games in thresholds:
            for opp, rec in per_opp[p].items():
                if rec["total"] < min_games:
                    continue
                rate = (rec["wins"] + rec["draws"] * 0.5) / rec["total"]
                closeness = abs(rate - 0.5)
                if closeness < best_closeness or (closeness == best_closeness and rec["total"] > best_total):
                    best_closeness, nemesis, best_total = closeness, opp, rec["total"]
            if nemesis:
                break
        result[p] = {"nemesis": nemesis, "nemesisScore": per_opp[p].get(nemesis) if nemesis else None}
    return result, per_opp
