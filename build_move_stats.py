#!/usr/bin/env python3
"""
SSJakk opening move-frequency pipeline.

Walks the first few plies of every Sunday arena game and records, per
person, which square their own 1st, 2nd, 3rd... move of the game landed
on -- keyed by OWN move number, not raw game ply, so a player's "first
move" means the same thing whether they had White or Black in that
particular game (raw game ply would silently drop every Black game from
"ply 1", which isn't what a per-player "your first move" view should do).
Feeds the animated opening-heatmap planned for the Player Stats page
(autoplay through move 1 -> MAX_OWN_MOVES).

Reads the PGN scratch cache build_games.py writes earlier in the same job
run (.game_pgns_cache.json) -- chess.com's own move text isn't ours to
keep around long-term, only the derived square-frequency counts are, so
this never writes the PGNs themselves anywhere committed.

Run it right after build_games.py, same job (needs its PGN cache):

    python build_games.py
    python build_move_stats.py
    git add move_stats.json build_move_stats.py
    git commit -m "Add move-frequency stats"
    git push

Requires: pip install chess
"""

import io
import json
import os
import sys
from datetime import datetime, timezone

import chess
import chess.pgn

from config import USERNAME_TO_PERSON

GAMES_FILE = "games.json"
PGN_CACHE_FILE = ".game_pgns_cache.json"
OUT_FILE = "move_stats.json"

# Five of each player's own moves is enough to cover almost every named
# opening's main line while staying squarely in "opening", not
# "middlegame", territory.
MAX_OWN_MOVES = 5


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def own_move_squares(pgn_text):
    """Returns {'white': [sq1, sq2, ...], 'black': [sq1, sq2, ...]} --
    each list holds up to MAX_OWN_MOVES square names, one per that side's
    own move, in order. A game that ends early just comes back shorter;
    None means the PGN itself didn't parse at all."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None
    board = game.board()
    out = {"white": [], "black": []}
    for move in game.mainline_moves():
        side = "white" if board.turn == chess.WHITE else "black"
        if len(out[side]) < MAX_OWN_MOVES:
            out[side].append(chess.square_name(move.to_square))
        board.push(move)
        if len(out["white"]) >= MAX_OWN_MOVES and len(out["black"]) >= MAX_OWN_MOVES:
            break
    return out


def main():
    if not os.path.exists(GAMES_FILE):
        print(f"! {GAMES_FILE} not found -- run build_games.py first. Skipping.", file=sys.stderr)
        return
    with open(GAMES_FILE) as f:
        games_data = json.load(f)
    if not os.path.exists(PGN_CACHE_FILE):
        print(f"! {PGN_CACHE_FILE} not found -- run build_games.py first (same job). Skipping.", file=sys.stderr)
        return
    with open(PGN_CACHE_FILE) as f:
        pgn_by_id = json.load(f)

    person_counts = {}   # person -> [{square: count}, ...] length MAX_OWN_MOVES
    person_games = {}    # person -> games that contributed at least one tracked move
    club_counts = [dict() for _ in range(MAX_OWN_MOVES)]
    club_games = 0
    parse_errors = 0
    missing_pgn = 0

    def bump(bucket_list, idx, sq):
        bucket_list[idx][sq] = bucket_list[idx].get(sq, 0) + 1

    for g in games_data.get("games", []):
        pgn_text = pgn_by_id.get(g["id"])
        if not pgn_text:
            missing_pgn += 1
            continue
        try:
            squares = own_move_squares(pgn_text)
        except Exception as e:
            print(f"  ! error parsing {g['id']}: {e}", file=sys.stderr)
            parse_errors += 1
            continue
        if not squares:
            parse_errors += 1
            continue

        game_contributed = False
        for side in ("white", "black"):
            if not squares[side]:
                continue
            person = person_for(g[side]["username"])
            bucket = person_counts.setdefault(person, [dict() for _ in range(MAX_OWN_MOVES)])
            for i, sq in enumerate(squares[side]):
                bump(bucket, i, sq)
                bump(club_counts, i, sq)
            person_games[person] = person_games.get(person, 0) + 1
            game_contributed = True
        if game_contributed:
            club_games += 1

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "maxOwnMoves": MAX_OWN_MOVES,
        "club": {"gamesAnalyzed": club_games, "moveSquares": club_counts},
        "players": {
            person: {"gamesAnalyzed": person_games[person], "moveSquares": buckets}
            for person, buckets in person_counts.items()
        },
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    total = len(games_data.get("games", []))
    print(f"\nWrote {OUT_FILE}: {len(person_counts)} players, "
          f"{club_games}/{total} games contributed "
          f"({missing_pgn} had no cached PGN, {parse_errors} failed to parse).")


if __name__ == "__main__":
    main()
