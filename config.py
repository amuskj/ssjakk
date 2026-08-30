"""
Shared roster configuration for SSJakk leaderboard scripts (refresh.py, backfill_sunday.py).

Edit this file when the club roster changes - both scripts import from here so the
mapping only needs to be updated in one place.
"""

# Every Chess.com username currently in the club (case-insensitive).
USERNAMES = [
    "deluludvig",
    "efdalen",
    "IdaMuren",
    "Lateks12",
    "martinaces",
    "noodle_addict1987",
    "parasosialist",
    "rookvg",
    "Shortking1996",
    "Skjellstad",
    "stinemartolini",
]

# Map each username to a person id. Give two usernames the same person id
# if they're alt accounts of the same human (games between a person's own
# alt accounts are dropped, not counted as a "rivalry").
USERNAME_TO_PERSON = {
    "deluludvig": "deluludvig",
    "efdalen": "efdalen",
    "idamuren": "idamuren",
    "lateks12": "lateks12",
    "martinaces": "martin",
    "shortking1996": "martin",
    "noodle_addict1987": "noodle_addict1987",
    "parasosialist": "parasosialist",
    "rookvg": "rookvg",
    "skjellstad": "skjellstad",
    "stinemartolini": "stinemartolini",
}

# What to show on the dashboard for each person id (first names, per club preference).
DISPLAY_NAMES = {
    "deluludvig": "Ludvig",
    "efdalen": "Erik",
    "idamuren": "Ida",
    "lateks12": "Michael",
    "martin": "Martin",
    "noodle_addict1987": "Didrik",
    "parasosialist": "Mathias",
    "rookvg": "Isak",
    "skjellstad": "Amund",
    "stinemartolini": "Stine",
}

# Which account's Chess.com profile picture to show for a merged person.
# (Only needed for person ids with more than one account.)
AVATAR_ACCOUNT_OVERRIDE = {
    "martin": "martinaces",
}

HEADERS = {"User-Agent": "SSJakk-Leaderboard/1.0 (contact: a.skjellstad@gmail.com)"}
