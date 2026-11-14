"""Classification and explanation tests. Integration tests require Stockfish."""

import io

import chess
import chess.pgn
import pytest

from classify import (CATEGORY_ORDER, categorize, categorize_good, classify_moves,
                      move_accuracy, win_pct)
from engine import analyze_positions, find_stockfish, game_positions

needs_engine = pytest.mark.skipif(find_stockfish() is None, reason="Stockfish not found")


def test_win_pct():
    assert win_pct(0) == 50
    assert round(win_pct(100), 1) == 59.1
    assert round(win_pct(-100) + win_pct(100), 6) == 100
    assert win_pct(5000) == win_pct(1000)  # capped like the evaluations
    assert win_pct(100_000, 3) == 100 and win_pct(-100_000, -3) == 0
    assert win_pct(100_000, 0) == 100 and win_pct(-100_000, 0) == 0  # mate on the board


def test_categorize_thresholds():
    assert categorize(4.9, False) is None
    assert categorize(5.0, False) == "inaccuracy"
    assert categorize(10.0, False) == "mistake"
    assert categorize(15.0, False) == "blunder"


def test_decided_positions_count_for_little():
    # +8 -> +5 is 3 pawns (a blunder in centipawns), but only ~9% win probability
    assert categorize(win_pct(800) - win_pct(500), False) == "inaccuracy"
    # +10 -> +8: 2 pawns, but the game stays won
    assert categorize(win_pct(1000) - win_pct(800), False) is None
    # equal -> -3 is a blunder
    assert categorize(win_pct(0) - win_pct(-300), False) == "blunder"


def test_categorize_missed_mate_always_flagged():
    assert categorize(1.0, True) == "inaccuracy"


def test_categorize_good():
    assert categorize_good(True, 0, 3, 0, False) == "best"
    assert categorize_good(True, 0, 15, 0, False) == "great"
    assert categorize_good(True, 0, None, 0, False) == "best"  # only one legal move
    assert categorize_good(True, 0, 15, 0, True) == "best"  # recapture / punishing a mistake
    assert categorize_good(True, 0, 15, 700, False) == "best"  # already winning
    assert categorize_good(False, 0.8, None, 0, False) == "excellent"
    assert categorize_good(False, 3, None, 0, False) == "good"


def test_accuracy():
    assert round(move_accuracy(0), 1) == 100.0
    assert move_accuracy(100) == 0
    assert 0 < move_accuracy(10) < move_accuracy(5) < 100


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
def test_any_mating_move_is_not_a_missed_mate():
    # Both Ra8# and Re8# mate; whichever the engine prefers, the other is not a mistake
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R3R1K1 w - - 0 1")
    for uci in ("a1a8", "e1e8"):
        b = board.copy()
        move = chess.Move.from_uci(uci)
        after = b.copy()
        after.push(move)
        evals = analyze_positions([b, after], find_stockfish(), budget_s=2, max_depth=10)
        report = classify_moves([b, after], [move], evals)[0]
        assert report.category in ("best", "excellent", "good", "great"), (uci, report.category)
