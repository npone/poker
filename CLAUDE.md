# poker

A headless **No-Limit Texas Hold'em** engine in Python plus an interactive terminal CLI, and a
separate legacy ASCII card-art / hand-classifier codebase that predates it. Everything lives in
`src/`. The modern engine (`engine.py`) is stdlib-only; the legacy half needs numpy.

**Repo:** `git@github.com:npone/poker.git` (branch `master`)
**Last updated:** 2026-10-17

No network, no cloud, no credentials — nothing here costs money or touches anything outside the
repo.

---

## Environment

- Interpreter: the shared conda **base** env, Python 3.13 — `/home/nliu/miniconda3/bin/python`.
  **There is no project `.venv`** and none is needed.
- Not a packaged project: no `pyproject.toml`, no `setup.py`, nothing to install. Modules are
  imported by bare name (`import engine`), so **the import path is `src/`**.
- Deps: `engine.py` / `play.py` / `poker.py` / `test_engine.py` / `test_play.py` are **pure
  stdlib**. `pokerClass.py`, `display.py`, `demo_ascii.py`, `test.py`, `test_evaluator.py`
  import **numpy** (2.4.6, present in the shared env).
- Shared-env policy and the env lock: `/home/nliu/dev/devenv/python-env/`.

---

## Layout

Two generations of code share `src/`. Treat them as separate codebases; they share no types.

| File | Lines | What it is |
|------|------:|-----------|
| `engine.py` | 473 | **The engine (current).** `Card`, `Deck`, `evaluate5`/`evaluate`/`hand_name`, `Player`, `HoldemGame` (betting rounds, side pots, showdown, multi-hand), built-in bot policies |
| `play.py` | 182 | **Interactive CLI** (argparse) — you + bots in the terminal |
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

## Commands (verified 2026-10-17)

```bash
cd /home/nliu/dev/poker/src

# Tests — 27 passed in ~1.9s  ✅
python -m pytest -q
python -m pytest test_engine.py test_evaluator.py test_play.py -q   # README form, same 27
# (also passes when run from the repo root: 27 passed)

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

Breakdown of the 27: **19** in `test_engine.py`, **4** in `test_evaluator.py`, **4** in
`test_play.py`. No failures, no skips. `test.py` contributes 0 collected tests (it just prints
ASCII cards at import).

**Lint:** no config, no CI, not a project gate. `ruff check .` (ruff 0.15.16 defaults) reports
**41 pre-existing errors** — 27 `E701` + 8 `E702` (the deliberate one-line `if x: return` and
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
- **There is no solver and no equity/Monte-Carlo module.** The only "math" is the exact hand
  evaluator in `engine.py` (and the legacy classifier in `pokerClass.py`). `play.py`'s bot uses
  a crude pot-odds heuristic (`to_call / (pot + to_call)`) plus a random per-bot `aggression`
  multiplier — it is not a solver and makes no claim to be one. `demo_ascii.py`'s comment
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
- `.gitignore` only covers `__pycache__/` and `*.pyc`. `src/.pytest_cache/` is in the tree but
  carries its own `.gitignore` (`*`), so it stays out of `git status`.

---

## Current state (as of 2026-10-17)

- Branch `master` @ `e837a99`, in sync with `origin/master` — nothing staged, unstaged, or
  unpushed. The only untracked file is **this `CLAUDE.md`** (added 2026-10-17, not yet committed).
- History (newest first):
  - `e837a99` / `af3d9b8` (2026-08-24) — PR #2 `cli-play`: "Add interactive CLI to play against
    the bots (play.py) + engine narration hooks". **This is the CLI entry point:
    `python src/play.py`** (argparse; no console_script, since the repo isn't packaged).
  - `e7fe910` / `7a25542` / `9441b5d` (2026-08-24) — PR #1 `fix-evaluator-bugs`: complete
    headless engine + regression tests, and the legacy evaluator fixes
  - `b410e14` — set Jekyll theme; `b262a3b` — first commit (legacy ASCII code)
- Test suite green: **27 passed**.
- `README.md` is accurate about layout and commands, with one stale claim: it says
  "Pure standard library — no dependencies", but the legacy half (`pokerClass.py`,
  `display.py`, `demo_ascii.py`, `test.py`, `test_evaluator.py`) imports numpy. Only the
  engine/CLI/demo path is dependency-free.
