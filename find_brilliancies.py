#!/usr/bin/env python3
"""
SSJakk brilliant-move finder.

Runs Stockfish over every Sunday arena game to find genuine brilliancies --
not just decisive moments, but a *sacrifice* (giving up real material) that
still holds up under engine review as an objectively strong try, in a
position that wasn't already trivially winning. Writes brilliancies.json,
which index.html's "Brilliant Moves" section turns into click-to-solve
puzzles (find the move yourself before revealing the answer).

Incremental by design: games already analyzed (tracked by id, right in
brilliancies.json) are skipped on every later run, so the GitHub Actions
workflow can call this after every refresh without redoing work -- only
brand-new games get analyzed. The very first run analyzes the whole
Hopen Arena history; every run after that only sees whatever's new.

Needs `stockfish` on PATH (the GitHub Actions workflow apt-installs it)
and games.json + the PGN scratch cache (.game_pgns_cache.json) that
build_games.py just wrote -- run this right after build_games.py, in the
same job, so that cache is still there.

Tunables below trade off strictness / runtime; PLY_TIME_LIMIT is the
biggest lever on how long a full run takes.
"""

import json
import os
import shutil
import sys

import chess
import chess.engine
import chess.pgn
import io

from config import USERNAME_TO_PERSON, DISPLAY_NAMES

GAMES_FILE = "games.json"
PGN_CACHE_FILE = ".game_pgns_cache.json"
OUT_FILE = "brilliancies.json"

PLY_TIME_LIMIT = 0.25       # seconds per position -- the main runtime lever
SKIP_FIRST_PLIES = 10       # brilliancies don't happen in opening theory
SWING_TOLERANCE = 40        # cp: how close to "assumed best play" counts as objectively strong
MAX_EVAL_BEFORE = 500       # cp: skip already-crushing positions (not a turning point)
MIN_EVAL_AFTER = -100       # cp: the sac must still hold up, not just fail
MIN_MATERIAL_RISKED = 2     # at least a minor piece -- no pawn pokes

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def find_engine():
    path = shutil.which("stockfish")
    if not path:
        print("! stockfish not found on PATH -- skipping brilliancy analysis this run.", file=sys.stderr)
        return None
    return path


def analyze_game(engine, game_meta, pgn_text):
    """Returns a list of brilliancy dicts found in this one game."""
    found = []
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return found
    board = game.board()
    ply = 0
    for move in game.mainline_moves():
        ply += 1
        if ply <= SKIP_FIRST_PLIES:
            board.push(move)
            continue

        mover_color = board.turn
        fen_before = board.fen()
        info_before = engine.analyse(board, chess.engine.Limit(time=PLY_TIME_LIMIT))
        cp_before = info_before["score"].pov(mover_color).score(mate_score=10000)

        moved_piece = board.piece_at(move.from_square)
        captured_piece = board.piece_at(move.to_square)
        san = board.san(move)
        board.push(move)

        info_after = engine.analyse(board, chess.engine.Limit(time=PLY_TIME_LIMIT))
        cp_after_mover = -info_after["score"].pov(board.turn).score(mate_score=10000)

        is_attacked = board.is_attacked_by(not mover_color, move.to_square)
        risked = PIECE_VALUES.get(moved_piece.piece_type, 0) - (
            PIECE_VALUES.get(captured_piece.piece_type, 0) if captured_piece else 0)
        is_sac = is_attacked and moved_piece.piece_type != chess.PAWN and risked >= MIN_MATERIAL_RISKED

        if (is_sac
                and cp_after_mover >= cp_before - SWING_TOLERANCE
                and abs(cp_before) < MAX_EVAL_BEFORE
                and cp_after_mover > MIN_EVAL_AFTER):
            white_person = person_for(game_meta["whiteUsername"])
            black_person = person_for(game_meta["blackUsername"])
            mover_person = white_person if mover_color == chess.WHITE else black_person
            opp_person = black_person if mover_color == chess.WHITE else white_person
            found.append({
                "id": f"{game_meta['gameId']}-{ply}",
                "gameId": game_meta["gameId"],
                "gameUrl": game_meta["gameUrl"],
                "tournamentId": game_meta["tournamentId"],
                "date": game_meta["date"],
                "ply": ply,
                "moveNumber": (ply + 1) // 2,
                "mover": "white" if mover_color == chess.WHITE else "black",
                "person": mover_person,
                "displayName": DISPLAY_NAMES.get(mover_person, mover_person),
                "opponentPerson": opp_person,
                "opponentDisplayName": DISPLAY_NAMES.get(opp_person, opp_person),
                "fenBefore": fen_before,
                "correctSan": san,
                "correctUci": move.uci(),
                "evalBefore": cp_before,
                "evalAfter": cp_after_mover,
                "materialRisked": risked,
            })
    return found


def main():
    with open(GAMES_FILE) as f:
        games_data = json.load(f)
    if not os.path.exists(PGN_CACHE_FILE):
        print(f"! {PGN_CACHE_FILE} not found -- run build_games.py first (same job). Skipping.", file=sys.stderr)
        return
    with open(PGN_CACHE_FILE) as f:
        pgn_by_id = json.load(f)

    if os.path.exists(OUT_FILE):
        with open(OUT_FILE) as f:
            existing = json.load(f)
    else:
        existing = {"analyzedGameIds": [], "brilliancies": []}

    analyzed = set(existing.get("analyzedGameIds", []))
    to_analyze = [g for g in games_data.get("games", []) if g["id"] not in analyzed and g["id"] in pgn_by_id]

    if not to_analyze:
        print("No new games to analyze.")
        return

    engine_path = find_engine()
    if not engine_path:
        return

    print(f"Analyzing {len(to_analyze)} new game(s) for brilliancies "
          f"(skipping {len(analyzed)} already done)...")
    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    new_brilliancies = []
    try:
        for g in to_analyze:
            meta = {
                "gameId": g["id"], "gameUrl": g["url"], "tournamentId": g["tournamentId"],
                "date": g["date"], "whiteUsername": g["white"]["username"], "blackUsername": g["black"]["username"],
            }
            pgn_text = pgn_by_id[g["id"]]
            try:
                found = analyze_game(engine, meta, pgn_text)
            except Exception as e:
                print(f"  ! error analyzing {g['id']}: {e}", file=sys.stderr)
                found = []
            if found:
                print(f"  + {g['id']}: {len(found)} brilliancy candidate(s)")
            new_brilliancies.extend(found)
            analyzed.add(g["id"])
    finally:
        engine.quit()

    all_brilliancies = existing.get("brilliancies", []) + new_brilliancies
    all_brilliancies.sort(key=lambda b: b.get("date") or "", reverse=True)

    out = {
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "analyzedGameIds": sorted(analyzed),
        "brilliancies": all_brilliancies,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=None)

    print(f"\nWrote {OUT_FILE}: {len(all_brilliancies)} total brilliancies "
          f"({len(new_brilliancies)} new), {len(analyzed)} games analyzed so far.")


if __name__ == "__main__":
    main()
