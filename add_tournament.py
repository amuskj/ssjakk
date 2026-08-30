#!/usr/bin/env python3
"""
Add one new tournament to the site without touching config.py by hand.

Chess.com doesn't expose any public, credential-free way to list a
private club's tournaments, or to find them in a member's own tournament
history (both checked and ruled out) -- so there's no way to fully
automate noticing a *brand-new* week's tournament. This script is the
next best thing: it turns "add a new week" into a single command (or a
single GitHub Actions "Run workflow" button tap with the link pasted into
the tournament_url input), instead of hand-editing config.py, committing,
and pushing from your own machine.

    python add_tournament.py --url https://www.chess.com/tournament/live/arena/hopen-31234567
    python add_tournament.py --url hopen-31234567 --series hopen           # regular week (default)
    python add_tournament.py --url some-memorial-arena-31234567 --series bjorn-jens-memorial

Appends to discovered_tournaments.json, which config.py merges into
TOURNAMENTS automatically -- refresh.py / backfill_sunday.py /
build_games.py all pick it up with no other changes. A brand-new *series*
(a new kind of one-off event) still needs an entry in config.py's SERIES
dict by hand, same as always -- this script only appends the tournament id.
"""

import argparse
import json
import os

from config import TOURNAMENTS, extract_id

DISCOVERED_FILE = "discovered_tournaments.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Tournament URL or bare id")
    ap.add_argument("--series", default="hopen", help='Series slug (default: "hopen")')
    args = ap.parse_args()

    tid = extract_id(args.url)
    known_ids = {extract_id(t["id"]) for t in TOURNAMENTS}

    if os.path.exists(DISCOVERED_FILE):
        with open(DISCOVERED_FILE) as f:
            discovered = json.load(f)
    else:
        discovered = []
    known_ids |= {extract_id(t["id"]) for t in discovered}

    if tid in known_ids:
        print(f"{tid} is already known -- nothing to do.")
        return

    discovered.append({"id": tid, "series": args.series})
    with open(DISCOVERED_FILE, "w") as f:
        json.dump(discovered, f, indent=2)
        f.write("\n")
    print(f"Added {tid} (series: {args.series}) to {DISCOVERED_FILE}.")


if __name__ == "__main__":
    main()
