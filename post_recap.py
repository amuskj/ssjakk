#!/usr/bin/env python3
"""
Posts an automatic weekly recap to the club's Discord channel.

Reads sunday.json (backfill_sunday.py must run first) and, if there's a
new week since the last time this posted, sends a message with that
week's podium plus the auto-flagged storylines (biggest upset, biggest
rating gain, hottest streak, new season leader).

Needs a DISCORD_WEBHOOK_URL environment variable (set as a repo secret in
the GitHub Actions workflow -- see README's one-time setup). If it isn't
set, this just prints what it would have posted and exits quietly, so
local runs never error.

Idempotent: remembers the last week it posted about in .last_recap_week
(committed to the repo) so a scheduled run with nothing new never
double-posts.
"""

import json
import os
import sys

import requests

# GitHub Pages always works; swap to "https://ssjakk.no" once that domain
# is confirmed resolving (see README's DNS section).
SITE_URL = "https://amuskj.github.io/ssjakk/"
STATE_FILE = ".last_recap_week"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return f.read().strip()
    return None


def save_state(week_id):
    with open(STATE_FILE, "w") as f:
        f.write(week_id + "\n")


def rank_icon(i):
    return ["\U0001F947", "\U0001F948", "\U0001F949"][i] if i < 3 else f"#{i + 1}"


def build_message(sunday):
    storylines = sunday.get("storylines")
    weeks = sunday.get("weeks", [])
    if not storylines or not weeks:
        return None

    latest = weeks[-1]
    lines = [f"**Results are in for {latest.get('seriesLabel') or 'this week'}** · {latest.get('date')}", ""]

    lines.append("**This week's podium**")
    for i, s in enumerate(latest["standings"][:3]):
        lines.append(f"{rank_icon(i)} {s['displayName']} — {s['points']} pts")
    lines.append("")

    headlines = []
    upset = storylines.get("upset")
    if upset:
        headlines.append(
            f"\U0001F525 **Upset of the week:** {upset['winnerDisplayName']} ({upset['winnerRating']}) beat "
            f"{upset['loserDisplayName']} ({upset['loserRating']}) — a {upset['gap']}-point upset."
        )
    gain = storylines.get("ratingGain")
    if gain:
        headlines.append(
            f"\U0001F4C8 **Biggest rating gain:** {gain['displayName']} climbed from {gain['fromRating']} "
            f"to {gain['toRating']} (+{gain['gain']})."
        )
    streak = storylines.get("streak")
    if streak and streak["length"] >= 2:
        headlines.append(f"\U0001F3AF **On fire:** {streak['displayName']} is riding a {streak['length']}-game win streak.")
    new_leader = storylines.get("newLeader")
    if new_leader:
        headlines.append(
            f"\U0001F451 **New leader!** {new_leader['displayName']} has taken over the top spot from "
            f"{new_leader['previousDisplayName']} in the cumulative Sunday Standings."
        )
    if headlines:
        lines.append("**Storylines**")
        lines.extend(headlines)
        lines.append("")

    cumulative = sunday.get("cumulative", [])
    if cumulative:
        leader = cumulative[0]
        lines.append(f"Season lead: **{leader['displayName']}** ({leader['firsts']} wins, {leader['podiums']} podiums)")

    lines.append("")
    lines.append(f"Full standings: {SITE_URL}")
    return "\n".join(lines)


def main():
    with open("sunday.json") as f:
        sunday = json.load(f)

    storylines = sunday.get("storylines")
    if not storylines:
        print("No storylines yet (not enough data) -- nothing to post.")
        return

    week_id = storylines["week"]
    if load_state() == week_id:
        print(f"Already posted about {week_id} -- nothing new.")
        return

    message = build_message(sunday)
    if not message:
        print("Nothing to post.")
        return

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL not set -- would have posted:\n")
        print(message)
        return

    r = requests.post(webhook, json={"content": message}, timeout=20)
    if r.status_code >= 300:
        print(f"! Discord webhook returned HTTP {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)

    save_state(week_id)
    print(f"Posted recap for {week_id}.")


if __name__ == "__main__":
    main()
