# poker

A **No-Limit Texas Hold'em** game: a headless Python engine, a UI-agnostic session layer, a
JSON HTTP API, a static web client (live at https://poker.npone.dev), an interactive terminal
CLI, and a separate legacy ASCII card-art / hand-classifier codebase that predates it. Python is
in `src/`, the web client in `web/`, deployment in `deploy/`.

**Goal (Ning, 2026-10-18):** a complete poker game. Stage 1 is the web interface; iOS and
Android apps follow **for the same underlying program**. So the layering is the point:
`engine.py` (rules) → `table.py` (session, JSON) → `server.py` (`/api/v1`) → clients. **No game
rule may live in a client**; the mobile apps are thin clients of `/api/v1` (server-authoritative,
decided 2026-10-18 — no on-device engine, no offline play). Stage 1 is you vs bots only.

**Repo:** `git@github.com:npone/poker.git` (branch `master`)
**Last updated:** 2026-10-18

No cloud and no credentials — nothing here costs money. The one thing outside the repo is the
deployed service (`poker.service`, and the `poker.npone.dev` rule in the shared tunnel config).

---

## Environment

- Interpreter: the shared conda **base** env, Python 3.13 — `/home/nliu/miniconda3/bin/python`.
  **There is no project `.venv`** and none is needed.
- Not a packaged project: no `pyproject.toml`, no `setup.py`, nothing to install. Modules are
  imported by bare name (`import engine`), so **the import path is `src/`**.
- Deps: `engine.py` / `table.py` / `bots.py` / `play.py` / `poker.py` and their tests are **pure
  stdlib**; `server.py` / `test_server.py` need **fastapi, uvicorn, httpx** (in the shared env).
  The legacy files (`pokerClass.py`, `display.py`, `demo_ascii.py`, `test.py`, `test_evaluator.py`)
  import **numpy** (2.4.6, present in the shared env).
- Shared-env policy and the env lock: `/home/nliu/dev/devenv/python-env/`.

---

## Layout

Two generations of code share `src/`. Treat them as separate codebases; they share no types.

| File | Lines | What it is |
|------|------:|-----------|
| `engine.py` | 473 | **The engine (current).** `Card`, `Deck`, `evaluate5`/`evaluate`/`hand_name`, `Player`, `HoldemGame` (betting rounds, side pots, showdown, multi-hand), built-in bot policies |
| `table.py` | — | **Session layer** every front end drives: hero (seat 0) vs bots; `deal()`, `act(kind, amount)`, `state()` → JSON snapshot with an `events` log. Hides other players' hole cards except at showdown |
| `server.py` | — | **HTTP API** `/api/v1` (FastAPI) over `table.py`, + serves `web/`. In-memory tables, capped/idle-evicted, per-table lock |
| `bots.py` | — | Equity bots (`make_bot(seed, risk=None)`, `BOT_NAMES`, `SIMS`), shared by CLI and server; `play.py` re-exports it. Each bot gets a random risk tolerance 0–1 (`policy.risk`). **Never expose it in `state`** — Ning: the player must not see bot styles |
| `odds.py` | — | `fast_eval` (same tuples as `engine.evaluate`, ~10 µs), `equity` (Monte Carlo vs random hands), `outs`, `pot_odds` |
| `conftest.py` | — | Sets `bots.SIMS = 20` so the suite stays fast; production uses 250 |
| `play.py` | — | **Interactive CLI** (argparse) — you + bots in the terminal |
| `test_table.py` / `test_server.py` | — | Session fuzz (chips conserved, cards hidden, games end, JSON-able) / HTTP contract |
| `../web/` | — | Static web client (`index.html`, `app.js`, `style.css`), no build step, no framework, **no game rules** |
| `../deploy/` | — | `poker.service` + `install.sh` (service + tunnel route with rollback) |
| `poker.py` | 55 | Headless bot-vs-bot demo; prints each hand |
| `test_engine.py` | 228 | Engine regression suite: evaluator, blinds, raise/reopen, pot building, showdown, fuzz, full-game termination |
| `test_play.py` | 65 | Tests the CLI's human input parser and the bot policy's legality |
| `pokerClass.py` | 316 | **Legacy.** numpy-based `Card`/`Deck`/`Player`/`Table` + `CheckFlush`/`CheckStraight`/`CheckMultiples`/`ScoreHand` classifier |
| `display.py` | 95 | **Legacy.** ASCII card art (`ShowCard`, `ShowCards`, `ShowScore`) |
| `demo_ascii.py` | 28 | **Legacy** demo — deals a table and renders it as ASCII art |
| `test.py` | 16 | **Legacy** scratch script that prints ASCII cards. Not a pytest file despite the name (no `test_*` functions — pytest collects 0 from it) |
| `test_evaluator.py` | 58 | Tests the **legacy** `pokerClass.ScoreHand` classifier |
| `_config.yml` | — | GitHub Pages theme (`jekyll-theme-merlot`); unrelated to the code |

---

## Commands (verified 2026-10-18)

```bash
cd /home/nliu/dev/poker/src

# Tests — 51 passed in ~9s  ✅  (also the .taskhub.json `test` command)
python -m pytest -q

# Web game locally
python -m uvicorn server:app --host 127.0.0.1 --port 8094   # http://127.0.0.1:8094/

# Interactive CLI  ✅ --help verified
python play.py
python play.py --players 6 --stack 200
#   flags: --players (2-8, incl. you)  --stack  --sb  --bb  --seed
#   turn keys: k=check  c=call  f=fold  b/r <N>=bet/raise to N  a=all-in  q=quit

# Headless demos  ✅ both produce output
python poker.py        # bot-vs-bot game, prints board/pots/stacks per hand
python demo_ascii.py   # legacy: ASCII-rendered deal + score (needs numpy)
python test.py         # legacy scratch: prints ASCII cards only
```

Breakdown of the 51: **21** in `test_engine.py`, **9** in `test_server.py`, **8** in
`test_table.py`, **5** in `test_odds.py`, **4** each in `test_evaluator.py` and `test_play.py`. No failures, no skips. `test.py` contributes 0 collected tests (it just prints
ASCII cards at import).

**Lint:** no config, no CI, not a project gate. `ruff check .` (ruff 0.15.16 defaults) reports
**46 errors** — 27 `E701` + 13 `E702` (the deliberate one-line `if x: return` and
`a; assert b` style used throughout `engine.py` and the tests), 3 `F841`, 2 `F401`, 1 `E722`.
These are stylistic and intentional; don't mass-fix them.

**Typecheck / build:** none. `mypy` is not installed.

---

## Engine API

Policy-driven: a policy is `callable(view) -> action`.

```python
import engine as e

g = e.HoldemGame([100, 100, 100], sb=1, bb=2, button=0, rng=None)
g.on_action = fn   # optional narration hook: (player, action, chips_put)
g.on_street = fn   # optional narration hook: (street_name, board)

result = g.play_hand([e.calling_station, e.calling_station, e.fold_to_bet])
g.play(policies, hands=None)   # until one player holds all the chips
g.advance_button()

h = g.hand(order=None)         # step form: generator; next(h) -> view, h.send(action) -> view,
                               # StopIteration.value = the play_hand result. play_hand drives it.
```

`action` is one of `('fold',)`, `('check',)`, `('call',)`, `('raise', total)`, `('allin',)`,
where `total` is the player's **total wagered on the current street after the raise** (not the
increment). Built-in policies: `fold_to_bet`, `calling_station`, `always_allin`,
`scripted(actions)`.

`view` keys: `seat`, `street`, `hole`, `board`, `pot`, `current_bet`, `to_call`, `can_check`,
`can_raise`, `min_raise_to`, `allin_to`, `my_stack`, `my_street_bet`, `num_active`, `stacks`,
`contrib`, `folded`.

`play_hand()` returns: `board`, `pots`, `stacks`, `stacks_before`, `folded`, `holes`, `button`.

Evaluator: `e.evaluate(e.cards("Ah Kh Qh Jh Th 2c 3d"))` → a comparable
`(category, tiebreakers…)` tuple (bigger = stronger, so `>` / `max()` / `==` work directly);
`e.hand_name(score)` → `'Royal Flush'`. `evaluate` picks the best 5 of 5–7 cards via
`itertools.combinations`; `evaluate5` scores exactly five.

---

## Conventions & gotchas

- **Run from `src/`.** Imports are flat module names; `cd src` first (pytest also works from the
  repo root because it prepends the test file's directory).
- **There is no solver.** `odds.py` estimates equity by Monte Carlo against *random* hands; the
  bots discount it when facing a bet and weigh it against pot odds and stack at risk, scaled by
  their risk tolerance. Not game-theory optimal, and it makes no claim to be. `odds.fast_eval`
  must stay equal to `engine.evaluate` (`test_odds.py` pins it); the engine's evaluator remains
  the one that decides showdowns. `demo_ascii.py`'s comment
  "a test program for calculating chances in poker games" is aspirational; it computes no
  chances.
- `engine.py` and `pokerClass.py` **both define a `Card` class** and they are incompatible.
  `engine`'s is `(rank, suit)` ints with `Card.parse("Ah")`; the legacy one is numpy-array based.
  Never mix them.
- The engine is deliberately **defensive**: `_coerce()` forces any policy output into a legal
  action rather than raising, so a buggy policy silently folds/checks instead of erroring. When
  debugging a policy, assert on the action yourself.
- `play_hand(policies, order=...)` accepts a stacked deck order — that's how `test_engine.py`
  pins deterministic hands (`_deck_for`). Use it instead of seeding RNG when you need an exact
  board.
- Rules actually implemented: blinds, heads-up button-is-SB, min-raise sizing, raise reopens
  action, all-in **side pots** with dead money from folded players excluded from eligibility,
  split pots with the **odd chip going left of the button**, Ace-high (Broadway) and Ace-low
  (wheel) straights, full kicker resolution.
- `test_engine.py::test_fuzz_invariants` plays hundreds of random 2–6-player hands asserting
  chip conservation, non-negative stacks, exact pot accounting, and that the awarded winner
  truly holds the best hand. **If you change betting or pot logic, that test is the gate.**
- Legacy evaluator bugs already fixed in `9441b5d` — do not reintroduce: Ace-high straights,
  clubs flush detection, royal flush, false straight-flush positives.
- `test.py` is not a test module; don't "fix" it into one.
- `_settle` refunds the top contributor's **uncalled** excess before building pots, and a betting
  round ends when the only player able to bet owes nothing (fixed 2026-10-18: a heads-up SB
  all-in for less than the BB used to give the BB an option, and folding it crashed `_settle`).
- A **short all-in does not reopen betting**: `_legal(p, acted)` gives a seat that already acted
  `can_raise False`, and `_coerce` turns its `allin` into a call. (Before 2026-10-18 this was a
  documented simplification; the review of PR #3 found the UI and bots could raise there.)
- `table.py` voids a hand (refunds every contribution) if a bot or the engine raises, so a bug
  cannot wedge a table. `server.py` limits: 2000 live tables (then 503, never evicting a table
  used in the last 2 h), 20 new tables per client IP per 10 min (`CF-Connecting-IP`), and a
  422 handler that never echoes input (the default one 500s on NaN/Infinity).
- Browser check: Playwright does not support Ubuntu 20.04, so run it from the
  `mcr.microsoft.com/playwright/python:v1.55.0-noble` image with `--network host`.
- Cloudflare's edge caches static files (4 h). `server.py` sends `Cache-Control: no-cache` on
  every non-API path so new deploys revalidate; `index.html` also carries `?v=N` on `app.js` /
  `style.css` — bump it if a deploy ever still shows old assets.
- **Deployed from this checkout.** `poker.service` runs `src/` in place, so whatever is checked
  out is what restarts. Keep `master` checked out here; `sudo systemctl restart poker` after a
  merge. A restart drops every in-progress table (memory only).
- `.gitignore` only covers `__pycache__/` and `*.pyc`. `src/.pytest_cache/` is in the tree but
  carries its own `.gitignore` (`*`), so it stays out of `git status`.

---

## Current state (as of 2026-10-18)

- Stage 1 (web, you vs bots) built on branch `web-game`: step-by-step engine (`hand()`), the
  uncalled-chip fix, `table.py`, `server.py`, `web/`, `deploy/`, `.taskhub.json`. 41 tests pass.
  Verified in headless Chromium: desktop, phone 390 px (no horizontal scroll), dark mode, reload
  resumes the table, no console errors. Shipped (PR #3).
- Smoother play (Ning, 2026-10-18), branch `smoother-play`: hands auto-deal 4 s after a winner
  overlay (Hold / Deal now); chips fly to bets, pot and winners; cards deal, flip and muck;
  textured buttons and table; equity bots with a random risk tolerance; an optional odds helper
  (header toggle or `O`) fed by `GET /api/v1/tables/{id}/odds`. Animations are WAAPI on
  persistent seat elements (`buildSeats` once, `updateSeats` per event), not DOM rebuilds.
  Follow-ups the same day: a "Next hand" setting (2/4/7/12 s or manual, per-viewer
  localStorage `poker.next`); each seat's last move stays up until the street ends, newest in
  gold; bot styles hidden; a fixed side column (odds helper + hand log) so toggling the odds
  helper never moves the table.
  Then: synthesized sound effects (Web Audio, no files; `sfx` in `app.js`; Sound toggle or `M`, volume slider `poker.volume`,
  per-viewer `poker.sound`) for cards, chips, checks and the winner; a styled title with the
  npone wordmark linking back to https://npone.dev, as every npone.dev page has (Ning).
  Hand history replay: `Table.history` keeps the last 50 finished hands as the hero saw them
  (`hands()`, `hand_record(n)`, `GET …/hands[/{n}]`); the web `<dialog>` steps through one by
  folding its events (H key, or "Replay this hand" on the end-of-hand overlay); auto-deal
  waits while it is open.
- Not yet: iOS/Android apps (no Xcode/Android SDK on dev176), multiplayer, accounts/persistence
  (tables are lost on restart), ruff cleanup (46 stylistic findings; leave them).
- `README.md` still claims nothing beyond what is true; it documents the API and deploy.
