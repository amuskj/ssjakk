#!/usr/bin/env python3
"""
SSJakk Stockfish analysis.

Runs Stockfish over every ply of every Sunday arena game, once, and gets
two things out of that single pass:

  - Brilliancies: genuine sacrifices that still hold up under review, in a
    position that wasn't already trivially winning. Writes brilliancies.json,
    which index.html's "Brilliant Moves" section turns into click-to-solve
    puzzles.
  - Full-game accuracy: average centipawn loss, a move-quality breakdown
    (best/good/inaccuracy/mistake/blunder) per side, and the eval curve for
    the whole game (used for the swing chart in the match log). Writes
    game_analysis.json.

Centipawn loss per move is the standard, engine-agnostic way analysis tools
measure move quality: how much worse the position got for the mover than
engine review says it should have, comparing the position's eval right
before the move to right after it (both from the mover's own point of
view), floored at zero. It is not chess.com's own (proprietary, win%-based)
accuracy metric -- this is the older, simpler measure most open chess
tools use, and it is what the numbers on this site mean.

Each ply needs exactly one fresh Stockfish call: the position right after
a move is the exact same position as right before the next one, just with
the other side to move, so that single evaluation (sign-flipped) does
double duty as both "after" for this ply and "before" for the next. The
original version of this script called Stockfish twice per ply without
noticing the two calls were evaluating the same position from opposite
sides -- fixing that roughly doubled how much game we can afford to
analyze per second of engine time, which is what made full-game (not just
post-opening) analysis affordable.

A "sacrifice" candidate must actually stay a sacrifice, not just look like
one for a single move. The original brilliancy detector only checked
whether one move gave up more value than it captured on a square the
opponent attacks -- but that's also true of the *first half* of a
completely ordinary trade (e.g. bishop takes pawn, knight takes bishop,
knight retakes knight -- textbook opening theory, not a sacrifice). That
bug flagged 192 "brilliancies" across the club's games, of which 186 were
recaptured back to even by the mover's very next move and only 2 held up
under scrutiny. The fix: after a candidate passes the existing eval-based
checks, replay the game's own following moves and require the material
deficit to actually persist for a real stretch of play (SAC_LOOKAHEAD_PLIES),
not evaporate the moment the natural recapture happens.

Incremental by design: games already analyzed (tracked by id, right in
brilliancies.json) are skipped on every later run, so the GitHub Actions
workflow can call this after every refresh without redoing work -- only
brand-new games get analyzed.

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
ANALYSIS_OUT_FILE = "game_analysis.json"

PLY_TIME_LIMIT = 0.25       # seconds per position -- the main runtime lever
SKIP_FIRST_PLIES = 10       # brilliancies don't happen in opening theory
SWING_TOLERANCE = 40        # cp: how close to "assumed best play" counts as objectively strong
MAX_EVAL_BEFORE = 500       # cp: skip already-crushing positions (not a turning point)
MIN_EVAL_AFTER = -100       # cp: the sac must still hold up, not just fail
MIN_MATERIAL_RISKED = 2     # at least a minor piece -- no pawn pokes
SAC_LOOKAHEAD_PLIES = 16    # how far into the ACTUAL game to check the material stays down
SAC_RECOVERY_MARGIN = 1     # points: within this of even, within the window above, means "just a trade"

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

# Centipawn-loss-per-move thresholds for the move-quality breakdown. A
# single move's loss is capped before averaging so one blundered-into-mate
# doesn't blow out a whole game's average.
CPL_CAP = 1000
CPL_BUCKETS = [(10, "best"), (50, "good"), (100, "inaccuracy"), (300, "mistake")]


def classify_loss(loss):
    for threshold, label in CPL_BUCKETS:
        if loss < threshold:
            return label
    return "blunder"


def material_diff(board, color):
    """Total piece value for `color` minus the opponent's, in pawns. Used
    only to check whether a candidate sacrifice's material actually stays
    given up -- not related to the engine's own positional evaluation."""
    diff = 0
    for piece_type, value in PIECE_VALUES.items():
        diff += value * len(board.pieces(piece_type, color))
        diff -= value * len(board.pieces(piece_type, not color))
    return diff


def material_recovers(board_after_move, moves, idx, mover_color, diff_before):
    """True if the material given up on this move comes back to roughly
    even within the game's own next several moves -- the signature of an
    ordinary trade (give a piece, get one back) rather than a genuine,
    lasting sacrifice. `board_after_move` already has `moves[idx]` applied;
    it's copied here so the caller's board keeps streaming forward untouched."""
    lookahead = board_after_move.copy()
    for j in range(idx + 1, min(idx + 1 + SAC_LOOKAHEAD_PLIES, len(moves))):
        lookahead.push(moves[j])
        if material_diff(lookahead, mover_color) >= diff_before - SAC_RECOVERY_MARGIN:
            return True
    return False


def person_for(username):
    return USERNAME_TO_PERSON.get(username.lower(), username.lower())


def find_engine():
    path = shutil.which("stockfish")
    if not path:
        print("! stockfish not found on PATH -- skipping analysis this run.", file=sys.stderr)
        return None
    return path


def analyze_game(engine, game_meta, pgn_text):
    """Returns (brilliancies, analysis) for one game: the brilliancy
    candidates found (a list, same shape as before), and a full accuracy
    breakdown for both sides (None if the PGN didn't parse)."""
    found = []
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return found, None

    board = game.board()
    moves = list(game.mainline_moves())  # materialized once, so a candidate
                                          # sacrifice can look ahead at what
                                          # actually happened next in the game
    ply = 0
    sides = {
        chess.WHITE: {"losses": [], "best": 0, "good": 0, "inaccuracy": 0, "mistake": 0, "blunder": 0},
        chess.BLACK: {"losses": [], "best": 0, "good": 0, "inaccuracy": 0, "mistake": 0, "blunder": 0},
    }
    eval_curve = []  # eval after each ply, from White's POV -- the swing chart
    cp_before = None  # position eval, from the mover-to-move's POV; reused from the previous ply's result

    for idx, move in enumerate(moves):
        ply += 1
        mover_color = board.turn

        if cp_before is None:
            # Only needed once, for the very first ply of the game -- every
            # ply after this reuses the previous ply's post-move eval.
            info = engine.analyse(board, chess.engine.Limit(time=PLY_TIME_LIMIT))
            cp_before = info["score"].pov(mover_color).score(mate_score=10000)

        fen_before = board.fen()
        moved_piece = board.piece_at(move.from_square)
        captured_piece = board.piece_at(move.to_square)
        san = board.san(move)
        diff_before = material_diff(board, mover_color)  # material balance BEFORE this move
        board.push(move)

        info_after = engine.analyse(board, chess.engine.Limit(time=PLY_TIME_LIMIT))
        # From here, board.turn is the side to move NEXT -- this is exactly
        # the "before" eval that next ply needs, so it gets reused as-is.
        cp_after_next_pov = info_after["score"].pov(board.turn).score(mate_score=10000)
        cp_after_mover = -cp_after_next_pov

        loss = max(0, min(CPL_CAP, cp_before - cp_after_mover))
        bucket = sides[mover_color]
        bucket["losses"].append(loss)
        bucket[classify_loss(loss)] += 1
        eval_curve.append(cp_after_mover if mover_color == chess.WHITE else -cp_after_mover)

        if ply > SKIP_FIRST_PLIES:
            is_attacked = board.is_attacked_by(not mover_color, move.to_square)
            risked = PIECE_VALUES.get(moved_piece.piece_type, 0) - (
                PIECE_VALUES.get(captured_piece.piece_type, 0) if captured_piece else 0)
            is_sac = is_attacked and moved_piece.piece_type != chess.PAWN and risked >= MIN_MATERIAL_RISKED

            if (is_sac
                    and cp_after_mover >= cp_before - SWING_TOLERANCE
                    and abs(cp_before) < MAX_EVAL_BEFORE
                    and cp_after_mover > MIN_EVAL_AFTER
                    and not material_recovers(board, moves, idx, mover_color, diff_before)):
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

        cp_before = cp_after_next_pov

    def summarize(color):
        b = sides[color]
        n = len(b["losses"])
        return {
            "moves": n,
            "avgCpLoss": round(sum(b["losses"]) / n, 1) if n else None,
            "best": b["best"], "good": b["good"], "inaccuracy": b["inaccuracy"],
            "mistake": b["mistake"], "blunder": b["blunder"],
        }

    analysis = None
    if eval_curve:
        analysis = {
            "white": summarize(chess.WHITE),
            "black": summarize(chess.BLACK),
            "evalCurve": eval_curve,
        }
    return found, analysis


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
    if os.path.exists(ANALYSIS_OUT_FILE):
        with open(ANALYSIS_OUT_FILE) as f:
            existing_analysis = json.load(f)
    else:
        existing_analysis = {"analyzedGameIds": [], "games": {}}

    # brilliancies.json is the checkpoint of record for "already analyzed" --
    # both files are written together every run, so they stay in lockstep.
    analyzed = set(existing.get("analyzedGameIds", []))
    to_analyze = [g for g in games_data.get("games", []) if g["id"] not in analyzed and g["id"] in pgn_by_id]

    if not to_analyze:
        print("No new games to analyze.")
        return

    engine_path = find_engine()
    if not engine_path:
        return

    print(f"Analyzing {len(to_analyze)} new game(s) "
          f"(skipping {len(analyzed)} already done)...")
    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    new_brilliancies = []
    new_analysis = {}
    try:
        for g in to_analyze:
            meta = {
                "gameId": g["id"], "gameUrl": g["url"], "tournamentId": g["tournamentId"],
                "date": g["date"], "whiteUsername": g["white"]["username"], "blackUsername": g["black"]["username"],
            }
            pgn_text = pgn_by_id[g["id"]]
            try:
                found, analysis = analyze_game(engine, meta, pgn_text)
            except Exception as e:
                print(f"  ! error analyzing {g['id']}: {e}", file=sys.stderr)
                found, analysis = [], None
            if found:
                print(f"  + {g['id']}: {len(found)} brilliancy candidate(s)")
            new_brilliancies.extend(found)
            if analysis:
                new_analysis[g["id"]] = analysis
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

    all_analysis = {**existing_analysis.get("games", {}), **new_analysis}
    analysis_out = {
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "analyzedGameIds": sorted(analyzed),
        "games": all_analysis,
    }
    with open(ANALYSIS_OUT_FILE, "w") as f:
        json.dump(analysis_out, f, indent=None)

    print(f"Wrote {ANALYSIS_OUT_FILE}: {len(all_analysis)} games with full move-accuracy data "
          f"({len(new_analysis)} new).")


if __name__ == "__main__":
    main()
