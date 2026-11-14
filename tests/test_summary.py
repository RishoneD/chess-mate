"""Copy summary (Format v2) and moment details: lines, clock, phase, opponent's misses."""

import io
import re

import chess
import chess.pgn
import pytest

from chesscom import GameMeta
from classify import MoveReport, classify_moves
from engine import analyze_positions, find_stockfish, game_positions
from moments import (TimeControl, clock_at, clocks_from_pgn, fmt_clock, game_phase,
                     line_after_best, line_after_played, line_san, opponent_misses,
                     parse_time_control)
from summary import FINAL_INSTRUCTION, HEADER, MAX_MOMENTS, build_summary, critical_moments

needs_engine = pytest.mark.skipif(find_stockfish() is None, reason="Stockfish not found")


def _meta(pgn: str, color: str = "white", tc: str = "600", result_code: str = "resigned",
          outcome: str = "win") -> GameMeta:
    return GameMeta(
        url="https://www.chess.com/game/live/1", pgn=pgn, end_time=1794300896,
        time_class="rapid", time_control=tc, my_color=color,
        opponent="opp", opponent_rating=1048, my_rating=1034,
        outcome=outcome, result_code=result_code,
    )


def _analyze(pgn: str) -> list[MoveReport]:
    game = chess.pgn.read_game(io.StringIO(pgn))
    boards, moves = game_positions(game)
    evals = analyze_positions(boards, find_stockfish(), budget_s=4, max_depth=14)
    return classify_moves(boards, moves, evals)


def _report(ply: int, color: chess.Color, category: str, win_drop: float,
            uci: str = "e2e4", best: str = "d2d4", **kw) -> MoveReport:
    fields = dict(
        ply=ply, move_label=f"{ply // 2 + 1}." if color == chess.WHITE else f"{ply // 2 + 1}...",
        color=color, san="x", uci=uci, fen_before=chess.STARTING_FEN, best_san="y", best_uci=best,
        eval_before=0, eval_after=0, mate_before=None, mate_after=None, loss=0,
        win_before=50, win_after=50 - win_drop, win_drop=win_drop,
        category=category, explanation=None,
    )
    fields.update(kw)
    return MoveReport(**fields)


# ---------- pure helpers ----------

def test_line_san_numbers_moves_and_stops_at_illegal():
    board = chess.Board()
    assert line_san(board, ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]) == "1. e4 e5 2. Nf3 Nc6"
    assert line_san(board, ["e2e4", "e2e4"]) == "1. e4"  # second move is illegal
    board.push_san("e4")
    assert line_san(board, ["e7e5", "g1f3"]) == "1...e5 2. Nf3"


def test_lines_after_played_and_best():
    r = _report(0, chess.WHITE, "inaccuracy", 6, uci="f2f3", best="e2e4",
                pv_best=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
                pv_after=("e7e5", "g2g4", "d8h4"))
    assert line_after_played(r) == "1...e5 2. g4 Qh4#"
    assert line_after_best(r) == "1...e5 2. Nf3 Nc6 3. Bb5"


def test_game_phase():
    assert game_phase(chess.Board()) == "opening"
    middlegame = chess.Board()
    middlegame.fullmove_number = 20
    assert game_phase(middlegame) == "middlegame"
    assert game_phase(chess.Board("8/5pk1/6p1/3r4/7P/6P1/5PK1/3R4 w - - 0 40")) == "endgame"
    # queens and one rook pair off: 2R+2B+2N... per side is still a middlegame
    assert game_phase(chess.Board("r1b1kb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1B1KB1R w KQkq - 0 15")) == "middlegame"


def test_time_control_and_clock():
    assert parse_time_control("600") == TimeControl(600, 0)
    assert parse_time_control("180+2") == TimeControl(180, 2)
    assert parse_time_control("1/86400") is None
    assert parse_time_control("") is None
    pgn = ('[TimeControl "180+2"]\n\n1. e4 {[%clk 0:03:01]} e5 {[%clk 0:02:55]} '
           '2. Nf3 {[%clk 0:00:20]} Nc6 {[%clk 0:02:50]} *')
    clocks = clocks_from_pgn(pgn)
    assert clocks == [181, 175, 20, 170]
    tc = parse_time_control("180+2")
    first = clock_at(0, clocks, tc)
    assert first.before_s == 180 and first.spent_s == 1 and not first.pressure
    third = clock_at(2, clocks, tc)  # 2. Nf3: from 3:01 to 0:20
    assert third.before_s == 181 and third.spent_s == 163 and third.opponent_s == 175
    assert not third.pressure  # pressure is judged on the time left *before* the move
    fourth = clock_at(3, [181, 175, 20, 170, 15], tc)
    assert fourth.opponent_s == 20
    fifth = clock_at(4, [181, 175, 20, 170, 15], tc)
    assert fifth.before_s == 20 and fifth.pressure
    assert fmt_clock(3725) == "1:02:05" and fmt_clock(65) == "1:05"


def test_no_clock_tags():
    assert clocks_from_pgn("1. e4 e5 *") == [None, None]
    assert clock_at(0, [None, None], TimeControl(600, 0)) is None
    assert clock_at(0, [], TimeControl(600, 0)) is None
    assert clock_at(0, [100.0], None) is None  # daily game


def test_opponent_misses():
    me, opp = chess.WHITE, chess.BLACK
    reports = [
        _report(0, me, "best", 0, uci="a", best="a"),
        _report(1, opp, "blunder", 20),          # their blunder...
        _report(2, me, "mistake", 12),           # ...and I gave it back: listed
        _report(3, opp, "mistake", 11),          # their mistake...
        _report(4, me, "best", 0, uci="b", best="b"),  # ...punished: not listed
        _report(5, opp, "inaccuracy", 6),        # their inaccuracy...
        _report(6, me, "good", 3.5),             # ...I gave back more than half: listed
    ]
    misses = opponent_misses(reports, me)
    assert [(m.theirs.ply, m.reply.ply) for m in misses] == [(1, 2), (5, 6)]


def test_critical_moments_order_and_limit():
    reports = [_report(i * 2, chess.WHITE, "inaccuracy", 5 + i) for i in range(12)]
    moments = critical_moments(reports, chess.WHITE)
    assert len(moments) == MAX_MOMENTS
    drops = [m.win_drop for m in moments]
    assert drops == sorted(drops, reverse=True)


def _evals_from_summary(text: str) -> list[tuple[str, str]]:
    return re.findall(r"Eval \(me\): (\S+) -> (\S+)", text)


# ---------- with the engine ----------

@needs_engine
def test_summary_layout_as_white():
    pgn = "1. e4 e5 2. Nf3 Qh4 3. d3 Qxf2+ 4. Kxf2 *"
    reports = _analyze(pgn)
    text = build_summary(_meta(pgn), reports)
    lines = text.splitlines()
    assert lines[0] == HEADER == "Chess game analysis (chess.com) | Format: v2"
    assert lines[-1] == FINAL_INSTRUCTION
    assert "I played: White (1034)" in text
    assert "PGN: 1. e4 e5 2. Nf3 Qh4 3. d3 Qxf2+ 4. Kxf2" in text
    assert re.search(r"Accuracy: me \d+\.\d% \| opponent \d+\.\d%", text)
    # White's mistake: 3. d3 missed the free queen
    assert "Move 3. d3 – Blunder" in text
    assert "Played: d3 (d2d3) | Best: Nxh4 (f3h4)" in text
    assert "Tactic: Missed a free queen on h4" in text
    assert "Line after played: 3..." in text
    assert "Line after best: Nxh4, then 3..." in text
    assert "Clock: n/a" in text  # no clock tags in this PGN
    # the opponent's 2...Qh4 blunder went unpunished
    assert "Their move 2... Qh4 – Blunder" in text
    assert "My reply: d3 (d2d3)" in text


@needs_engine
def test_summary_as_black_flips_evaluations():
    pgn = "1. e4 e5 2. Nf3 Qh4 3. d3 Qxf2+ 4. Kxf2 *"
    reports = _analyze(pgn)
    text = build_summary(_meta(pgn, color="black", outcome="loss"), reports)
    assert "I played: Black (1034)" in text
    assert "Move 2... Qh4 – Blunder" in text
    # Black's blunder: my evaluation goes from about equal to clearly negative
    block = text[text.index("Move 2... Qh4"):]
    before, after = _evals_from_summary(block)[0]
    assert float(after) < -3 and float(after) < float(before)
    win = re.search(r"Win% \(me\): (\d+) -> (\d+)", block)
    assert int(win.group(2)) < int(win.group(1))


@needs_engine
@pytest.mark.parametrize("pgn,result_code,outcome", [
    ("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0", "checkmated", "win"),  # mate
    ("1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 "
     "8. Qxb8 Qh7 9. Qxc8 Kg6 10. Qe6 1/2-1/2", "stalemate", "draw"),  # stalemate
    ("1. e4 *", "abandoned", "win"),  # very short
    ("*", "abandoned", "draw"),  # no moves at all
    ("1. d4 d5 2. c4 e6 3. Nc3 Nf6 0-1", "timeout", "loss"),  # timeout, no clocks
    ("1. e4 e5 2. Nf3 Nc6 1-0", "resigned", "win"),  # resignation
])
def test_summary_edge_games(pgn, result_code, outcome):
    reports = _analyze(pgn)
    text = build_summary(_meta(pgn, result_code=result_code, outcome=outcome), reports)
    assert text.splitlines()[0] == HEADER
    assert text.splitlines()[-1] == FINAL_INSTRUCTION
    assert "== My critical moments" in text
    assert "== Opponent's mistakes I did not punish" in text


@needs_engine
def test_summary_mate_in_lines_and_eval():
    pgn = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"
    reports = _analyze(pgn)
    text = build_summary(_meta(pgn, color="black", outcome="loss", result_code="checkmated"), reports)
    assert "Move 3... Nf6 – Blunder" in text
    assert "Tactic: Allowed mate in 1" in text
    assert "Line after played: 4. Qxf7#" in text
    assert "-> -M1" in text  # from my (Black's) point of view: I get mated


@needs_engine
def test_summary_with_clock_tags():
    pgn = ('[TimeControl "60"]\n\n1. e4 {[%clk 0:00:59]} e5 {[%clk 0:00:58]} '
           '2. Nf3 {[%clk 0:00:50]} Qh4 {[%clk 0:00:20]} 3. d3 {[%clk 0:00:45]} '
           'Qxf2+ {[%clk 0:00:19]} 4. Kxf2 {[%clk 0:00:44]} *')
    reports = _analyze(pgn)
    text = build_summary(_meta(pgn, tc="60", color="black", outcome="loss"), reports)
    block = text[text.index("Move 2... Qh4"):]
    clock = next(line for line in block.splitlines() if line.startswith("Clock:"))
    assert clock == "Clock: me 0:58 left before the move, spent 0:38 | opponent 0:50"
    # 30 s or less before the move = time pressure (base 60 s)
    assert clock_at(5, clocks_from_pgn(pgn), parse_time_control("60")).pressure
