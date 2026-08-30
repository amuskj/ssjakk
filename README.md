# SSJakk Leaderboard

Static site: `index.html` reads `data.json` at load time. `refresh.py` regenerates
`data.json` from Chess.com's public API.

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

```
pip install requests   # once
python refresh.py
git add data.json
git commit -m "Refresh leaderboard data"
git push
```

The site picks up the new data.json automatically within a minute of the push
(no rebuild step — it's a static file the page fetches on load).

## Editing the roster

Open `refresh.py` and edit the `USERNAMES`, `USERNAME_TO_PERSON`, and
`DISPLAY_NAMES` dictionaries at the top — e.g. add a new member's username, or
merge in a newly-discovered alt account. Re-run the script afterward.

## Known limitations (v1)

- The "Sunday Standings" tab is a placeholder — it doesn't have weekly Arena
  results wired up yet. That's a separate piece (fetching each week's arena
  tournament directly needs that week's tournament URL, since Chess.com creates
  a new one each time rather than reusing a fixed link).
- Head-to-head counts every standard/variant game the two accounts have ever
  played against each other on Chess.com, across all time controls — not just
  games played during your Sunday club sessions.
