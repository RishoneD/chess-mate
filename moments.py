"""Details for each critical moment: engine lines in SAN, clock, game phase, opponent's mistakes."""

from __future__ import annotations

import io
from dataclasses import dataclass

import chess
import chess.pgn

from classify import MoveReport, is_mistake

LINE_PLIES = 4  # half-moves shown in each refutation line
OPENING_PHASE_MOVES = 12  # moves 1–12 count as the opening (unless it is already an endgame)
ENDGAME_MATERIAL = 26  # endgame: both sides' non-pawn material together is at most this (Q=9 R=5 B=N=3)
TIME_PRESSURE_FRACTION = 0.10  # less than 10% of the base time left before the move
TIME_PRESSURE_MIN_S = 30  # ... or less than 30 seconds
MAX_OPPONENT_MISSES = 3

_NON_PAWN_VALUE = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


# ---------- engine lines ----------

def line_san(board: chess.Board, ucis: tuple[str, ...] | list[str], plies: int = LINE_PLIES) -> str:
    """Up to `plies` legal moves of a UCI line, in numbered SAN (e.g. '12... Bxa4 13. Qxa4')."""
    b = board.copy(stack=False)
    moves = []
    for uci in list(ucis)[:plies]:
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            break
        moves.append(move)
        b.push(move)
    if not moves:
        return ""
    return board.copy(stack=False).variation_san(moves)


def line_after_played(r: MoveReport, plies: int = LINE_PLIES) -> str:
    """The engine's continuation after the move played, starting with the opponent's best reply."""
    board = chess.Board(r.fen_before)
    board.push(chess.Move.from_uci(r.uci))
    if board.is_game_over():
        return "(game over)"
    return line_san(board, r.pv_after, plies) or "(no line)"


def line_after_best(r: MoveReport, plies: int = LINE_PLIES) -> str:
    """The engine's continuation after the best move (the best move itself is not repeated)."""
    if not r.best_uci:
        return "(no line)"
    board = chess.Board(r.fen_before)
    board.push(chess.Move.from_uci(r.best_uci))
    if board.is_game_over():
        return "(game over)"
    return line_san(board, r.pv_best[1:], plies) or "(no line)"


# ---------- game phase ----------

def non_pawn_material(board: chess.Board) -> int:
    return sum(v * len(board.pieces(pt, c)) for pt, v in _NON_PAWN_VALUE.items() for c in chess.COLORS)


def game_phase(board: chess.Board) -> str:
    if non_pawn_material(board) <= ENDGAME_MATERIAL:
        return "endgame"
    if board.fullmove_number <= OPENING_PHASE_MOVES:
        return "opening"
    return "middlegame"


# ---------- clock ----------

@dataclass(frozen=True)
class TimeControl:
    base_s: int
    inc_s: int


def parse_time_control(tc: str) -> TimeControl | None:
    """'600' -> 600+0, '180+2' -> 180+2. Daily ('1/86400') and unknown formats -> None."""
    if not tc or "/" in tc:
        return None
    base, _, inc = tc.partition("+")
    try:
        return TimeControl(int(base), int(inc or 0))
    except ValueError:
        return None


def clocks_from_pgn(pgn: str) -> list[float | None]:
    """Clock (seconds) of the mover right after each ply, from the PGN's [%clk] comments."""
    game = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
    if game is None:
        return []
    return [node.clock() for node in game.mainline()]


@dataclass(frozen=True)
class ClockInfo:
    before_s: float  # mover's time left when the move was started
    spent_s: float | None
    opponent_s: float | None  # opponent's time left at that moment
    pressure: bool


def clock_at(ply: int, clocks: list[float | None], tc: TimeControl | None) -> ClockInfo | None:
    """Clock situation for the move at `ply`, or None without clock data."""
    if tc is None or ply >= len(clocks) or clocks[ply] is None:
        return None
    after = clocks[ply]
    # mover's clock before this move: their clock after their previous move (or the base time)
    before = clocks[ply - 2] if ply >= 2 else float(tc.base_s)
    if before is None:
        before = after
    spent = max(0.0, before + tc.inc_s - after)
    opponent = clocks[ply - 1] if ply >= 1 else float(tc.base_s)
    pressure = before < max(TIME_PRESSURE_FRACTION * tc.base_s, TIME_PRESSURE_MIN_S)
    return ClockInfo(before, spent, opponent, pressure)


def fmt_clock(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------- opponent's unpunished mistakes ----------

@dataclass(frozen=True)
class OpponentMiss:
    theirs: MoveReport  # the opponent's mistake
    reply: MoveReport  # my reply, which did not take the chance


def opponent_misses(reports: list[MoveReport], my_color: chess.Color,
                    limit: int = MAX_OPPONENT_MISSES) -> list[OpponentMiss]:
    """The opponent's biggest mistakes that I did not exploit: my reply was not the best move and
    gave back at least half of what they lost (in win%), or was itself an inaccuracy or worse."""
    found = []
    for theirs, reply in zip(reports, reports[1:]):
        if theirs.color == my_color or not is_mistake(theirs.category):
            continue
        if reply.played_best:
            continue
        if reply.win_drop >= theirs.win_drop / 2 or is_mistake(reply.category):
            found.append(OpponentMiss(theirs, reply))
    found.sort(key=lambda m: m.theirs.win_drop, reverse=True)
    return found[:limit]
