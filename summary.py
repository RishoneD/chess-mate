"""Compact text of the critical moments, to paste into a chat with Claude."""

from __future__ import annotations

import chess

from chesscom import GameMeta
from classify import CATEGORY_LABEL, MoveReport, is_mistake

MAX_MOMENTS = 5
MAX_HIGHLIGHTS = 2


def fmt_eval(cp: int, mate: int | None = None) -> str:
    """Evaluation in pawns from White's view. Mate is shown as M3 / -M3 (and # when mate is on the board)."""
    if mate is not None:
        if mate == 0:
            return "#"
        return f"M{mate}" if mate > 0 else f"-M{abs(mate)}"
    return f"{cp / 100:+.1f}"


def critical_moments(reports: list[MoveReport], color: chess.Color,
                     limit: int = MAX_MOMENTS) -> list[MoveReport]:
    """The biggest mistakes of `color`, in game order."""
    mine = [r for r in reports if r.color == color and is_mistake(r.category)]
    top = sorted(mine, key=lambda r: r.loss, reverse=True)[:limit]
    return sorted(top, key=lambda r: r.ply)


def build_summary(meta: GameMeta, reports: list[MoveReport]) -> str:
    my_color = chess.WHITE if meta.my_color == "white" else chess.BLACK
    color_name = "White" if my_color == chess.WHITE else "Black"
    lines = [
        f"Chess game analysis (chess.com). I played {color_name}.",
        f"Opponent: {meta.opponent} ({meta.opponent_rating}) | Me: {meta.my_rating}",
        f"Format: {meta.format_label} | Result: {meta.outcome_label} | {meta.end_dt:%Y-%m-%d}",
        f"Link: {meta.url}",
        "Eval = Stockfish evaluation in pawns, from White's point of view.",
        "",
    ]
    moments = critical_moments(reports, my_color)
    if not moments:
        lines.append("No significant mistakes of mine in this game.")
    for i, r in enumerate(moments, 1):
        lines += [
            f"{i}) Move {r.move_label} – {CATEGORY_LABEL[r.category]}",
            f"FEN: {r.fen_before}",
            f"Played: {r.san} | Best: {r.best_san or '?'}",
            f"Eval: {fmt_eval(r.eval_before, r.mate_before)} -> {fmt_eval(r.eval_after, r.mate_after)}",
            f"Why: {r.explanation or ''}",
            "",
        ]
    great = [r for r in reports if r.color == my_color and r.category == "great"][:MAX_HIGHLIGHTS]
    if great:
        lines.append("Good moments (only moves I found):")
        for r in great:
            lines.append(f"- Move {r.full_label}: {r.explanation} | FEN: {r.fen_before}")
        lines.append("")
    lines.append("What idea did I miss at each moment, and what principle should I remember?")
    return "\n".join(lines).strip()
