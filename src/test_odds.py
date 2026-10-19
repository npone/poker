"""Tests for odds.py (equity math) and the risk-tolerant bots built on it."""
import random

import bots
import engine as e
import odds
from table import Table, TableError


def test_fast_eval_matches_engine():
    rng = random.Random(1)
    deck = e.make_deck()
    for n in (5, 6, 7) * 3000:
        h = rng.sample(deck, n)
        assert odds.fast_eval(h) == e.evaluate(h), h
    for spec in ("Ah 2c 3d 4s 5h Kd Kc", "9h 9c 9d 4s 4h 4d Kc", "Ah Kh Qh Jh Th 9h 8h",
                 "2s 3s 4s 5s As Ks 6d", "7c 7d 7h 7s 2c 3c 4c"):
        h = e.cards(spec)
        assert odds.fast_eval(h) == e.evaluate(h), spec


def test_equity_known_spots():
    rng = random.Random(2)
    assert 0.82 < odds.equity(e.cards("As Ah"), [], 1, 3000, rng) < 0.89     # AA vs 1 ~ 85%
    assert odds.equity(e.cards("As Ah"), e.cards("Ad Ac 2s 7h 9d"), 3, 200, rng) == 1.0
    assert odds.equity(e.cards("2c 3d"), [], 0) == 1.0
    assert odds.pot_odds(10, 30) == 0.25 and odds.pot_odds(0, 30) == 0


def test_outs_flush_draw_and_board_pairs_excluded():
    outs = odds.outs(e.cards("Ah Kh"), e.cards("2h 7h Qc"))
    assert len(outs) == 15                          # 9 hearts + 3 aces + 3 kings
    # turn: a card pairing only the board is not an out for a high-card hand
    outs = odds.outs(e.cards("Ah Kd"), e.cards("2c 7s 9d Jh"))
    assert not any(c.rank in (2, 7, 9, 11) for c in outs)
    assert odds.outs(e.cards("Ah Kd"), []) == []
    # flop 7-7-2: the turn 2 leaves a 4-card two-pair/quads board (no kicker) and once crashed
    assert odds.outs(e.cards("Ah Kd"), e.cards("7c 7d 2s"))
    assert odds.fast_eval(e.cards("7c 7d 7h 7s"))[0] == 7


def test_risk_tolerance_changes_play():
    # a marginal spot: K7 offsuit facing a pot-sized bet heads-up preflop
    view = dict(seat=1, street="preflop", hole=e.cards("Kd 7c"), board=[], pot=30, current_bet=20,
                to_call=10, can_check=False, can_raise=True, min_raise_to=30, allin_to=100,
                my_stack=90, my_street_bet=10, num_active=2, stacks=[80, 90], contrib=[20, 10],
                folded=[False, False])
    def calls(risk):
        return sum(bots.make_bot(s, risk)(view)[0] != "fold" for s in range(40))
    assert calls(0.0) < calls(1.0)
    assert 0 <= bots.make_bot(5).risk <= 1


def test_table_odds_only_on_hero_turn():
    t = Table(players=3, seed=4)
    try:
        t.odds(); assert False
    except TableError:
        pass
    s = t.deal()
    while not s["to_act"]:
        s = t.deal()
    o = t.odds(sims=200)
    assert 0 <= o["equity"] <= 1 and o["opponents"] >= 1
    assert t.odds() == o                                        # cached for this decision
    assert o["verdict"] in ("call_plus_ev", "call_minus_ev", "value_bet", "check")
    a = s["to_act"]
    if a["can_raise"]:
        r = t.odds(raise_to=a["allin_to"])
        assert 0 < r["caller_needs"] < 0.5 and r["equity"] == o["equity"]
        try:
            t.odds(raise_to=a["allin_to"] + 1); assert False
        except TableError:
            pass
    assert o["pot_odds"] == round(odds.pot_odds(o["to_call"], o["pot"]), 4)
    assert all("style" not in p and "risk" not in p for p in s["players"])   # play style is hidden
