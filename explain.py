"""Short rule-based explanations for mistakes (no LLM)."""

from __future__ import annotations

import chess

from engine import PositionEval

PIECE_VALUE = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}
LINE_PLIES = 6  # how many plies ahead to compare material
MATERIAL_THRESHOLD = 2  # minimum material difference (points) that counts as losing a piece
MIN_LOSS_FOR_MATERIAL = 150  # centipawns; below this we make no claims about material
MIN_LINE_PLIES = 4  # shorter engine lines are not used for material claims


def material(board: chess.Board, color: chess.Color) -> int:
    """Material balance from color's point of view."""
    total = 0
    for piece_type, value in PIECE_VALUE.items():
        total += value * len(board.pieces(piece_type, color))
        total -= value * len(board.pieces(piece_type, not color))
    return total


def play_line(board: chess.Board, ucis: list[str], plies: int):
    """Play up to `plies` moves of a line. Returns the final board and the captured pieces."""
    b = board.copy(stack=False)
    captured: list[tuple[chess.Color, chess.PieceType]] = []
    for uci in ucis[:plies]:
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            break
        if b.is_en_passant(move):
            captured.append((not b.turn, chess.PAWN))
        else:
            victim = b.piece_at(move.to_square)
            if victim:
                captured.append((victim.color, victim.piece_type))
        b.push(move)
    return b, captured


def pov_mate(ev: PositionEval, color: chess.Color) -> int | None:
    """Mate from color's view: positive = color mates, negative = color gets mated."""
    if ev.mate is None:
        return None
    return ev.mate if color == chess.WHITE else -ev.mate


def _even_length(*lines: list[str]) -> int:
    n = min([LINE_PLIES, *(len(line) for line in lines)])
    if n > 1 and n % 2 == 1:
        n -= 1  # stop after the opponent's reply, not in the middle of an exchange
    return n


def _lost_piece_text(piece: chess.PieceType) -> str:
    name = chess.piece_name(piece)
    return "Lost the queen" if piece == chess.QUEEN else f"Lost a {name}"


def explain(
    board: chess.Board,
    move: chess.Move,
    ev_before: PositionEval,
    ev_after: PositionEval,
    loss_cp: int,
    before_cp: int,
    after_cp: int,
) -> str | None:
    """One-line tactical explanation, or None when no rule matches.
    before_cp / after_cp are from the mover's point of view."""
    mover = board.turn
    mate_before = pov_mate(ev_before, mover)
    mate_after = pov_mate(ev_after, mover)

    # 1. Allowed mate
    if mate_after is not None and mate_after < 0 and not (mate_before is not None and mate_before < 0):
        return f"Allowed mate in {abs(mate_after)}"

    # 2. Missed mate
    if mate_before is not None and mate_before > 0 and not (mate_after is not None and mate_after >= 0):
        return f"Missed mate in {mate_before}"

    # 3. Material: compare the engine's best line with the line after the move played
    best_line = list(ev_before.pv)
    played_line = [move.uci(), *ev_after.pv]
    # The engine's PV can be cut short (1–3 plies) and stop in the middle of an exchange:
    # "lost" claims need a played line of MIN_LINE_PLIES, "missed" claims a best line of 2.
    n_played = _even_length(played_line)
    n_best = _even_length(best_line)
    played_ok = n_played >= MIN_LINE_PLIES
    if best_line and (played_ok or n_best >= 2):
        start = material(board, mover)
        best_end, _ = play_line(board, best_line, n_best)
        played_end, played_caps = play_line(board, played_line, n_played)
        best_mat = material(best_end, mover)
        played_mat = material(played_end, mover) if played_ok else start

        # Only talk about material when the evaluation dropped accordingly;
        # otherwise it is just an exchange in the middle of the line.
        if best_mat - played_mat >= MATERIAL_THRESHOLD and loss_cp >= MIN_LOSS_FOR_MATERIAL:
            if played_ok and played_mat - start <= -MATERIAL_THRESHOLD:
                tactic = _allowed_tactic(board, move, ev_after)
                if tactic:
                    return tactic
                unmatched = _unmatched_losses(played_caps, mover)
                pieces = [pt for pt in unmatched if pt != chess.PAWN]
                if len(pieces) == 1:  # a single piece (possibly plus pawns)
                    return _lost_piece_text(pieces[0])
                if unmatched and all(pt == chess.PAWN for pt in unmatched):
                    return "Lost pawns"
                return f"Lost material (~{start - played_mat} points)"

            best_move = chess.Move.from_uci(best_line[0])
            if board.is_capture(best_move) and best_mat - start >= MATERIAL_THRESHOLD:
                if board.is_en_passant(best_move):
                    victim = chess.PAWN
                else:
                    victim = board.piece_type_at(best_move.to_square)
                square = chess.square_name(best_move.to_square)
                return f"Missed a free {chess.piece_name(victim)} on {square}"

            after_best = board.copy(stack=False)
            after_best.push(best_move)
            targets = _fork_targets(after_best, best_move.to_square)
            if len(targets) >= 2:
                forker = chess.piece_name(after_best.piece_type_at(best_move.to_square))
                return (f"Missed a fork: {forker} to {chess.square_name(best_move.to_square)} "
                        f"attacks {_and_list(targets)}")

            return f"Missed a material gain (~{best_mat - played_mat} points)"

    # 4. Nothing recognized: say so rather than guess (the evaluation numbers are shown separately)
    return None


def _and_list(targets: list[tuple[chess.PieceType, chess.Square]]) -> str:
    names = [f"{chess.piece_name(pt)} on {chess.square_name(sq)}" for pt, sq in targets]
    return " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]


def _fork_targets(board: chess.Board, square: chess.Square) -> list[tuple[chess.PieceType, chess.Square]]:
    """Enemy pieces attacked by the piece on `square` that it can profitably win:
    the king, anything worth more than the attacker, or an undefended minor/major piece."""
    attacker = board.piece_at(square)
    if attacker is None:
        return []
    enemy = not attacker.color
    targets = []
    for sq in board.attacks(square):
        victim = board.piece_at(sq)
        if victim is None or victim.color != enemy or victim.piece_type == chess.PAWN:
            continue
        worth_more = PIECE_VALUE[victim.piece_type] > PIECE_VALUE[attacker.piece_type]
        undefended = not board.is_attacked_by(enemy, sq)
        if victim.piece_type == chess.KING or worth_more or undefended:
            targets.append((victim.piece_type, sq))
    return sorted(targets, key=lambda t: -PIECE_VALUE[t[0]] if t[0] != chess.KING else -100)


def _allowed_tactic(board: chess.Board, move: chess.Move, ev_after: PositionEval) -> str | None:
    """Name the tactic behind the opponent's best reply: hanging piece, fork or pin."""
    mover = board.turn
    after = board.copy(stack=False)
    after.push(move)
    if not ev_after.pv:
        return None
    reply = chess.Move.from_uci(ev_after.pv[0])
    if reply not in after.legal_moves:
        return None

    # Hanging piece: the reply simply captures a piece
    if after.is_capture(reply) and not after.is_en_passant(reply):
        victim = after.piece_at(reply.to_square)
        attacker = after.piece_at(reply.from_square)
        if victim and victim.color == mover and victim.piece_type != chess.PAWN:
            name, sq = chess.piece_name(victim.piece_type), chess.square_name(reply.to_square)
            if not after.is_attacked_by(mover, reply.to_square):
                return f"Left your {name} on {sq} undefended"
            if PIECE_VALUE[attacker.piece_type] < PIECE_VALUE[victim.piece_type]:
                return f"Your {name} on {sq} could be taken by a {chess.piece_name(attacker.piece_type)}"

    pinned_before = {sq for sq in chess.SquareSet(after.occupied_co[mover]) if after.is_pinned(mover, sq)}
    after.push(reply)

    # Fork: the replying piece attacks two or more valuable targets
    targets = _fork_targets(after, reply.to_square)
    if len(targets) >= 2:
        forker = chess.piece_name(after.piece_type_at(reply.to_square))
        return (f"Allowed a fork: {forker} on {chess.square_name(reply.to_square)} "
                f"attacks your {_and_list(targets)}")

    # Pin: one of your pieces is newly pinned to your king
    for sq in chess.SquareSet(after.occupied_co[mover]):
        piece_type = after.piece_type_at(sq)
        if (piece_type not in (chess.PAWN, chess.KING) and sq not in pinned_before
                and after.is_pinned(mover, sq)):
            return f"Allowed a pin: your {chess.piece_name(piece_type)} on {chess.square_name(sq)} is pinned to your king"
    return None


def _unmatched_losses(captures: list[tuple[chess.Color, chess.PieceType]],
                      mover: chess.Color) -> list[chess.PieceType]:
    """Mover's pieces captured without compensation of equal or higher value (trades cancel out)."""
    gained = sorted((pt for c, pt in captures if c != mover), key=lambda p: PIECE_VALUE[p])
    lost = sorted((pt for c, pt in captures if c == mover), key=lambda p: -PIECE_VALUE[p])
    unmatched = []
    # Most valuable losses first, each matched with the cheapest capture that is worth as much
    # (so a queen trade cancels out and a lost bishop is not "paid for" by the enemy queen).
    for piece in lost:
        match = next((g for g in gained if PIECE_VALUE[g] >= PIECE_VALUE[piece]), None)
        if match is None:
            unmatched.append(piece)
        else:
            gained.remove(match)
    return unmatched
