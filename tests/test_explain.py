"""Tactic explanations, tested on hand-built positions (no engine needed)."""

import chess

from engine import PositionEval
from explain import _allowed_tactic, _fork_targets


def _reply(*ucis: str) -> PositionEval:
    """An evaluation whose principal variation (the opponent's best reply) is given."""
    return PositionEval(fen="", cp=0, mate=None, best_move=ucis[0], pv=ucis, depth=0)


def test_hanging_piece():
    board = chess.Board("3qk3/8/8/8/8/5N2/8/4K3 w - - 0 1")
    text = _allowed_tactic(board, chess.Move.from_uci("f3d4"), _reply("d8d4"))
    assert text == "Left your knight on d4 undefended"


def test_piece_taken_by_cheaper_piece():
    board = chess.Board("4k3/8/3p4/8/3P4/5N2/8/4K3 w - - 0 1")
    text = _allowed_tactic(board, chess.Move.from_uci("f3e5"), _reply("d6e5"))
    assert text == "Your knight on e5 could be taken by a pawn"


def test_allowed_fork():
    board = chess.Board("4k3/8/8/8/3n4/2Q5/8/7K w - - 0 1")
    text = _allowed_tactic(board, chess.Move.from_uci("h1g1"), _reply("d4e2"))
    assert text == "Allowed a fork: knight on e2 attacks your king on g1 and queen on c3"


def test_allowed_pin():
    board = chess.Board("4kb2/8/8/8/8/2N5/3P4/4K3 w - - 0 1")
    text = _allowed_tactic(board, chess.Move.from_uci("d2d3"), _reply("f8b4"))
    assert text == "Allowed a pin: your knight on c3 is pinned to your king"


def test_fork_targets_ignore_defended_equal_pieces():
    # Knight on e5 attacks a knight defended by the b7 pawn (equal value: not a target)
    # and a rook (worth more than the knight: a target even though the king defends it)
    board = chess.Board("4k3/1p1r4/2n5/4N3/8/8/8/4K3 w - - 0 1")
    targets = _fork_targets(board, chess.E5)
    assert targets == [(chess.ROOK, chess.D7)]
