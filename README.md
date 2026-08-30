# SSJakk Leaderboard

Static site: `index.html` reads `data.json` (Rivalry tab) and `sunday.json`
(Sunday Standings tab) at load time.

- `refresh.py` regenerates `data.json` — lifetime head-to-head across every
  game club members have played each other on Chess.com.
- `backfill_sunday.py` regenerates `sunday.json` — results from the weekly
  "Hopen Arena" tournaments, plus an arena-only head-to-head graph.
- `config.py` holds the shared roster mapping both scripts import from.

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
python refresh.py            # lifetime rivalry data -> data.json
python backfill_sunday.py    # Sunday arena results -> sunday.json
git add data.json sunday.json
git commit -m "Refresh leaderboard data"
git push
```

Before running `backfill_sunday.py`, open it and add that week's tournament
URL (or just the id, e.g. `hopen-31068160`) to the `TOURNAMENT_IDS` list near
the top — Chess.com creates a new tournament link every week, so this list is
the one thing that needs a manual touch each time. Find the link from the
club's page on Chess.com (`chess.com/club/ssjakk`, logged in) under its past
events.

The site picks up new data automatically within a minute of the push
(no rebuild step — these are static files the page fetches on load).

## Editing the roster

Edit `config.py` — `USERNAMES`, `USERNAME_TO_PERSON`, and `DISPLAY_NAMES` — to
add a new member's username or merge in a newly-discovered alt account. Both
`refresh.py` and `backfill_sunday.py` import from here, so it only needs
updating in one place. Re-run both scripts afterward.

## Known limitations (v1)

- Head-to-head on the Rivalry tab counts every standard/variant game the two
  accounts have ever played against each other on Chess.com, across all time
  controls — not just games played during Sunday club sessions. The Sunday
  Standings tab's graph is scoped to just the Sunday arenas.
- "Biggest upset" is the largest rating gap in a decisive (non-drawn) arena
  game where the lower-rated player won — it isn't an engine-based brilliancy
  detector. Real move-quality analysis (Stockfish over each game's PGN) is a
  future addition, not yet built.
