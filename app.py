"""Chess-mate: quick post-game analysis of chess.com games, built for the phone."""

from __future__ import annotations

import html
import io
import json
import os
import threading
from collections import OrderedDict

import altair as alt
import chess
import chess.pgn
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from chesscom import GameMeta, fetch_recent_games
from classify import (CATEGORY_ICON, CATEGORY_LABEL, CATEGORY_ORDER, EVAL_CAP, MISTAKES,
                      MoveReport, classify_moves, count_categories, game_accuracy, is_mistake)
from engine import DEFAULT_BUDGET_S, analyze_positions, find_stockfish, game_positions
from summary import build_summary
from version import VERSION

DEFAULT_USER = os.environ.get("CHESSCOM_USER", "first_div")
MAX_STORED_ANALYSES = 30
CATEGORY_COLOR = {
    "great": "#2e9d4f", "best": "#5cb85c", "excellent": "#7cc47c", "good": "#9ab0a0",
    "inaccuracy": "#f2b705", "mistake": "#f57c00", "blunder": "#e53935",
}

st.set_page_config(page_title="Chess-mate", page_icon="♟️", layout="centered")

st.markdown(
    """
<style>
.block-container {padding: 3.2rem 0.9rem 3rem; max-width: 640px;}
[data-testid="stCode"] pre, [data-testid="stCode"] code {white-space: pre-wrap; overflow-wrap: anywhere;}
.cm-title {font-size: 1.6rem; font-weight: 700; margin: 0;}
.cm-ver {font-size: .8rem; opacity: .6; margin-left: .4rem;}
.cm-meta {opacity: .85; margin: .2rem 0 .6rem;}
.cm-counts {width: 100%; border-collapse: collapse; margin: .3rem 0 .8rem; font-size: .95rem;}
.cm-counts th, .cm-counts td {padding: .25rem .4rem; text-align: center;
  border-bottom: 1px solid rgba(128,128,128,.25);}
.cm-counts th:first-child, .cm-counts td:first-child {text-align: left;}
.cm-card {border-left: 4px solid var(--c); background: rgba(128,128,128,.08);
  border-radius: 6px; padding: .5rem .7rem; margin: .45rem 0; line-height: 1.5;}
.cm-card small {opacity: .75;}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60, show_spinner="Loading games from chess.com...")
def load_games(username: str) -> list[GameMeta]:
    return fetch_recent_games(username, n=10)


class AnalysisStore:
    """Server-side store of finished analyses, shared by all sessions of this process.

    Survives page reloads (phone browsers often kill background tabs), unlike st.session_state.
    Bounded: the least recently used analysis is dropped beyond MAX_STORED_ANALYSES.
    """

    def __init__(self) -> None:
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > MAX_STORED_ANALYSES:
                self._items.popitem(last=False)


@st.cache_resource
def analysis_store() -> AnalysisStore:
    return AnalysisStore()


def load_error_message(username: str, exc: Exception) -> str:
    """A clear message for a failure to load games from chess.com."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 404:
        return f'chess.com user "{username}" was not found. Check the username in ⚙️ Settings.'
    if status is not None:
        return f"chess.com is not responding properly right now (HTTP {status}). Try again in a minute."
    if isinstance(exc, requests.RequestException):
        return f"Could not reach chess.com ({type(exc).__name__}). Check the internet connection and try again."
    return f"Could not load games from chess.com ({type(exc).__name__}: {exc})."


def game_label(g: GameMeta) -> str:
    # Kept short so it fits a phone screen; the full details are shown below the picker.
    return f"{g.outcome_icon} {g.opponent} · {g.end_dt:%d/%m %H:%M}"


def run_analysis(meta: GameMeta, budget_s: float, engine_path: str) -> dict:
    game = chess.pgn.read_game(io.StringIO(meta.pgn))
    boards, moves = game_positions(game)
    bar = st.progress(0.0, text="Starting analysis...")

    def on_progress(done: int, total: int) -> None:
        bar.progress(done / total, text=f"Analyzing position {done} of {total}")

    try:
        evals = analyze_positions(boards, engine_path, budget_s=budget_s, progress=on_progress)
    finally:
        bar.empty()
    return {
        "reports": classify_moves(boards, moves, evals),
        "evals": [max(-EVAL_CAP, min(EVAL_CAP, e.cp)) for e in evals],
    }


def eval_chart(evals: list[int], reports: list[MoveReport], my_color: chess.Color) -> alt.Chart:
    sign = 1 if my_color == chess.WHITE else -1
    line = pd.DataFrame({
        "move": [i / 2 for i in range(len(evals))],
        "adv": [sign * cp / 100 for cp in evals],
    })
    marks = pd.DataFrame([
        {
            "move": (r.ply + 1) / 2,
            "adv": sign * evals[r.ply + 1] / 100,
            "who": "Me" if r.color == my_color else "Opponent",
            "cat": CATEGORY_LABEL[r.category],
            "label": r.full_label,
            "why": r.explanation or "",
        }
        for r in reports if is_mistake(r.category)
    ])
    stars = pd.DataFrame([
        {"move": (r.ply + 1) / 2, "adv": sign * evals[r.ply + 1] / 100,
         "label": r.full_label, "why": r.explanation or "",
         "who": "Me" if r.color == my_color else "Opponent"}
        for r in reports if r.category == "great"
    ])
    y = alt.Y("adv:Q", title="My advantage (pawns)", scale=alt.Scale(domain=[-10, 10]))
    x = alt.X("move:Q", title="Move")
    base = alt.Chart(line).encode(x=x, y=y)
    layers = [
        base.mark_area(opacity=0.25, color="#4c8bf5"),
        base.mark_line(color="#4c8bf5", strokeWidth=2),
        alt.Chart(pd.DataFrame({"z": [0]})).mark_rule(color="gray", opacity=0.5).encode(y="z:Q"),
    ]
    if not stars.empty:
        # Vega has no star symbol, so great moves are drawn as a text glyph
        layers.append(alt.Chart(stars).mark_text(text="★", size=20, color=CATEGORY_COLOR["great"]).encode(
            x=x, y=y,
            tooltip=[alt.Tooltip("label:N", title="Move"), alt.Tooltip("who:N", title="By"),
                     alt.Tooltip("why:N", title="Why")],
        ))
    if not marks.empty:
        cats = [CATEGORY_LABEL[c] for c in MISTAKES]
        layers.append(alt.Chart(marks).mark_point(filled=True, size=70).encode(
            x=x, y=y,
            # No legend (it gets cramped at phone width); a caption below the chart explains the marks.
            color=alt.Color("cat:N", scale=alt.Scale(
                domain=cats, range=[CATEGORY_COLOR[c] for c in MISTAKES]), legend=None),
            shape=alt.Shape("who:N", scale=alt.Scale(
                domain=["Me", "Opponent"], range=["circle", "triangle"]), legend=None),
            tooltip=[alt.Tooltip("label:N", title="Move"), alt.Tooltip("cat:N", title="Type"),
                     alt.Tooltip("why:N", title="Why")],
        ))
    return alt.layer(*layers).properties(height=230)


def counts_table(reports: list[MoveReport], my_color: chess.Color) -> str:
    mine = count_categories(reports, my_color)
    theirs = count_categories(reports, not my_color)
    rows = "".join(
        f"<tr><td>{CATEGORY_ICON[c]} {CATEGORY_LABEL[c]}</td><td>{mine[c]}</td><td>{theirs[c]}</td></tr>"
        for c in CATEGORY_ORDER
    )
    return f'<table class="cm-counts"><tr><th></th><th>Me</th><th>Opponent</th></tr>{rows}</table>'


def move_cards(reports: list[MoveReport]) -> str:
    cards = []
    for r in reports:
        if is_mistake(r.category):
            best = f"Best: {html.escape(r.best_san)} · " if r.best_san else ""
            footer = f"<br><small>{best}Win% −{r.win_drop:.0f}</small>"
            text = r.explanation or "No tactic detected"
        else:
            footer = ""
            text = r.explanation or ""
        cards.append(
            f'<div class="cm-card" style="--c:{CATEGORY_COLOR[r.category]}">'
            f"<b>{CATEGORY_ICON[r.category]} {CATEGORY_LABEL[r.category]}</b> · {html.escape(r.full_label)}<br>"
            f"{html.escape(text)}{footer}</div>"
        )
    return "".join(cards)


def copy_button(text: str) -> None:
    """A "Copy summary" button (st.code's own copy icon is small on a phone).
    Runs in a component iframe. execCommand("copy") goes first because it reports success
    synchronously; the Clipboard API is the fallback (its promise was seen to stay pending
    in some browsers even after the text was copied)."""
    components.html(
        f"""
<button id="b" style="width:100%;padding:.6rem;font-size:1rem;border-radius:.5rem;
  border:1px solid rgba(128,128,128,.4);background:#4c8bf5;color:#fff;cursor:pointer;
  font-family:sans-serif">📋 Copy summary</button>
<script>
const text = {json.dumps(text)};
const b = document.getElementById("b");
function done(ok) {{
  b.textContent = ok ? "✅ Copied" : "Copy failed: use the icon on the box below";
  setTimeout(() => b.textContent = "📋 Copy summary", 2500);
}}
function execCopy() {{
  const t = document.createElement("textarea");
  t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
  document.body.appendChild(t); t.select(); t.setSelectionRange(0, text.length);
  let ok = false;
  try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  t.remove(); return ok;
}}
b.addEventListener("click", () => {{
  if (execCopy()) {{ done(true); return; }}
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
  }} else {{ done(false); }}
}});
</script>""",
        height=52,
    )


# ---------- UI ----------

st.markdown(f'<p class="cm-title">♟️ Chess-mate<span class="cm-ver">v{VERSION}</span></p>',
            unsafe_allow_html=True)

with st.expander("⚙️ Settings"):
    username = st.text_input("chess.com username", value=DEFAULT_USER).strip()
    budget = st.slider("Approximate analysis time (seconds)", 15, 60, int(DEFAULT_BUDGET_S), step=5)
    if st.button("🔄 Refresh game list"):
        load_games.clear()

engine_path = find_stockfish()
if not engine_path:
    st.error("Stockfish not found. Set STOCKFISH_PATH or install it (in the cloud: packages.txt).")
    st.stop()

try:
    games = load_games(username)
except Exception as exc:  # noqa: BLE001 - show any network/API failure to the user
    st.error(load_error_message(username, exc))
    if st.button("🔁 Try again"):
        load_games.clear()
    st.stop()

if not games:
    st.info("No games found in recent months.")
    st.stop()

idx = st.selectbox("Choose a game", range(len(games)), format_func=lambda i: game_label(games[i]))
meta = games[idx]
my_color = chess.WHITE if meta.my_color == "white" else chess.BLACK

store = analysis_store()
key = (meta.url, budget, VERSION)
result = store.get(key)
if result is None:
    try:
        result = run_analysis(meta, budget, engine_path)
    except Exception as exc:  # noqa: BLE001 - engine crash / timeout; Streamlit's rerun/stop are BaseException
        st.error(f"The analysis failed ({type(exc).__name__}: {exc}). "
                 "The engine may have crashed or run out of resources.")
        st.button("🔁 Try again")  # clicking reruns the script, which retries the analysis
        st.stop()
    store.put(key, result)
reports: list[MoveReport] = result["reports"]

color_name = "White" if my_color == chess.WHITE else "Black"
st.markdown(
    f'<p class="cm-meta">{meta.outcome_label} · {meta.format_label} · You played {color_name}'
    f' · Rating: opponent {meta.opponent_rating or "?"}, you {meta.my_rating or "?"}'
    f' · <a href="{html.escape(meta.url)}">Open on chess.com</a></p>',
    unsafe_allow_html=True,
)
acc_me, acc_opp = game_accuracy(reports, my_color), game_accuracy(reports, not my_color)
if acc_me is not None or acc_opp is not None:
    def _acc(a: float | None) -> str:
        return f"{a:.1f}%" if a is not None else "n/a"
    st.markdown(f'<p class="cm-meta">Accuracy: you {_acc(acc_me)} · opponent {_acc(acc_opp)}</p>',
                unsafe_allow_html=True)
st.markdown(counts_table(reports, my_color), unsafe_allow_html=True)
st.altair_chart(eval_chart(result["evals"], reports, my_color), width="stretch")
st.caption("Up = your advantage · ● me ▲ opponent · 🟡 inaccuracy 🟠 mistake 🔴 blunder · ★ great move")

mine = [r for r in reports if is_mistake(r.category) and r.color == my_color]
theirs = [r for r in reports if is_mistake(r.category) and r.color != my_color]
highlights = [r for r in reports if r.category == "great" and r.color == my_color]
tab_me, tab_opp, tab_hi = st.tabs([
    f"My mistakes ({len(mine)})", f"Opponent's ({len(theirs)})", f"🌟 Highlights ({len(highlights)})",
])
with tab_me:
    st.markdown(move_cards(mine) or "No significant mistakes 🎉", unsafe_allow_html=True)
with tab_opp:
    st.markdown(move_cards(theirs) or "No significant mistakes", unsafe_allow_html=True)
with tab_hi:
    st.markdown(move_cards(highlights) or "No only-moves found in this game.", unsafe_allow_html=True)

st.markdown("### 📋 Copy summary")
st.caption("Copy the summary and paste it into a chat with Claude "
           "(the button, or the copy icon in the corner of the box).")
summary_text = build_summary(meta, reports)
copy_button(summary_text)
st.code(summary_text, language=None, wrap_lines=True)

st.caption(f"Chess-mate v{VERSION} · Stockfish analysis · data from the public chess.com API")
