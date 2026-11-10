"""Classify every move by centipawn loss: good moves and mistakes."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from engine import PositionEval
from explain import explain, pov_mate

EVAL_CAP = 1000  # cap evaluations at ±10 pawns before computing loss
WINNING = 500  # above this (or below minus this) the position is decided
EXCELLENT_MAX = 10  # centipawn loss up to which a non-best move is "excellent"
ONLY_MOVE_GAP = 150  # the second-best move must be at least this much worse for an "only move"
# Without an opening book, small engine preferences in the opening are noise:
# inaccuracies in the first OPENING_MOVES moves are not flagged (mistakes and blunders still are).
OPENING_MOVES = 8

THRESHOLDS = [(200, "blunder"), (100, "mistake"), (50, "inaccuracy")]
GOOD = ["great", "best", "excellent", "good"]
MISTAKES = ["inaccuracy", "mistake", "blunder"]
CATEGORY_ORDER = GOOD + MISTAKES  # display order, best to worst
CATEGORY_LABEL = {
    "great": "Great (only move)", "best": "Best", "excellent": "Excellent", "good": "Good",
    "inaccuracy": "Inaccuracy", "mistake": "Mistake", "blunder": "Blunder",
}
CATEGORY_ICON = {
    "great": "🌟", "best": "⭐", "excellent": "✅", "good": "👍",
    "inaccuracy": "🟡", "mistake": "🟠", "blunder": "🔴",
}


def is_mistake(category: str | None) -> bool:
    return category in MISTAKES


@dataclass(frozen=True)
class MoveReport:
    ply: int  # index of the move in the game (0 = first move)
    move_label: str  # "12." or "12..."
    color: chess.Color
    san: str
    uci: str
    fen_before: str
    best_san: str | None
    best_uci: str | None
    eval_before: int  # White's view, capped at ±EVAL_CAP
    eval_after: int
    mate_before: int | None  # White's view, as in PositionEval
    mate_after: int | None
    loss: int  # from the mover's point of view
    category: str  # one of CATEGORY_ORDER
    explanation: str | None  # for mistakes and great moves

    @property
    def full_label(self) -> str:
        return f"{self.move_label}{self.san}"


def capped(cp: int) -> int:
    return max(-EVAL_CAP, min(EVAL_CAP, cp))


def categorize(loss: int, before: int, after: int, missed_mate: bool) -> str | None:
    """Mistake category, or None. before/after are from the mover's point of view, after capping."""
    category = next((name for limit, name in THRESHOLDS if loss >= limit), None)
    decided = after >= WINNING or before <= -WINNING
    if category and decided:
        # in a decided position a large loss matters less
        category = "inaccuracy" if loss >= 200 else None
    if missed_mate and category is None:
        category = "inaccuracy"
    return category


def categorize_good(played_best: bool, loss: int, gap: int | None,
                    before: int, trivial: bool) -> str:
    """Category for a move that is not a mistake.

    gap: how much worse the second-best move is (mover's view), None if there was only one legal move.
    trivial: a recapture or the capture punishing an opponent's mistake; never counted as "great".
    """
    if played_best:
        undecided = -WINNING < before < WINNING
        if gap is not None and gap >= ONLY_MOVE_GAP and undecided and not trivial:
            return "great"
        return "best"
    return "excellent" if loss <= EXCELLENT_MAX else "good"


def _san_or_none(board: chess.Board, uci: str | None) -> str | None:
    if not uci:
        return None
    move = chess.Move.from_uci(uci)
    return board.san(move) if move in board.legal_moves else None


def classify_moves(
    boards: list[chess.Board],
    moves: list[chess.Move],
    evals: list[PositionEval],
) -> list[MoveReport]:
    reports: list[MoveReport] = []
    for i, move in enumerate(moves):
        board = boards[i]
        mover = board.turn
        sign = 1 if mover == chess.WHITE else -1
        ev_b, ev_a = evals[i], evals[i + 1]
        before = capped(ev_b.cp) * sign
        after = capped(ev_a.cp) * sign
        played_best = ev_b.best_move == move.uci()
        loss = 0 if played_best else max(0, before - after)

        mate_b, mate_a = pov_mate(ev_b, mover), pov_mate(ev_a, mover)
        missed_mate = (not played_best and mate_b is not None and mate_b > 0
                       and not (mate_a is not None and mate_a > 0))
        category = categorize(loss, before, after, missed_mate)
        if category == "inaccuracy" and board.fullmove_number <= OPENING_MOVES and not missed_mate:
            category = None

        explanation = None
        if category:
            explanation = explain(board, move, ev_b, ev_a, loss, before, after)
        else:
            gap = None
            if ev_b.second_cp is not None:
                gap = before - capped(ev_b.second_cp) * sign
            prev_move = moves[i - 1] if i > 0 else None
            recapture = (prev_move is not None and boards[i - 1].is_capture(prev_move)
                         and move.to_square == prev_move.to_square)
            punishes = (board.is_capture(move) and bool(reports)
                        and is_mistake(reports[-1].category))
            category = categorize_good(played_best, loss, gap, before, recapture or punishes)
            if category == "great":
                second = _san_or_none(board, ev_b.second_move) or "the alternative"
                second_mate = (ev_b.second_mate * sign) if ev_b.second_mate is not None else None
                if second_mate is not None and second_mate < 0:
                    explanation = f"Only move: every alternative allows mate (e.g. {second} allows mate in {-second_mate})"
                else:
                    explanation = f"Only good move: the next best ({second}) was {gap / 100:.1f} pawns worse"

        num = board.fullmove_number
        reports.append(MoveReport(
            ply=i,
            move_label=f"{num}." if mover == chess.WHITE else f"{num}...",
            color=mover,
            san=board.san(move),
            uci=move.uci(),
            fen_before=board.fen(),
            best_san=_san_or_none(board, ev_b.best_move),
            best_uci=ev_b.best_move,
            eval_before=capped(ev_b.cp),
            eval_after=capped(ev_a.cp),
            mate_before=ev_b.mate,
            mate_after=ev_a.mate,
            loss=loss,
            category=category,
            explanation=explanation,
        ))
    return reports


def count_categories(reports: list[MoveReport], color: chess.Color) -> dict[str, int]:
    counts = {name: 0 for name in CATEGORY_ORDER}
    for r in reports:
        if r.color == color:
            counts[r.category] += 1
    return counts
