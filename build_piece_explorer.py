#!/usr/bin/env python3
"""
SSJakk Piece Explorer pipeline.

Feeds the interactive Piece Explorer on the Player Stats page: click one
of your 16 starting pieces to see where its opening moves actually go
(not book theory -- your own games), click a lit destination to see how
your opponents replied, with real win/loss/draw coloring and links back
to the actual chess.com games behind each number.

For each of a player's own moves within the opening window (own move
1..MAX_OWN_MOVES -- the same "your Nth own move" convention build_move_stats.py
uses, so a player's "first move" means the same thing whether they had
White or Black that game), this records the exact square the move
originated from -- but only while that square is still one of the
piece's own 16 starting squares. That's "the first time this piece
leaves home" without needing to track it separately: once a piece has
moved, its square is no longer its own start square, so a later move of
the same piece naturally won't match `from_sq in START_TYPE` again.

Own-perspective canonicalization: every square is mirrored onto White's
home ranks with chess.square_mirror() whenever the tracked player had
Black that game, so a player's own squares and their opponent's squares
always land on the same canonical ranks (1/2 for the player's own
pieces, 7/8 for the opponent's) regardless of which color they actually
played. This canonicalization always uses the TRACKED PLAYER's color for
both sides' moves in a game -- an opponent's reply is mirrored the same
way as the player's own move it replies to, not by the opponent's own
color, so the two halves of one exchange land on consistent squares.

One-exchange move pairs: whenever a player's own move is recorded, the
very next ply (their opponent's immediate reply) is also recorded under
that destination's `replies`, but only when the reply itself falls
within THAT side's own opening-move budget -- no further alternation
past one exchange. Every outcome and game sample on a reply is still
scored from the TRACKED PLAYER's perspective (this is their practice
page, not their opponent's), so "outcomes" and "games" mean the same
thing everywhere in this file: how games with this exact exchange in
them turned out for the player whose data this is.

Reads the same ephemeral PGN cache build_games.py writes earlier in the
same job run (.game_pgns_cache.json) -- chess.com's own move text isn't
ours to keep around long-term, only these derived counts are, so this
(like build_move_stats.py) never writes the PGNs themselves anywhere
committed.

Run it right after build_games.py, same job (needs its PGN cache):

    python build_games.py
    python build_piece_explorer.py
    git add piece_explorer.json build_piece_explorer.py
    git commit -m "Add piece explorer stats"
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

from config import USERNAME_TO_PERSON, DISPLAY_NAMES

GAMES_FILE = "games.json"
PGN_CACHE_FILE = ".game_pgns_cache.json"
OUT_FILE = "piece_explorer.json"

# Same opening window as build_move_stats.py -- enough to cover almost
# every named opening's main line while staying in "opening", not
# "middlegame", territory.
MAX_OWN_MOVES = 5

# Capped, real sample of the actual games behind a number -- enough for
# a "browse the games" list without trying to enumerate every one of
# e.g. 40 games a specific exchange shows up in club-wide.
MAX_GAME_SAMPLE = 6

START_TYPE = {
    "a1": "rook", "b1": "knight", "c1": "bishop", "d1": "queen",
    "e1": "king", "f1": "bishop", "g1": "knight", "h1": "rook",
    "a2": "pawn", "b2": "pawn", "c2": "pawn", "d2": "pawn",
    "e2": "pawn", "f2": "pawn", "g2": "pawn", "h2": "pawn",
}

PIECE_NAME = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def display_name_for(person):
    return DISPLAY_NAMES.get(person, person) if person else "opponent"


def canonical_square(square, tracked_side_is_white):
    """Mirror onto White's home ranks when the TRACKED PLAYER had Black
    that game -- applied to both players' moves alike, see module docstring."""
    return square if tracked_side_is_white else chess.square_mirror(square)


def outcome_for(person_side, result):
    """`result` is games.json's own "white"/"black"/"draw"; `person_side`
    is which color the tracked player had that game."""
    if result == "draw":
        return "draw"
    return "win" if result == person_side else "loss"


def new_dest_entry():
    return {"count": 0, "outcomes": {"win": 0, "loss": 0, "draw": 0}, "games": [], "replies": {}}


def new_reply_entry(piece_type):
    return {"pieceType": piece_type, "count": 0, "outcomes": {"win": 0, "loss": 0, "draw": 0}, "games": []}


def bump_outcome(entry, outcome):
    entry["outcomes"][outcome] += 1


def add_game_sample(entry, game_row, max_sample=MAX_GAME_SAMPLE):
    entry["games"].append(game_row)
    entry["games"].sort(key=lambda g: g["date"], reverse=True)
    del entry["games"][max_sample:]


def process_game(pgn_text, white_person, black_person, result, url, date, origins_by_person):
    """Walks one game's mainline once, updating origins_by_person for
    whichever of the two players are tracked club members. Returns True
    if the game contributed at least one recorded move for either side."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return False
    board = game.board()
    moves = list(game.mainline_moves())
    own_count = {chess.WHITE: 0, chess.BLACK: 0}
    contributed = False

    for i, move in enumerate(moves):
        side = board.turn
        is_white = side == chess.WHITE
        person = white_person if is_white else black_person
        side_label = "white" if is_white else "black"
        own_count[side] += 1

        pending_reply = None
        if person and own_count[side] <= MAX_OWN_MOVES:
            piece = board.piece_at(move.from_square)
            piece_type = PIECE_NAME.get(piece.piece_type, "?") if piece else "?"
            from_sq = chess.square_name(canonical_square(move.from_square, is_white))
            to_sq = chess.square_name(canonical_square(move.to_square, is_white))

            if from_sq in START_TYPE:
                origins = origins_by_person.setdefault(person, {})
                origin_entry = origins.setdefault(from_sq, {"pieceType": piece_type, "destinations": {}})
                dest_entry = origin_entry["destinations"].setdefault(to_sq, new_dest_entry())
                outcome = outcome_for(side_label, result)
                opp_person = black_person if is_white else white_person

                dest_entry["count"] += 1
                bump_outcome(dest_entry, outcome)
                add_game_sample(dest_entry, {
                    "opponent": display_name_for(opp_person),
                    "date": date, "result": outcome, "url": url,
                })
                contributed = True
                pending_reply = (dest_entry, is_white, outcome, opp_person)

        board.push(move)

        # The very next ply is the opponent's immediate reply -- log it
        # under this destination's `replies`, but only if it's within
        # THEIR OWN opening-move budget too (own_count[opp_side] hasn't
        # been bumped for this ply yet, so +1 previews it).
        if pending_reply is not None and i + 1 < len(moves):
            dest_entry, was_white, outcome, opp_person = pending_reply
            opp_side = chess.BLACK if was_white else chess.WHITE
            if own_count[opp_side] + 1 <= MAX_OWN_MOVES:
                reply_move = moves[i + 1]
                reply_piece = board.piece_at(reply_move.from_square)
                reply_piece_type = PIECE_NAME.get(reply_piece.piece_type, "?") if reply_piece else "?"
                r_from = chess.square_name(canonical_square(reply_move.from_square, was_white))
                r_to = chess.square_name(canonical_square(reply_move.to_square, was_white))
                reply_key = f"{r_from}>{r_to}"
                reply_entry = dest_entry["replies"].setdefault(reply_key, new_reply_entry(reply_piece_type))
                reply_entry["count"] += 1
                bump_outcome(reply_entry, outcome)
                add_game_sample(reply_entry, {
                    "opponent": display_name_for(opp_person),
                    "date": date, "result": outcome, "url": url,
                })

    return contributed


def compute_times_moved_and_bloom(origins):
    """Fills in each origin's timesMoved (from its own destination
    counts) and returns a combined origin+destination frequency map --
    the single "bloom" heatmap for the reveal stage."""
    bloom = {}
    for sq, entry in origins.items():
        times_moved = sum(d["count"] for d in entry["destinations"].values())
        entry["timesMoved"] = times_moved
        bloom[sq] = bloom.get(sq, 0) + times_moved
        for d, dentry in entry["destinations"].items():
            bloom[d] = bloom.get(d, 0) + dentry["count"]
    return bloom


def merge_outcomes(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in ("win", "loss", "draw")}


def merge_games(a, b, max_sample=MAX_GAME_SAMPLE):
    merged = (a or []) + (b or [])
    merged.sort(key=lambda g: g["date"], reverse=True)
    return merged[:max_sample]


def build_club_origins(origins_by_person):
    club_origins = {}
    for origins in origins_by_person.values():
        for sq, entry in origins.items():
            c_entry = club_origins.setdefault(sq, {"pieceType": entry["pieceType"], "destinations": {}})
            for d, dentry in entry["destinations"].items():
                c_dest = c_entry["destinations"].setdefault(d, new_dest_entry())
                c_dest["count"] += dentry["count"]
                c_dest["outcomes"] = merge_outcomes(c_dest["outcomes"], dentry["outcomes"])
                c_dest["games"] = merge_games(c_dest["games"], dentry["games"])
                for rk, rentry in dentry["replies"].items():
                    c_reply = c_dest["replies"].setdefault(rk, new_reply_entry(rentry["pieceType"]))
                    c_reply["count"] += rentry["count"]
                    c_reply["outcomes"] = merge_outcomes(c_reply["outcomes"], rentry["outcomes"])
                    c_reply["games"] = merge_games(c_reply["games"], rentry["games"])
    return club_origins


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

    origins_by_person = {}
    person_games_count = {}
    club_games = 0
    total = 0
    missing_pgn = 0
    parse_errors = 0

    for g in games_data.get("games", []):
        total += 1
        pgn_text = pgn_by_id.get(g["id"])
        if not pgn_text:
            missing_pgn += 1
            continue
        white_person = person_for(g["white"]["username"])
        black_person = person_for(g["black"]["username"])
        try:
            contributed = process_game(
                pgn_text, white_person, black_person, g["result"], g["url"], g["date"],
                origins_by_person,
            )
        except Exception as e:
            print(f"  ! error parsing {g['id']}: {e}", file=sys.stderr)
            parse_errors += 1
            continue
        if contributed:
            club_games += 1
            for p in (white_person, black_person):
                person_games_count[p] = person_games_count.get(p, 0) + 1

    players_out = {}
    for person, origins in origins_by_person.items():
        bloom = compute_times_moved_and_bloom(origins)
        players_out[person] = {
            "gamesAnalyzed": person_games_count.get(person, 0),
            "origins": origins,
            "bloom": bloom,
        }

    club_origins = build_club_origins(origins_by_person)
    club_bloom = compute_times_moved_and_bloom(club_origins)

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "maxOwnMoves": MAX_OWN_MOVES,
        "club": {"gamesAnalyzed": club_games, "origins": club_origins, "bloom": club_bloom},
        "players": players_out,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"\nWrote {OUT_FILE}: {len(players_out)} players, "
          f"{club_games}/{total} games contributed "
          f"({missing_pgn} had no cached PGN, {parse_errors} failed to parse).")


if __name__ == "__main__":
    main()
