"""Classification and explanation tests. Integration tests require Stockfish."""

import io

import chess
import chess.pgn
import pytest

from chesscom import GameMeta
from classify import CATEGORY_ORDER, categorize, categorize_good, classify_moves
from engine import analyze_positions, find_stockfish, game_positions
from summary import build_summary, critical_moments

needs_engine = pytest.mark.skipif(find_stockfish() is None, reason="Stockfish not found")


def test_categorize_thresholds():
    assert categorize(40, 0, -40, False) is None
    assert categorize(60, 0, -60, False) == "inaccuracy"
    assert categorize(150, 0, -150, False) == "mistake"
    assert categorize(300, 0, -300, False) == "blunder"


def test_categorize_decided_positions_are_softened():
    assert categorize(300, 1000, 700, False) == "inaccuracy"
    assert categorize(150, 900, 750, False) is None
    assert categorize(300, -600, -900, False) == "inaccuracy"


def test_categorize_missed_mate_always_flagged():
    assert categorize(20, 1000, 980, True) == "inaccuracy"


def test_categorize_good():
    assert categorize_good(True, 0, 50, 0, False) == "best"
    assert categorize_good(True, 0, 200, 0, False) == "great"
    assert categorize_good(True, 0, None, 0, False) == "best"  # only one legal move
    assert categorize_good(True, 0, 200, 0, True) == "best"  # recapture / punishing a mistake
    assert categorize_good(True, 0, 200, 700, False) == "best"  # already winning
    assert categorize_good(False, 8, None, 0, False) == "excellent"
    assert categorize_good(False, 30, None, 0, False) == "good"


def _analyze(pgn: str):
    game = chess.pgn.read_game(io.StringIO(pgn))
    boards, moves = game_positions(game)
    evals = analyze_positions(boards, find_stockfish(), budget_s=4, max_depth=14)
    return classify_moves(boards, moves, evals)


@needs_engine
def test_analysis_is_deterministic():
    game = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 *"))
    boards, _ = game_positions(game)
    first = analyze_positions(boards, find_stockfish(), nodes=50_000)
    second = analyze_positions(boards, find_stockfish(), nodes=50_000)
    assert first == second


def test_nodes_for_budget_uses_fixed_steps():
    from engine import NODE_STEPS, nodes_for_budget
    assert nodes_for_budget(800_000, 30, 80) in NODE_STEPS
    assert nodes_for_budget(800_000, 30, 80) <= 800_000 * 30 / 80
    # small speed changes inside a step give the same node count
    assert nodes_for_budget(800_000, 30, 80) == nodes_for_budget(780_000, 30, 80)
    assert nodes_for_budget(1, 1, 100) == NODE_STEPS[0]


@needs_engine
def test_every_move_gets_a_category():
    reports = _analyze("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *")
    assert len(reports) == 10
    assert all(r.category in CATEGORY_ORDER for r in reports)


@needs_engine
def test_recapture_is_never_great():
    # 2...Qxd5 recaptures; it may be best, but must not be counted as an only move
    reports = _analyze("1. e4 d5 2. exd5 Qxd5 *")
    assert reports[3].category != "great"


@needs_engine
def test_allowed_mate():
    reports = _analyze("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0")
    nf6 = reports[5]
    assert nf6.san == "Nf6"
    assert nf6.category == "blunder"
    assert nf6.explanation == "Allowed mate in 1"


@needs_engine
def test_missed_mate():
    reports = _analyze("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. d3 *")
    d3 = reports[6]
    assert d3.category is not None
    assert d3.explanation == "Missed mate in 1"
    assert d3.best_san == "Qxf7#"


@needs_engine
def test_lost_piece_and_missed_capture():
    reports = _analyze("1. e4 e5 2. Nf3 Qh4 3. d3 *")
    qh4, d3 = reports[3], reports[4]
    assert qh4.category == "blunder"
    assert qh4.explanation == "Left your queen on h4 undefended"
    assert d3.category == "blunder"
    assert d3.explanation == "Missed a free queen on h4"
    assert d3.best_san == "Nxh4"


@needs_engine
def test_summary_contains_critical_moments():
    reports = _analyze("1. e4 e5 2. Nf3 Qh4 3. d3 Qb4+ 4. c3 *")
    meta = GameMeta(
        url="https://www.chess.com/game/live/1", pgn="", end_time=1794300896,
        time_class="rapid", time_control="600", my_color="black",
        opponent="opp", opponent_rating=1048, my_rating=1034,
        outcome="loss", result_code="resigned",
    )
    moments = critical_moments(reports, chess.BLACK)
    assert moments and all(m.color == chess.BLACK for m in moments)
    text = build_summary(meta, reports)
    assert "I played Black" in text
    assert "Move 2..." in text
    assert "FEN: rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2" in text
    assert "Result: Loss (resignation)" in text
