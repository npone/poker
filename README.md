# poker

A **No-Limit Texas Hold'em** game: a headless Python engine, a JSON API over it, and a web
client — play against bots at https://poker.npone.dev. The engine is pure standard library; the
server needs FastAPI + uvicorn; the legacy ASCII half needs numpy.

Layers, each usable without the ones above it:

    engine.py   rules: deal, betting, side pots, showdown        (no UI, no I/O)
    table.py    a session: you vs bots, JSON snapshots + events   (no UI, no I/O)
    server.py   HTTP JSON API /api/v1 over table.py               (the contract for every client)
    web/        static web client                                  (no game rules)

The iOS and Android apps will be further clients of the same `/api/v1`.

## Layout (`src/`)

| File | What it is |
|------|-----------|
| `engine.py` | **The backend engine.** Cards/Deck, a correct hand evaluator (with kickers), betting rounds, side pots, showdown, and multi-hand play. |
| `table.py` | **Game session** for any front end: hero (seat 0) vs bots, `deal()` / `act()` / `state()` returning JSON snapshots with an event log. |
| `server.py` | **HTTP API** (`/api/v1`, FastAPI) over `table.py`; also serves `web/`. |
| `bots.py` | Equity bots shared by the CLI and the server: Monte Carlo win chance vs pot odds and stack at risk, with a random per-bot risk tolerance, kept hidden from the player. |
| `odds.py` | Hand-strength math: fast 7-card evaluator (pinned equal to the engine's), Monte Carlo equity, outs, pot odds. Used by the bots and the odds endpoint. |
| `test_odds.py` | Evaluator equivalence, known equities, outs, risk tolerance changing play, the odds endpoint. |
| `test_table.py`, `test_server.py` | Session fuzz (chips, hidden cards, termination) and the HTTP contract. |
| `test_engine.py` | Regression suite for the engine (evaluator, betting, side pots, showdown, integration, and a randomized fuzz). |
| `play.py` | **Interactive CLI** — play against the bots in your terminal. |
| `poker.py` | Headless demo — plays a short game and prints each hand. |
| `pokerClass.py`, `display.py` | Original hand classifier + ASCII card art. |
| `demo_ascii.py`, `test_evaluator.py` | Legacy ASCII deal demo + tests for the original classifier. |

## Run

```bash
cd src
python play.py                          # play against the bots (you + 3 bots)
python play.py --players 6 --stack 200  # options: --players --stack --sb --bb --seed
python poker.py                         # watch a bot-vs-bot demo game
python -m pytest -q                     # all tests
uvicorn server:app --port 8094          # web game at http://127.0.0.1:8094/
```

## HTTP API (`/api/v1`)

| | |
|---|---|
| `POST /api/v1/tables` `{players, stack, sb, bb}` | new table → `{id, state}` |
| `GET /api/v1/tables/{id}` | current `state` |
| `POST /api/v1/tables/{id}/deal` | start the next hand → `state` |
| `POST /api/v1/tables/{id}/act` `{action, amount?}` | `fold` `check` `call` `raise` (`amount` = total street bet) `allin` → `state` |
| `POST /api/v1/session` `{token}` | signed in: your stats, and your table (live, or restored from the last save) → `{account, table?, state?, ranked?}` |
| `POST /api/v1/leaderboard` `{token?}` | top players by ranked chips won, plus your row when signed in |
| `GET /api/v1/tables/{id}/hands` | finished hands kept for replay (last 50): `hand_no`, your `net`, `pot`, `winners`, `showdown` |
| `GET /api/v1/tables/{id}/hands/{n}` | one hand as you saw it: start stacks, your `hole`, the full `events` log (bots' cards only where shown) |
| `GET /api/v1/tables/{id}/odds` | on your turn only: `pot_odds`, `equity` (vs the hands still in), `opponents`, `made`, `outs` — the odds helper's numbers |

`state` is the view from your seat: players (stacks, bets, folded/all-in; other players' hole
cards only when shown at showdown), board, pot, `to_act` (your legal options, or null), the last
`result`, and `events` — everything that happened since the previous response, in order. Errors
are 400 (illegal now), 404 (unknown/expired table), 422 (malformed), 429 (too many new tables
from one client: 20 per 10 min) or 503 (server full). Interactive docs at
`/api/docs`. Tables live in server memory: a restart ends them.

## Accounts, progress and the leaderboard

Guests play without an account. Nothing is saved, and a reload starts a new game. Signed-in
players use their **npone.dev account**. The page fetches a 5-minute token from
`https://npone.dev/auth/token?aud=poker` and sends it with `POST /api/v1/tables` or
`/session`. The server checks it at npone.dev's `/auth/introspect`, which returns an opaque
account id and the profile name; poker never sees an email. For them:

- **Progress is kept.** Their table is saved between hands (`data/poker.db`) and comes back
  after a reload, on another device, or after a server restart, as it stood before any
  unfinished hand.
- **Leaderboard.** Lifetime chips won, hands, sessions, tables won and best pot. Only
  **ranked** settings count: 4 players, 100 chips, blinds 1/2. Other settings are practice (saved, not
  counted). Names are npone.dev profile names, or `Player xxxx` when none is set.
- **No escaping a losing hand.** If you start a new game, or leave mid-hand until the table
  is evicted, the chips you had in the pot count as lost. A hand cut short by a server restart
  is void.

## Deploy ([private-host])

`sudo bash deploy/install.sh` installs `poker.service` (uvicorn on `127.0.0.1:8094`, low
priority) and routes `poker.npone.dev` to it through the existing Cloudflare tunnel, rolling the
tunnel config back if any route stops answering. Take the tunnel lease first (`~/dev/CLAUDE.md`).
The service runs from this checkout: `sudo systemctl restart poker` after merging to `master`.

At your turn: `k`=check  `c`=call  `f`=fold  `b/r <N>`=bet/raise to N  `a`=all-in  `q`=quit.

## Using the engine

The engine is driven by **policies** — a policy is `callable(view) -> action`. `view` is a
read-only snapshot for the acting player; `action` is one of
`('fold',)`, `('check',)`, `('call',)`, `('raise', total)`, `('allin',)`
(`total` = the player's total wagered on the current street after the raise).

```python
import engine as e

g = e.HoldemGame([100, 100, 100], sb=1, bb=2, button=0)
result = g.play_hand([e.calling_station, e.calling_station, e.fold_to_bet])
# result: {'board', 'pots', 'stacks', 'holes', 'folded', 'button', ...}

g.play([my_policy, my_policy, my_policy])   # play hands until one player has all the chips
```

Evaluate any 5–7 cards into a fully comparable score (bigger = stronger, so `>` / `max` work):

```python
e.evaluate(e.cards("Ah Kh Qh Jh Th 2c 3d"))   # best 5 of 7
e.hand_name(_)                                  # 'Royal Flush'
```

## Correctness

Standard NLHE rules: blinds, min-raise sizing, a short all-in does not reopen betting,
uncalled chips are returned, all-in **side pots**, split pots with the odd
chip going left of the button. The evaluator handles kickers, Ace-high (Broadway) and Ace-low
(wheel) straights, and picks the best 5 of 7. The fuzz test plays hundreds of random 2–6-player
hands asserting chip conservation, non-negative stacks, exact pot accounting, and that the
awarded winner truly holds the best hand.
