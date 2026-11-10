"""Fetch games from the public chess.com API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from version import VERSION

API_BASE = "https://api.chess.com/pub/player"
# chess.com requires an identifying User-Agent. Personal contact details are deliberately omitted.
USER_AGENT = f"check-mate/{VERSION} (personal game analysis app; chess.com user: first_div)"
TIMEOUT_S = 15
MAX_ARCHIVES = 3  # the latest month and up to two months before it
# chess.com timestamps are UTC; show them in the player's local time
LOCAL_TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Jerusalem"))

DRAW_RESULTS = {
    "agreed", "repetition", "stalemate", "insufficient",
    "50move", "timevsinsufficient",
}

RESULT_DETAIL = {
    "checkmated": "checkmate",
    "timeout": "timeout",
    "resigned": "resignation",
    "abandoned": "abandoned",
    "agreed": "agreement",
    "repetition": "repetition",
    "stalemate": "stalemate",
    "insufficient": "insufficient material",
    "50move": "50-move rule",
    "timevsinsufficient": "timeout vs insufficient material",
}

TIME_CLASS_LABEL = {
    "bullet": "Bullet",
    "blitz": "Blitz",
    "rapid": "Rapid",
    "daily": "Daily",
}


@dataclass(frozen=True)
class GameMeta:
    url: str
    pgn: str
    end_time: int
    time_class: str
    time_control: str
    my_color: str  # "white" / "black"
    opponent: str
    opponent_rating: int | None
    my_rating: int | None
    outcome: str  # "win" / "loss" / "draw"
    result_code: str  # raw chess.com code explaining how the game ended (e.g. "checkmated")

    @property
    def end_dt(self) -> datetime:
        """End time in local time (LOCAL_TZ)."""
        return datetime.fromtimestamp(self.end_time, tz=timezone.utc).astimezone(LOCAL_TZ)

    @property
    def format_label(self) -> str:
        cls = TIME_CLASS_LABEL.get(self.time_class, self.time_class)
        return f"{cls} {format_time_control(self.time_control)}".strip()

    @property
    def outcome_label(self) -> str:
        base = {"win": "Win", "loss": "Loss", "draw": "Draw"}[self.outcome]
        detail = RESULT_DETAIL.get(self.result_code, "")
        return f"{base} ({detail})" if detail else base

    @property
    def outcome_icon(self) -> str:
        return {"win": "🟢", "loss": "🔴", "draw": "⚪"}[self.outcome]


def format_time_control(tc: str) -> str:
    """'600' -> '10+0', '180+2' -> '3+2', '1/86400' -> '1 day/move'."""
    if not tc:
        return ""
    if "/" in tc:
        days = int(tc.split("/")[1]) // 86400
        return f"{days} day/move" if days == 1 else f"{days} days/move"
    base, _, inc = tc.partition("+")
    try:
        minutes = int(base) / 60
    except ValueError:
        return tc
    return f"{minutes:g}+{inc or '0'}"


def _outcome(result_code: str) -> str:
    if result_code == "win":
        return "win"
    if result_code in DRAW_RESULTS:
        return "draw"
    return "loss"


def parse_game(raw: dict, username: str) -> GameMeta | None:
    """Convert a raw API game into GameMeta. Returns None for games we don't analyze."""
    if raw.get("rules") != "chess" or not raw.get("pgn"):
        return None
    user = username.lower()
    white, black = raw["white"], raw["black"]
    if white["username"].lower() == user:
        me, opp, color = white, black, "white"
    elif black["username"].lower() == user:
        me, opp, color = black, white, "black"
    else:
        return None
    my_result = me.get("result", "")
    return GameMeta(
        url=raw.get("url", ""),
        pgn=raw["pgn"],
        end_time=int(raw.get("end_time", 0)),
        time_class=raw.get("time_class", ""),
        time_control=raw.get("time_control", ""),
        my_color=color,
        opponent=opp["username"],
        opponent_rating=opp.get("rating"),
        my_rating=me.get("rating"),
        outcome=_outcome(my_result),
        # On a win, the opponent's code says how it ended (resigned, timeout, ...)
        result_code=my_result if my_result != "win" else opp.get("result", "win"),
    )


def _get_json(url: str, session: requests.Session) -> dict:
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def fetch_recent_games(username: str, n: int = 10,
                       session: requests.Session | None = None) -> list[GameMeta]:
    """Return up to n most recent games, newest first. Falls back to earlier months only if needed."""
    session = session or requests.Session()
    user = username.strip().lower()
    archives = _get_json(f"{API_BASE}/{user}/games/archives", session).get("archives", [])
    games: list[GameMeta] = []
    for archive_url in reversed(archives[-MAX_ARCHIVES:]):
        for raw in _get_json(archive_url, session).get("games", []):
            meta = parse_game(raw, user)
            if meta:
                games.append(meta)
        if len(games) >= n:
            break
    games.sort(key=lambda g: g.end_time, reverse=True)
    return games[:n]
