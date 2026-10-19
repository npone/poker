"""Hand-strength math shared by the bots and the odds helper: Monte Carlo equity, outs, pot odds.

`fast_eval` scores 5-7 cards with the same comparable tuples as `engine.evaluate` (a test pins
them equal) but counts ranks directly instead of trying all 21 five-card combinations, so a
few hundred simulated showdowns fit in a bot's turn.
"""
from __future__ import annotations

import random

import engine as e

_DECK = e.make_deck()


def _straight_high(present: set[int]) -> int | None:
    for high in range(14, 4, -1):
        if all((high - o) in present for o in range(5)):
            return high
    return 5 if {14, 2, 3, 4, 5} <= present else None


def fast_eval(cs) -> tuple:
    """Best hand in `cs` (5-7 engine Cards) as engine.evaluate would score it. Fewer cards
    (a bare board, for outs) still get the right category."""
    cnt: dict[int, int] = {}
    by_suit: dict[int, list[int]] = {}
    for c in cs:
        cnt[c.rank] = cnt.get(c.rank, 0) + 1
        by_suit.setdefault(c.suit, []).append(c.rank)
    flush = None
    for rs in by_suit.values():
        if len(rs) >= 5:
            sh = _straight_high(set(rs))
            if sh:
                return (8, (sh,))
            flush = (5, tuple(sorted(rs, reverse=True)[:5]))
    ranks = sorted(cnt, reverse=True)
    quads = [r for r in ranks if cnt[r] == 4]
    trips = [r for r in ranks if cnt[r] == 3]
    pairs = [r for r in ranks if cnt[r] == 2]
    if quads:
        return (7, (quads[0], max((r for r in ranks if r != quads[0]), default=0)))
    if trips and (len(trips) > 1 or pairs):
        return (6, (trips[0], max(trips[1:] + pairs)))
    if flush:
        return flush
    sh = _straight_high(set(ranks))
    if sh:
        return (4, (sh,))
    if trips:
        return (3, (trips[0],) + tuple(r for r in ranks if r != trips[0])[:2])
    if len(pairs) > 1:
        hi, lo = pairs[0], pairs[1]
        return (2, (hi, lo, max((r for r in ranks if r not in (hi, lo)), default=0)))
    if pairs:
        return (1, (pairs[0],) + tuple(r for r in ranks if r != pairs[0])[:3])
    return (0, tuple(ranks[:5]))


def equity(hole, board, opponents: int, sims: int = 400, rng: random.Random | None = None) -> float:
    """Chance (0-1, ties shared) that `hole` wins at showdown against `opponents` random hands."""
    if opponents < 1:
        return 1.0
    rng = rng or random.Random()
    known = set(hole) | set(board)
    deck = [c for c in _DECK if c not in known]
    need = 5 - len(board)
    draw = need + 2 * opponents
    total = 0.0
    for _ in range(sims):
        d = rng.sample(deck, draw)
        full = list(board) + d[:need]
        mine = fast_eval(list(hole) + full)
        best, ties = True, 0
        for k in range(opponents):
            theirs = fast_eval(d[need + 2 * k: need + 2 * k + 2] + full)
            if theirs > mine:
                best = False
                break
            ties += theirs == mine
        if best:
            total += 1 / (ties + 1)
    return total / sims


def outs(hole, board) -> list[e.Card]:
    """Unseen cards that lift your hand to a better category on the next card (flop/turn only).
    A card that improves the board as much as your hand (pairing the board) doesn't count."""
    if len(board) not in (3, 4):
        return []
    known = set(hole) | set(board)
    now = fast_eval(list(hole) + list(board))[0]
    out = []
    for c in _DECK:
        if c in known:
            continue
        cat = fast_eval(list(hole) + list(board) + [c])[0]
        board_cat = fast_eval(list(board) + [c])[0]
        if cat > now and cat > board_cat:
            out.append(c)
    return out


def pot_odds(to_call: int, pot: int) -> float:
    """Share of the final pot you put in by calling = the equity a call needs to break even."""
    return to_call / (pot + to_call) if to_call else 0.0
