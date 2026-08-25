# poker

A headless **No-Limit Texas Hold'em** backend engine in Python (plus the original ASCII card
renderer). Pure standard library — no dependencies.

## Layout (`src/`)

| File | What it is |
|------|-----------|
| `engine.py` | **The backend engine.** Cards/Deck, a correct hand evaluator (with kickers), betting rounds, side pots, showdown, and multi-hand play. |
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
python -m pytest test_engine.py test_evaluator.py test_play.py -q   # all tests
```

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

Standard NLHE rules: blinds, min-raise sizing, all-in **side pots**, split pots with the odd
chip going left of the button. The evaluator handles kickers, Ace-high (Broadway) and Ace-low
(wheel) straights, and picks the best 5 of 7. The fuzz test plays hundreds of random 2–6-player
hands asserting chip conservation, non-negative stacks, exact pot accounting, and that the
awarded winner truly holds the best hand.
