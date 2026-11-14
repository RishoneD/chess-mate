"""Classify every move by the drop in win probability (lichess formula): good moves and mistakes."""

from __future__ import annotations

import math
from dataclasses import dataclass

import chess

from engine import PositionEval
from explain import explain, pov_mate

EVAL_CAP = 1000  # cap evaluations at ±10 pawns (charts, and before converting to win%)
# Win probability from centipawns, as on lichess: 50 + 50 * (2 / (1 + exp(-k * cp)) - 1)
WIN_K = 0.00368208
# Severity thresholds on the drop of the mover's win% (lichess: 0.1/0.2/0.3 in winning chances).
# Near equality they match ~55/110/175 centipawns; in decided positions the curve is flat,
# so a large centipawn swing there counts for little (no separate softening rule needed).
WIN_THRESHOLDS = [(15.0, "blunder"), (10.0, "mistake"), (5.0, "inaccuracy")]
WINNING = 500  # centipawns: beyond ±this the position is decided ("great" moves are not counted)
EXCELLENT_MAX = 1.0  # win% drop up to which a non-best move is "excellent" (~10 cp near equality)
ONLY_MOVE_GAP = 10.0  # win%: the second-best move must be at least this much worse for an "only move"
# Without an opening book, small engine preferences in the opening are noise:
# inaccuracies in the first OPENING_MOVES moves are not flagged (mistakes and blunders still are).
OPENING_MOVES = 8

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


def capped(cp: int) -> int:
    return max(-EVAL_CAP, min(EVAL_CAP, cp))


def win_pct(cp: int, mate: int | None = None) -> float:
    """Win probability (0–100) for the side whose point of view cp/mate are in.
    Mate: 100 if that side mates (or has mated), 0 if it gets mated."""
    if mate is not None:
        return 100.0 if (mate > 0 or (mate == 0 and cp > 0)) else 0.0
    return 50 + 50 * (2 / (1 + math.exp(-WIN_K * capped(cp))) - 1)


def eval_win_pct(ev: PositionEval, color: chess.Color) -> float:
    """Win% of `color` for an engine evaluation (which is from White's view)."""
    sign = 1 if color == chess.WHITE else -1
    mate = None if ev.mate is None else ev.mate * sign
    return win_pct(ev.cp * sign, mate)


def move_accuracy(win_drop: float) -> float:
    """lichess per-move accuracy from the drop in win%."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * win_drop) - 3.1669))


def game_accuracy(reports: list["MoveReport"], color: chess.Color) -> float | None:
    """Mean of the arithmetic and harmonic means of per-move accuracy (no volatility weighting,
    so it is close to, but not the same as, lichess or chess.com)."""
    accs = [move_accuracy(r.win_drop) for r in reports if r.color == color]
    if not accs:
        return None
    mean = sum(accs) / len(accs)
    harmonic = len(accs) / sum(1 / max(a, 1.0) for a in accs)
    return (mean + harmonic) / 2


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
    loss: int  # centipawns, from the mover's point of view
    win_before: float  # mover's win%, before and after the move
    win_after: float
    win_drop: float  # mover's win% lost by this move (0 when the best move was played)
    category: str  # one of CATEGORY_ORDER
    explanation: str | None  # for mistakes (None = no tactic detected) and great moves
    pv_best: tuple[str, ...] = ()  # UCI line from fen_before, starting with the best move
    pv_after: tuple[str, ...] = ()  # UCI line after the move played (opponent's best reply first)

    @property
    def full_label(self) -> str:
        return f"{self.move_label}{self.san}"

    @property
    def played_best(self) -> bool:
        return self.best_uci == self.uci


def categorize(win_drop: float, missed_mate: bool) -> str | None:
    """Mistake category from the mover's win% drop, or None."""
    category = next((name for limit, name in WIN_THRESHOLDS if win_drop >= limit), None)
    if missed_mate and category is None:
        category = "inaccuracy"
    return category


def categorize_good(played_best: bool, win_drop: float, gap: float | None,
                    before_cp: int, trivial: bool) -> str:
    """Category for a move that is not a mistake.

    gap: how much worse (in win%) the second-best move is, None if there was only one legal move.
    before_cp: evaluation before the move, mover's view, capped.
    trivial: a recapture or the capture punishing an opponent's mistake; never counted as "great".
    """
    if played_best:
        undecided = -WINNING < before_cp < WINNING
        if gap is not None and gap >= ONLY_MOVE_GAP and undecided and not trivial:
            return "great"
        return "best"
    return "excellent" if win_drop <= EXCELLENT_MAX else "good"


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
        win_b, win_a = eval_win_pct(ev_b, mover), eval_win_pct(ev_a, mover)
        win_drop = 0.0 if played_best else max(0.0, win_b - win_a)

        mate_b, mate_a = pov_mate(ev_b, mover), pov_mate(ev_a, mover)
        missed_mate = (not played_best and mate_b is not None and mate_b > 0
                       # mate_a == 0: the move itself delivered mate (any mating move will do)
                       and not (mate_a is not None and mate_a >= 0))
        category = categorize(win_drop, missed_mate)
        if category == "inaccuracy" and board.fullmove_number <= OPENING_MOVES and not missed_mate:
            category = None

        explanation = None
        if category:
            explanation = explain(board, move, ev_b, ev_a, loss, before, after)
        else:
            gap = None
            if ev_b.second_cp is not None:
                second_mate = None if ev_b.second_mate is None else ev_b.second_mate * sign
                gap = win_b - win_pct(ev_b.second_cp * sign, second_mate)
            prev_move = moves[i - 1] if i > 0 else None
            recapture = (prev_move is not None and boards[i - 1].is_capture(prev_move)
                         and move.to_square == prev_move.to_square)
            punishes = (board.is_capture(move) and bool(reports)
                        and is_mistake(reports[-1].category))
            category = categorize_good(played_best, win_drop, gap, before, recapture or punishes)
            if category == "great":
                second = _san_or_none(board, ev_b.second_move) or "the alternative"
                second_mate = (ev_b.second_mate * sign) if ev_b.second_mate is not None else None
                if second_mate is not None and second_mate < 0:
                    explanation = f"Only move: every alternative allows mate (e.g. {second} allows mate in {-second_mate})"
                else:
                    explanation = (f"Only good move: the next best ({second}) "
                                   f"would cost {gap:.0f}% win probability")

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
            win_before=win_b,
            win_after=win_a,
            win_drop=win_drop,
            category=category,
            explanation=explanation,
            pv_best=ev_b.pv,
            pv_after=ev_a.pv,
        ))
    return reports


def count_categories(reports: list[MoveReport], color: chess.Color) -> dict[str, int]:
    counts = {name: 0 for name in CATEGORY_ORDER}
    for r in reports:
        if r.color == color:
            counts[r.category] += 1
    return counts
