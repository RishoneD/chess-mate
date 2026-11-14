"""Copy-summary text (Format v2), meant to be pasted into a chat with Claude.

The text is read by a model, not a person: the layout is fixed and line-oriented, every value
has a label, and all evaluations are from the user's point of view. Change FORMAT_VERSION when
the layout changes.
"""

from __future__ import annotations

import io

import chess
import chess.pgn

from chesscom import GameMeta
from classify import (CATEGORY_LABEL, WIN_THRESHOLDS, MoveReport, game_accuracy, is_mistake)
from moments import (clock_at, clocks_from_pgn, fmt_clock, game_phase, line_after_best,
                     line_after_played, opponent_misses, parse_time_control)

FORMAT_VERSION = 2
HEADER = f"Chess game analysis (chess.com) | Format: v{FORMAT_VERSION}"
MAX_MOMENTS = 8
MAX_HIGHLIGHTS = 2
NOT_DETECTED = "Not detected"
FINAL_INSTRUCTION = ("ענה בעברית. לכל רגע: צייר לוח עם חיצים (אדום ששיחקתי, ירוק הטוב ביותר), "
                     "הסבר מה פספסתי ומה העיקרון לזכור.")


def fmt_eval(cp: int, mate: int | None = None) -> str:
    """Evaluation in pawns from the point of view cp/mate are given in.
    Mate: M3 = mate in 3 for that side, -M3 = that side gets mated, #+ / #- = mate on the board."""
    if mate is not None:
        if mate == 0:
            return "#+" if cp > 0 else "#-"
        return f"M{mate}" if mate > 0 else f"-M{abs(mate)}"
    return f"{cp / 100:+.1f}"


def fmt_eval_pov(cp: int, mate: int | None, color: chess.Color) -> str:
    """fmt_eval of a White-view evaluation, turned to `color`'s point of view."""
    sign = 1 if color == chess.WHITE else -1
    return fmt_eval(cp * sign, None if mate is None else mate * sign)


def critical_moments(reports: list[MoveReport], color: chess.Color,
                     limit: int = MAX_MOMENTS) -> list[MoveReport]:
    """The biggest mistakes of `color`, most severe first (by win% drop, then game order)."""
    mine = [r for r in reports if r.color == color and is_mistake(r.category)]
    return sorted(mine, key=lambda r: (-r.win_drop, r.ply))[:limit]


def _movetext(pgn: str) -> str:
    """The game's moves in SAN, without headers, clocks or comments."""
    game = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
    if game is None:
        return "(not available)"
    moves = list(game.mainline_moves())
    if not moves:
        return "(no moves)"
    return game.board().variation_san(moves)


def _win_line(r: MoveReport, my_color: chess.Color) -> str:
    """Eval and win% before and after r's move, from my point of view."""
    before = fmt_eval_pov(r.eval_before, r.mate_before, my_color)
    after = fmt_eval_pov(r.eval_after, r.mate_after, my_color)
    wb, wa = (r.win_before, r.win_after) if r.color == my_color else (100 - r.win_before, 100 - r.win_after)
    return f"Eval (me): {before} -> {after} | Win% (me): {wb:.0f} -> {wa:.0f}"


def _clock_line(r: MoveReport, clocks, tc, my_color: chess.Color) -> str:
    info = clock_at(r.ply, clocks, tc)
    if info is None:
        return "Clock: n/a"
    who = "me" if r.color == my_color else "opponent"
    other = "opponent" if r.color == my_color else "me"
    text = (f"Clock: {who} {fmt_clock(info.before_s)} left before the move, "
            f"spent {fmt_clock(info.spent_s)} | {other} {fmt_clock(info.opponent_s)}")
    return text + (" | TIME PRESSURE" if info.pressure else "")


def build_summary(meta: GameMeta, reports: list[MoveReport]) -> str:
    my_color = chess.WHITE if meta.my_color == "white" else chess.BLACK
    color_name = "White" if my_color == chess.WHITE else "Black"
    clocks = clocks_from_pgn(meta.pgn)
    tc = parse_time_control(meta.time_control)
    acc_me, acc_opp = game_accuracy(reports, my_color), game_accuracy(reports, not my_color)

    def acc(a: float | None) -> str:
        return f"{a:.1f}%" if a is not None else "n/a"

    thresholds = ", ".join(f"{name} >= {limit:g}" for limit, name in reversed(WIN_THRESHOLDS))
    lines = [
        HEADER,
        f"I played: {color_name} ({meta.my_rating or '?'})",
        f"Opponent: {meta.opponent} ({meta.opponent_rating or '?'})",
        f"Result: {meta.outcome_label}",
        f"Time control: {meta.format_label}",
        f"Date: {meta.end_dt:%Y-%m-%d}",
        f"Link: {meta.url}",
        f"Accuracy: me {acc(acc_me)} | opponent {acc(acc_opp)}",
        "Conventions: Eval is Stockfish in pawns and Win% is win probability (lichess formula), "
        "both from MY point of view (+ / high = good for me). M3 = I mate in 3, -M3 = I get mated. "
        "FEN is the position before the move. "
        f"Severity = drop in the mover's Win% ({thresholds}).",
        f"PGN: {_movetext(meta.pgn)}",
        "",
        f"== My critical moments (most severe first, max {MAX_MOMENTS}) ==",
    ]

    moments = critical_moments(reports, my_color)
    if not moments:
        lines += ["None: no inaccuracies, mistakes or blunders of mine.", ""]
    for i, r in enumerate(moments, 1):
        board = chess.Board(r.fen_before)
        lines += [
            f"{i}) Move {r.move_label} {r.san} – {CATEGORY_LABEL[r.category]} "
            f"(Win% drop {r.win_drop:.1f}) | Phase: {game_phase(board)}",
            f"FEN: {r.fen_before}",
            f"Played: {r.san} ({r.uci}) | Best: {r.best_san or '?'} ({r.best_uci or '?'})",
            _win_line(r, my_color),
            f"Tactic: {r.explanation or NOT_DETECTED}",
            f"Line after played: {line_after_played(r)}",
            f"Line after best: {r.best_san or '?'}, then {line_after_best(r)}",
            _clock_line(r, clocks, tc, my_color),
            "",
        ]

    misses = opponent_misses(reports, my_color)
    lines.append("== Opponent's mistakes I did not punish (max 3) ==")
    if not misses:
        lines += ["None.", ""]
    for i, m in enumerate(misses, 1):
        t, rep = m.theirs, m.reply
        board = chess.Board(rep.fen_before)
        lines += [
            f"{i}) Their move {t.move_label} {t.san} – {CATEGORY_LABEL[t.category]} "
            f"(their Win% drop {t.win_drop:.1f}) | Phase: {game_phase(board)}",
            f"FEN (my turn): {rep.fen_before}",
            f"My reply: {rep.san} ({rep.uci}) | Best reply: {rep.best_san or '?'} ({rep.best_uci or '?'})",
            _win_line(rep, my_color),
            f"Tactic (their mistake; 'your' = the opponent): {t.explanation or NOT_DETECTED}",
            f"Line after best reply: {rep.best_san or '?'}, then {line_after_best(rep)}",
            _clock_line(rep, clocks, tc, my_color),
            "",
        ]

    great = [r for r in reports if r.color == my_color and r.category == "great"][:MAX_HIGHLIGHTS]
    if great:
        lines.append("== Good moments (only moves I found) ==")
        for r in great:
            lines.append(f"- Move {r.full_label}: {r.explanation} | FEN: {r.fen_before}")
        lines.append("")

    lines.append(FINAL_INSTRUCTION)
    return "\n".join(lines).strip()
