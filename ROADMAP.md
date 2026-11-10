# Chess-mate – ROADMAP

Source of truth for versions. The current version number is set in `version.py` and shown on screen.

## Versions

### v0.1 – Basic analysis (done)
- [x] Fetch the 10 most recent games from the public chess.com API (latest month, earlier months if needed), with a User-Agent
- [x] Game picker (default: latest): opponent, result, date, format
- [x] Stockfish analysis via python-chess, time budget of ~30 s (adjustable 15–60), with a progress bar
- [x] Advantage chart over the game, with mistakes marked
- [x] Inaccuracy / mistake / blunder classification by centipawn loss (50/100/200, eval capped at ±10, softened in decided positions), separately for me and the opponent
- [x] Short rule-based explanations: allowed mate, missed mate, lost piece/material, missed free capture, evaluation swing
- [x] "Copy summary": 3–5 critical moments (move, FEN, move played, best move, eval, explanation)
- [x] Phone layout: narrow screen

### v0.2 – English (done)
- [x] All UI, explanations, copy summary, code comments and docs in English (LTR layout)

### v0.3 – Good moves (done)
- [x] Every move gets a category: Great (only move) / Best / Excellent (loss ≤ 10) / Good (loss 11–49) / Inaccuracy / Mistake / Blunder
- [x] Great = played the engine's best move, the second-best was ≥ 150 cp worse, position not already decided (±5); recaptures and captures punishing an opponent's mistake are excluded
- [x] Engine runs MultiPV=2 for the second-best line (same time budget, ~1–2 plies less depth)
- [x] Counts table for all 7 categories (me / opponent), "Highlights" tab with my great moves, ★ on the chart
- [x] Copy summary includes up to 2 of my great moves

### v0.4 – Fixes and analysis quality (done)
- [x] Game times shown in local time (Asia/Jerusalem by default, `APP_TIMEZONE` to override)
- [x] Finished analyses kept server-side (up to 30), so a page reload does not re-run the engine
- [x] Engine crash / failure shows a clear message and a "Try again" button
- [x] Deterministic analysis: 1 thread + fixed node count per position, calibrated once per server process from the measured engine speed and rounded to fixed steps (same game → same result on the same server)
- [x] New explanations: piece left undefended, piece taken by a cheaper piece, allowed fork, allowed pin, missed fork
- [x] No inaccuracies flagged in the first 8 moves (no opening book); mistakes and blunders still are
- [x] "Only move" wording when every alternative allows mate

### v0.5 – Rename (current)
- [x] App renamed to "Chess-mate" (title, browser tab, footer, User-Agent, docs)

## Planned
(No future versions defined yet. Items move here from the Backlog only after a decision.)

## Backlog (not planned, ideas only)
- Board diagram (SVG) for each critical moment
- "Brilliant" moves (sound sacrifices) and "Book" moves (needs an opening database)
- More explanations: deeper tactics (beyond the opponent's first reply), skewers, discovered attacks, missed forcing moves; positional mistakes still get a generic "lost about X pawns" (~45% of mistakes in a 10-game sample)
- Opening name and where the game left theory
- Accuracy percentage per game
- Filter the game list by format
- Paste a PGN manually (not only from chess.com)
- Analysis history and trends over time
- Clear the previous game's results while a new game is being analyzed (they currently stay on screen, faded)
- Fallback to an external Stockfish API if the local engine is unavailable
