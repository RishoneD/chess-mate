from chesscom import format_time_control, parse_game


def _raw(white="first_div", black="opp", w_res="win", b_res="resigned", rules="chess"):
    return {
        "url": "https://www.chess.com/game/live/1",
        "pgn": "1. e4 e5 *",
        "end_time": 1794300896,
        "time_class": "rapid",
        "time_control": "600",
        "rules": rules,
        "white": {"username": white, "rating": 1034, "result": w_res},
        "black": {"username": black, "rating": 1048, "result": b_res},
    }


def test_time_control():
    assert format_time_control("600") == "10+0"
    assert format_time_control("180+2") == "3+2"
    assert format_time_control("900+10") == "15+10"
    assert format_time_control("1/86400") == "1 day/move"
    assert format_time_control("1/259200") == "3 days/move"


def test_parse_win_as_white():
    g = parse_game(_raw(), "First_Div")
    assert g.my_color == "white"
    assert g.opponent == "opp"
    assert g.outcome == "win"
    assert g.outcome_label == "Win (resignation)"
    assert g.format_label == "Rapid 10+0"


def test_end_time_is_local():
    g = parse_game(_raw(), "first_div")
    # 1794300896 = 2026-11-10 08:54:56 UTC = 10:54:56 in Israel (winter time, UTC+2)
    assert g.end_dt.strftime("%Y-%m-%d %H:%M") == "2026-11-10 10:54"


def test_parse_loss_as_black():
    g = parse_game(_raw(white="opp", black="first_div", w_res="win", b_res="checkmated"), "first_div")
    assert g.my_color == "black"
    assert g.outcome == "loss"
    assert g.outcome_label == "Loss (checkmate)"


def test_parse_draw_and_variants():
    g = parse_game(_raw(w_res="repetition", b_res="repetition"), "first_div")
    assert g.outcome == "draw"
    assert g.outcome_label == "Draw (repetition)"
    assert parse_game(_raw(rules="chess960"), "first_div") is None
    assert parse_game(_raw(white="a", black="b"), "first_div") is None
