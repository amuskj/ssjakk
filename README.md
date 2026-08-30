# SSJakk Leaderboard

Static site: `index.html` reads `data.json` (Rivalry tab), `sunday.json`
(Sunday Standings tab), `games.json`, and `ratings.json` (Trends tab) at
load time.

- `refresh.py` regenerates `data.json` — lifetime head-to-head across every
  game club members have played each other on Chess.com — and
  `ratings.json` — each member's own blitz rating over time (one point per
  day they played, across all opponents, not just club games).
- `backfill_sunday.py` regenerates `sunday.json` — results from the weekly
  "Hopen Arena" tournaments, plus an arena-only head-to-head graph.
- `build_games.py` regenerates `games.json` — every individual game from
  every arena (ratings, clock times, opening, move count, and accuracy where
  it exists), which powers the Trends tab: the arena rating chart, the full
  match log, the sweaty-game leaderboard, the opening breakdown, and the
  club-record lists.
- `config.py` holds the shared roster, the tournament list, and the
  "nemesis" calculation that all three scripts import from.

### What "Nemesis" means here

Nemesis isn't "the person who beats you the most" — it's the opponent whose
head-to-head record against you sits closest to an even 50/50 split (with a
minimum-game-count floor so a 1-0 fluke doesn't count). It's the rival you
can never quite shake either way. "Favorite matchup" (Rivalry tab only) is
the opposite: the opponent you have the best record against.

### A note on accuracy

Chess.com only computes a game's accuracy score when someone actually runs
"Game Review" on it — it isn't automatic for most accounts. `build_games.py`
checks for it opportunistically, so most games will show no accuracy at all,
and that's expected, not a bug. It'll fill in gradually as more games get
reviewed.

## One-time setup (GitHub Pages + ssjakk.no)

1. Create a new **public** repo on GitHub, e.g. `ssjakk-leaderboard`.
2. From this folder:
   ```
   git init
   git add .
   git commit -m "Initial leaderboard site"
   git branch -M main
   git remote add origin https://github.com/<your-username>/ssjakk-leaderboard.git
   git push -u origin main
   ```
3. On GitHub: repo **Settings → Pages** → Source: "Deploy from a branch" →
   Branch: `main`, folder `/ (root)` → Save.
4. Still in **Settings → Pages**, under "Custom domain" enter `ssjakk.no` and save.
   GitHub will add/confirm the `CNAME` file (already included here) and show you
   the DNS records to add.
5. At your domain registrar (wherever you bought ssjakk.no), add the DNS records
   GitHub showed you — normally four `A` records pointing the apex domain at
   GitHub's IPs, or a single `ANAME`/`ALIAS` record if your registrar supports one.
   DNS can take anywhere from a few minutes to a few hours to propagate.
6. Back in Settings → Pages, tick **Enforce HTTPS** once the certificate is ready
   (GitHub provisions it automatically after DNS resolves).

Once that's done, `https://ssjakk.no` serves this site directly, and stays live
with zero further setup.

## Weekly refresh

After each Sunday session:

```
pip install requests   # once
python refresh.py            # lifetime rivalry + rating history -> data.json, ratings.json
python backfill_sunday.py    # Sunday arena results -> sunday.json
python build_games.py        # full per-game log -> games.json
git add data.json ratings.json sunday.json games.json
git commit -m "Refresh leaderboard data"
git push
```

Before running `backfill_sunday.py` or `build_games.py`, add that week's
tournament URL (or just the id, e.g. `hopen-31068160`) to the
`TOURNAMENT_IDS` list in `config.py` — Chess.com creates a new tournament
link every week, so this list is the one thing that needs a manual touch
each time, and both scripts read the same list. Find the link from the
club's page on Chess.com (`chess.com/club/ssjakk`, logged in) under its past
events.

The site picks up new data automatically within a minute of the push
(no rebuild step — these are static files the page fetches on load).

## Editing the roster

Edit `config.py` — `USERNAMES`, `USERNAME_TO_PERSON`, and `DISPLAY_NAMES` — to
add a new member's username or merge in a newly-discovered alt account. All
three scripts import from here, so it only needs updating in one place.
Re-run all three afterward.

## Known limitations (v1)

- Head-to-head on the Rivalry tab counts every standard/variant game the two
  accounts have ever played against each other on Chess.com, across all time
  controls — not just games played during Sunday club sessions. The Sunday
  Standings tab's graph and the Trends tab are both scoped to just the
  Sunday arenas.
- "Biggest upset" is the largest rating gap in a decisive (non-drawn) arena
  game where the lower-rated player won — it isn't an engine-based brilliancy
  detector. Real move-quality analysis (Stockfish over each game's PGN) is a
  future addition, not yet built.
- Accuracy is opportunistic (see above) — most games won't have it yet.
- The Trends tab has two rating charts. "Arena Rating" plots each player's
  live rating as sampled at every Hopen Arena game, so it also reflects
  anything they play outside the club between sessions. "Lifetime Rating"
  plots one point per calendar day from their entire blitz history (any
  opponent, not just club games or club sessions) — currently blitz only.
