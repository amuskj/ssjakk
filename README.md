# SSJakk Leaderboard

Static site: `index.html` reads `data.json` (Rivalry tab), `sunday.json`
(Sunday Standings tab), `games.json`, and `ratings.json` (Trends tab) at
load time.

- `refresh.py` regenerates `data.json` — lifetime head-to-head across every
  game club members have played each other on Chess.com — and
  `ratings.json` — each member's own blitz rating over time (one point per
  day they played, across all opponents, not just club games).
- `backfill_sunday.py` regenerates `sunday.json` — results from the weekly
  "Hopen Arena" tournaments (cumulative podium/leaderboard), any one-off
  special events (their own section, see below), an arena-only head-to-head
  graph spanning both, each player's last-5-results "form", and this
  week's auto-flagged `storylines` (biggest upset, biggest rating gain,
  hottest streak, new season leader — also what `post_recap.py` posts to
  Discord). Each week/event also carries its Chess.com time control, time
  class, and total scheduled duration (`timeControl`, `timeClass`,
  `durationSec` — from the tournament's own `start_time`/`finish_time`),
  shown on its card on the site.
- `build_games.py` regenerates `games.json` — every individual game from
  every tournament, regular or special (ratings, clock times, opening, move
  count, and accuracy where it exists), which powers the Trends tab: the
  arena rating chart, the full match log, the sweaty-game leaderboard, the
  opening breakdown, and the club-record lists.
- `config.py` holds the shared roster, the tournament list, and the
  "nemesis" calculation that all four scripts import from.
- `add_tournament.py` registers a new tournament (see "Adding a new week's
  tournament" below) without hand-editing `config.py`.
- `post_recap.py` posts a Discord message with the latest week's podium and
  storylines (see "Automatic Discord recap" below).
- `.github/workflows/refresh.yml` runs all of the above on a schedule (and
  on demand) so the site updates itself with nobody touching a laptop — see
  "Automated refresh" below.

### Tournament series (regular weeks vs. one-off events)

`config.py`'s `TOURNAMENTS` list tags every tournament with a `series` —
`"hopen"` for the regular weekly arena, or a short slug of its own for a
one-off (a memorial arena, a holiday tournament, etc). `SERIES` in the same
file says whether a series counts toward the cumulative Sunday Standings
podium (`cumulative: True`, the default for "hopen") or gets its own
"special event" card instead (`cumulative: False`) — a compact podium and
full standings, kept separate so a single guest-heavy one-off can't skew
the regular season. Either way, its games still count everywhere else: the
arena-only head-to-head graph, the Rivalry tab (which is lifetime and
doesn't care about this list at all), and every chart on the Trends tab.

To add a future one-off: give it a new `series` slug in `TOURNAMENTS`, add
a matching entry to `SERIES` with `"cumulative": False` and a display
label, and re-run `backfill_sunday.py` / `build_games.py` — no other code
changes needed.

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

## Automated refresh (GitHub Actions) -- do this once

A GitHub Actions workflow (`.github/workflows/refresh.yml`) now runs the
whole pipeline with nobody touching a laptop:

- **Daily**, so every player's current blitz/rapid/bullet rating and
  lifetime rating history stay fresh even on a quiet week.
- **Every 15 minutes through a wide Sunday window** (08:00-23:45 UTC), so
  this week's arena results -- and the Discord recap -- show up soon after
  the session ends.
- **On demand**, from the repo's Actions tab (works great from a phone) --
  see "Adding a new week's tournament" below.

One-time setup:

1. Repo **Settings -> Actions -> General -> Workflow permissions** ->
   select "Read and write permissions" -> Save. (Without this, the
   workflow can't push its own commits.)
2. That's it for the refresh itself -- ratings, standings, and everything
   else on the site now update themselves forever.

### Adding a new week's tournament

Chess.com has no public, login-free way to list a private club's
tournaments, and a member's own tournament history doesn't include club
arena events either (both checked and ruled out) -- so noticing a
*brand-new* week's tournament still needs a person. This is the one
remaining manual step, and it's now a single action instead of a code
edit:

1. Grab the new tournament's link from Chess.com (same as always --
   `chess.com/club/ssjakk`, logged in, under Past Events).
2. On GitHub: repo's **Actions** tab -> "Refresh SSJakk leaderboard" in the
   left sidebar -> **Run workflow** -> paste the link into `tournament_url`
   -> Run workflow. (This works fine from GitHub's mobile app.)

That single tap registers the tournament *and* runs the full refresh (data
+ Discord recap) right away -- no waiting for the next scheduled tick. A
one-off special event (a memorial arena, a holiday tournament) works the
same way, just set the `series` input to a slug already listed in
`config.py`'s `SERIES` dict (or add a new one there first, same as always).

Leaving `tournament_url` blank and running the workflow just triggers an
ordinary refresh on demand -- handy right after a session if you don't
want to wait for the 15-minute cron tick.

### Automatic Discord recap

After every refresh that finds a new week, `post_recap.py` posts the
podium and that week's auto-flagged storylines (biggest upset, biggest
rating gain, hottest streak, new season leader) to a Discord channel. To
turn it on:

1. In Discord: the target channel's settings -> Integrations -> Webhooks
   -> New Webhook -> copy its URL.
2. On GitHub: repo **Settings -> Secrets and variables -> Actions -> New
   repository secret** -> name it `DISCORD_WEBHOOK_URL`, paste the webhook
   URL, save.

Without that secret set, the workflow just prints what it would have
posted and skips silently -- nothing breaks.

### Brilliant Moves puzzles

Every refresh also runs `find_brilliancies.py`, which points Stockfish at
every Sunday game looking for real brilliancies -- not just decisive
moments, but a genuine sacrifice (real material given up) that still
holds up under engine review, in a position that wasn't already
trivially winning. Whatever it finds goes into `brilliancies.json`, and
the Trends tab turns each one into a click-to-solve puzzle: pick the
mover's piece, then the square, same as a Lichess/chess.com puzzle
(there's a "Show the move" button if you get stuck). Everything runs
server-side during the GitHub Actions job -- the page itself never runs
an engine, it just replays a saved position.

It's incremental: a game already analyzed is tracked by id in
`brilliancies.json` and skipped on every later run, so only brand-new
games get analyzed each time. The very first run analyzes the whole
Hopen Arena history (roughly a minute of Stockfish time per game, so
budget up to an hour the first time this runs -- after that, only
that week's handful of new games need analyzing, so it's quick).
Needs `stockfish` on the runner (the workflow installs it via
`apt-get`) -- nothing to set up by hand.

### Installing the site as an app

`manifest.json` + a small service worker (`sw.js`) make the site
installable: open it on a phone and use the browser's "Add to Home
Screen" (iOS Safari) or the install prompt (Android Chrome) to get an app
icon that opens straight to the leaderboard. Only the app shell is cached
for offline use -- the JSON data files always come from the network, so
the numbers you see are never stale on purpose.

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

## Weekly refresh (manual / local -- optional now)

GitHub Actions handles this automatically now (see "Automated refresh"
above); this section is for running things by hand locally instead, if
you ever want to (debugging, or before Actions was set up):

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
tournament to the `TOURNAMENTS` list in `config.py` — `{"id": "hopen-31068160",
"series": "hopen"}` for a regular week, or a new `series` slug (plus an
entry in `SERIES`) for a one-off event — see "Tournament series" above.
Chess.com creates a new tournament link every week, so this list is the one
thing that needs a manual touch each time, and both scripts read the same
list. Find the link from the club's page on Chess.com
(`chess.com/club/ssjakk`, logged in) under its past events.

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
- The Trends tab's "Biggest upsets" list ranks decisive (non-drawn) games by
  rating gap where the lower-rated player won — it isn't an engine-based
  brilliancy detector. Real move-quality analysis (Stockfish over each
  game's PGN) is a future addition, not yet built.
- Accuracy is opportunistic (see above) — most games won't have it yet.
- The Trends tab has two rating charts. "Arena Rating" plots each player's
  live rating as sampled at every Hopen Arena game, so it also reflects
  anything they play outside the club between sessions. "Lifetime Rating"
  plots one point per calendar day from their entire blitz history (any
  opponent, not just club games or club sessions) — currently blitz only.
