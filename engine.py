"""Run Stockfish on every position of a game, via python-chess."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import chess
import chess.engine
import chess.pgn

MATE_CP = 100_000  # internal value for mate, before capping for display
PV_PLIES = 8

DEFAULT_BUDGET_S = 30.0
DEFAULT_MAX_DEPTH = 18

# Determinism: a single search thread plus a fixed node count per position gives the same
# result for the same game on every run (a time limit does not). The node count is derived
# from the engine's measured speed, then rounded down to a fixed step so that small speed
# fluctuations do not change it.
ENGINE_OPTIONS = {"Threads": 1, "Hash": 64}
NODE_STEPS = [int(25_000 * 2 ** (k / 2)) for k in range(17)]  # 25k ... 6.4M, ×√2 apart
CALIBRATION_FENS = [  # opening, middlegame, endgame
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 9",
    "8/5pk1/6p1/3r4/7P/6P1/5PK1/3R4 w - - 0 40",
]
CALIBRATION_NODES = 60_000
FALLBACK_NPS = 300_000
_nps_cache: dict[str, int] = {}


@dataclass(frozen=True)
class PositionEval:
    """Evaluation of one position, always from White's point of view."""
    fen: str
    cp: int  # centipawns from White's view; mate is ±MATE_CP
    mate: int | None  # mate in N moves: positive = White mates, negative = Black mates, 0 = mate on board
    best_move: str | None  # UCI
    pv: tuple[str, ...]  # UCI, starting with the best move
    depth: int
    second_cp: int | None = None  # White's view; eval of the second-best move (None if only one legal move)
    second_move: str | None = None  # UCI
    second_mate: int | None = None  # White's view, like `mate`, for the second-best move


def find_stockfish() -> str | None:
    """Locate Stockfish: STOCKFISH_PATH, then PATH, then the Debian install location."""
    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path and Path(env_path).is_file():
        return env_path
    found = shutil.which("stockfish")
    if found:
        return found
    debian = Path("/usr/games/stockfish")
    if debian.is_file():
        return str(debian)
    return None


def game_positions(game: chess.pgn.Game) -> tuple[list[chess.Board], list[chess.Move]]:
    """All positions (including the starting one) and all moves of the game."""
    board = game.board()
    boards = [board.copy()]
    moves = []
    for move in game.mainline_moves():
        moves.append(move)
        board.push(move)
        boards.append(board.copy())
    return boards, moves


def _terminal_eval(board: chess.Board) -> PositionEval | None:
    """Game-over positions (mate/stalemate/dead draw) are not sent to the engine."""
    if board.is_checkmate():
        # the side to move has been mated
        sign = -1 if board.turn == chess.WHITE else 1
        return PositionEval(board.fen(), sign * MATE_CP, 0, None, (), 0)
    if board.is_stalemate() or board.is_insufficient_material():
        return PositionEval(board.fen(), 0, None, None, (), 0)
    return None


def _to_eval(board: chess.Board, infos: list[chess.engine.InfoDict]) -> PositionEval:
    """infos is the MultiPV result: [best line, second-best line (if any)]."""
    info = infos[0]
    score = info["score"].white()
    pv = tuple(m.uci() for m in info.get("pv", [])[:PV_PLIES])
    second_cp = second_move = second_mate = None
    if len(infos) > 1 and "score" in infos[1] and infos[1].get("pv"):
        second_score = infos[1]["score"].white()
        second_cp = second_score.score(mate_score=MATE_CP)
        second_mate = second_score.mate()
        second_move = infos[1]["pv"][0].uci()
    return PositionEval(
        fen=board.fen(),
        cp=score.score(mate_score=MATE_CP),
        mate=score.mate(),
        best_move=pv[0] if pv else None,
        pv=pv,
        depth=int(info.get("depth", 0)),
        second_cp=second_cp,
        second_move=second_move,
        second_mate=second_mate,
    )


def measure_nps(engine_path: str) -> int:
    """Effective engine speed (nodes per wall-clock second) for our workload: many short
    MultiPV searches, including per-search overhead. Measured once per process and cached."""
    if engine_path not in _nps_cache:
        nps = 0
        try:
            with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                engine.configure(ENGINE_OPTIONS)
                engine.analyse(chess.Board(), chess.engine.Limit(nodes=5_000))  # warm-up
                nodes = 0
                start = time.perf_counter()
                for _ in range(2):
                    for fen in CALIBRATION_FENS:
                        infos = engine.analyse(chess.Board(fen),
                                               chess.engine.Limit(nodes=CALIBRATION_NODES), multipv=2)
                        nodes += int(infos[0].get("nodes", 0))
                elapsed = time.perf_counter() - start
                nps = int(nodes / elapsed) if elapsed > 0 else 0
        except chess.engine.EngineError:
            pass
        _nps_cache[engine_path] = nps or FALLBACK_NPS
    return _nps_cache[engine_path]


def nodes_for_budget(nps: int, budget_s: float, positions: int) -> int:
    """Largest node step that fits the time budget (at least the smallest step)."""
    target = nps * budget_s / max(positions, 1)
    fitting = [n for n in NODE_STEPS if n <= target]
    return fitting[-1] if fitting else NODE_STEPS[0]


def analyze_positions(
    boards: list[chess.Board],
    engine_path: str,
    budget_s: float = DEFAULT_BUDGET_S,
    max_depth: int = DEFAULT_MAX_DEPTH,
    progress: Callable[[int, int], None] | None = None,
    nodes: int | None = None,
) -> list[PositionEval]:
    """Analyze every position with a fixed node count (deterministic) and a depth cap."""
    total = len(boards)
    if nodes is None:
        nodes = nodes_for_budget(measure_nps(engine_path), budget_s, total)
    limit = chess.engine.Limit(depth=max_depth, nodes=nodes)
    results: list[PositionEval] = []
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        engine.configure(ENGINE_OPTIONS)
        for i, board in enumerate(boards):
            ev = _terminal_eval(board)
            if ev is None:
                # MultiPV=2: the second line is needed to detect "only moves"
                infos = engine.analyse(board, limit, multipv=2)
                ev = _to_eval(board, infos)
            results.append(ev)
            if progress:
                progress(i + 1, total)
    return results
