"""Regression tests for the Hold'em backend engine (engine.py).
Run: python test_engine.py   (or: pytest test_engine.py)
"""
import random

import engine as e
from engine import HoldemGame, cards, evaluate, hand_name


def ev(spec):
    return evaluate(cards(spec))


# ── evaluator: categories, ordering, kickers ────────────────────────────────

def test_category_ordering():
    order = [
        ev("Ah Kh Qh Jh Th"),   # straight flush (royal)
        ev("9c 9d 9h 9s 2c"),   # quads
        ev("9c 9d 9h 2s 2c"),   # full house
        ev("2c 5c 7c 9c Kc"),   # flush
        ev("Ah Kd Qc Js Tc"),   # straight
        ev("9c 9d 9h 2s 5c"),   # trips
        ev("9c 9d 2h 2s 5c"),   # two pair
        ev("9c 9d 2h 5s 7c"),   # pair
        ev("Ah Kd 9c 5s 2c"),   # high card
    ]
    assert order == sorted(order, reverse=True)          # strictly descending strength
    assert hand_name(order[0]) == "Royal Flush"


def test_kickers():
    assert ev("Ah As Kd 5c 2h") > ev("Ac Ad Qh 5s 2c")          # pair, K kicker > Q
    assert ev("Ah As Kd Kc 9h") > ev("Ah As Kd Kc 8h")          # two pair, 9 kicker > 8
    assert ev("9h 9s 9d Kc 2h") > ev("9h 9s 9c Qd 2s")          # trips, K kicker > Q
    assert ev("Ah Kh 9h 5h 3h") > ev("Ah Kh 9h 5h 2h")          # flush, 3 > 2
    assert ev("Ah As Ad Kc Kd") > ev("Ah As Ad Qc Qd")          # boat, aces-full-K > aces-full-Q
    assert ev("9h 9s 9d 9c Kh") > ev("9h 9s 9d 9c Qh")          # quads, K kicker > Q


def test_straights_ace_high_and_wheel():
    assert ev("Ah Kd Qc Js Tc") > ev("Kh Qd Jc Ts 9c")          # broadway > K-high straight
    assert ev("6h 5d 4c 3s 2c") > ev("Ah 2d 3c 4s 5c")          # 6-high > wheel
    assert ev("Ah 2d 3c 4s 5c")[0] == 4                          # wheel is a straight
    assert ev("Ah 2d 3c 4s 5c")[1] == (5,)                       # ...ranked 5-high


def test_best_of_seven_and_split():
    assert hand_name(ev("Ah Kh Qh Jh Th 2c 3d")) == "Royal Flush"
    assert ev("Ah As Kd Qc Jh") == ev("Ac Ad Ks Qh Js")         # identical ranks -> tie


# ── deck ─────────────────────────────────────────────────────────────────────

def test_deck_complete_and_unique():
    d = e.make_deck()
    assert len(d) == 52 and len(set(d)) == 52

def test_deck_deals_in_order():
    order = cards("As Kd 2c")
    d = e.Deck(order)
    assert d.remaining() == 3
    assert [d.deal(), d.deal()] == cards("As Kd") and d.remaining() == 1


# ── positions / blinds ───────────────────────────────────────────────────────

def test_blinds_posted():
    g = HoldemGame([100, 100, 100], sb=1, bb=2, button=0)
    # everyone folds to BB -> SB=seat1 loses 1, BB=seat2 nets +1, button(UTG seat0) untouched
    g.play_hand([e.fold_to_bet, e.fold_to_bet, e.fold_to_bet])
    assert [p.stack for p in g.players] == [100, 99, 101]

def test_heads_up_button_is_small_blind():
    g = HoldemGame([100, 100], sb=1, bb=2, button=0)
    # button(seat0)=SB acts first preflop and folds -> BB(seat1) wins the 1 chip
    g.play_hand([e.fold_to_bet, e.fold_to_bet])
    assert [p.stack for p in g.players] == [99, 101]


# ── betting mechanics (scripted) ─────────────────────────────────────────────

def _deck_for(game, holes_by_seat, board):
    """Build a deal-order deck so each seat gets its holes and the board is as given."""
    alive = game._alive()
    order = []
    for r in range(2):
        for s in alive:
            order.append(holes_by_seat[s][r])
    order += list(board)
    return order

def test_raise_reopens_and_call_closes():
    g = HoldemGame([100, 100, 100], sb=1, bb=2, button=0)
    holes = {0: cards("Ah Ad"), 1: cards("Kh Kd"), 2: cards("Qh Qd")}
    board = cards("2c 7d 9h Js 3s")
    deck = _deck_for(g, holes, board)
    # preflop order (3-handed): UTG=seat0, then seat1(SB), seat2(BB)
    pol = [
        e.scripted([("raise", 6), ("call",), ("check",), ("check",), ("check",)]),   # seat0
        e.scripted([("call",), ("check",), ("check",), ("check",), ("check",)]),     # seat1
        e.scripted([("raise", 12), ("check",), ("check",), ("check",), ("check",)]), # seat2 reraise
    ]
    res = g.play_hand(pol, order=deck)
    assert sum(p.contributed for p in g.players) == res["pots"][0]["amount"]
    # seat0 (AA) wins; everyone put in 12 -> pot 36
    assert g.players[0].stack == 100 - 12 + 36
    assert res["pots"][0]["winners"] == [0]


# ── side pots (unit) ─────────────────────────────────────────────────────────

def _pots_with(contribs, folded):
    g = HoldemGame([0] * len(contribs), button=0)
    for p, c, f in zip(g.players, contribs, folded):
        p.contributed, p.folded = c, f
    return g._build_pots()

def test_single_pot_equal_contributions():
    pots = _pots_with([100, 100, 100], [False, False, False])
    assert pots == [{"amount": 300, "eligible": [0, 1, 2]}]

def test_side_pot_short_all_in():
    pots = _pots_with([30, 100, 100], [False, False, False])
    assert pots == [{"amount": 90, "eligible": [0, 1, 2]},
                    {"amount": 140, "eligible": [1, 2]}]
    assert sum(p["amount"] for p in pots) == 230

def test_folded_dead_money_excluded_from_eligibility():
    pots = _pots_with([100, 100, 50], [False, True, False])   # seat1 folded
    assert sum(p["amount"] for p in pots) == 250
    for pot in pots:
        assert 1 not in pot["eligible"]                       # folded seat can never win


# ── showdown / payouts ───────────────────────────────────────────────────────

def _showdown(button, contribs, folded, holes, board):
    g = HoldemGame([0] * len(contribs), button=button)
    g.board = cards(board)
    for p, c, f, h in zip(g.players, contribs, folded, holes):
        p.contributed, p.folded, p.hole = c, f, cards(h)
    g._settle()
    return [p.stack for p in g.players]

def test_single_winner_takes_pot():
    stacks = _showdown(0, [20, 20, 20], [False, False, False],
                       ["Ah As", "Kh Ks", "Qh Qs"], "2c 7d 9h Js 3s")
    assert stacks == [60, 0, 0]                               # aces win the 60

def test_split_pot_odd_chip_left_of_button():
    # seats 0 & 1 tie (both play board's kickers); button=2 -> first winner left of button is 0
    stacks = _showdown(2, [5, 5, 5], [False, False, False],
                       ["As Ks", "Ac Kc", "2d 3d"], "Ah Kh Qh 5s 6d")
    assert stacks == [8, 7, 0]                                # 15 split -> 7 each, odd chip to seat0

def test_side_pot_short_stack_wins_main_only():
    # seat0 all-in 30 with the nut full house -> wins main (90); seat1 wins the side (140)
    stacks = _showdown(0, [30, 100, 100], [False, False, False],
                       ["As Ac", "Ks Kc", "3s 4s"], "2c 2d 2h 7s 9c")
    assert stacks == [90, 140, 0]


# ── integration ──────────────────────────────────────────────────────────────

def test_heads_up_all_in_known_winner():
    g = HoldemGame([100, 100], sb=1, bb=2, button=0)
    holes = {0: cards("Ah As"), 1: cards("Kd Kc")}
    board = cards("2c 7d 9h Js 3c")
    deck = _deck_for(g, holes, board)
    g.play_hand([e.always_allin, e.calling_station], order=deck)
    assert [p.stack for p in g.players] == [200, 0]           # AA holds vs KK

def test_everyone_folds_to_one():
    g = HoldemGame([100, 100, 100], sb=1, bb=2, button=0)
    r = g.play_hand([e.fold_to_bet, e.fold_to_bet, e.calling_station])
    assert r["pots"][0]["winners"] == [2]                     # BB wins uncontested


# ── fuzz: invariants over many random hands ──────────────────────────────────

def test_fuzz_invariants():
    def randpol(view):
        r = rng.random()
        if not view["can_check"] and r < 0.20:
            return ("fold",)
        if view["can_raise"] and r < 0.18:
            return ("raise", rng.randint(view["min_raise_to"], view["allin_to"]))
        return ("check",) if view["can_check"] else ("call",)

    for seed in range(300):
        rng = random.Random(seed)
        n = rng.choice([2, 3, 4, 5, 6])
        g = HoldemGame([rng.choice([20, 50, 100, 200]) for _ in range(n)],
                       sb=1, bb=2, button=rng.randrange(n), rng=random.Random(seed))
        before = sum(p.stack for p in g.players)
        res = g.play_hand([randpol] * n)
        after = sum(p.stack for p in g.players)
        assert before == after, f"chip leak seed={seed}: {before} -> {after}"
        assert all(p.stack >= 0 for p in g.players), f"negative stack seed={seed}"
        # the pots exactly account for everything wagered this hand
        wagered = sum(p.contributed for p in g.players)
        assert sum(pot["amount"] for pot in res["pots"]) == wagered, f"pot mismatch seed={seed}"
        # winners of a contested pot really hold the best hand among its eligible players
        for pot in res["pots"]:
            elig = pot["eligible"]
            if len(elig) > 1:
                best = max(evaluate(g.players[s].hole + g.board) for s in elig)
                assert all(evaluate(g.players[w].hole + g.board) == best
                           for w in pot["winners"]), f"wrong winner seed={seed}"


def test_full_game_terminates_with_one_winner():
    g = HoldemGame([50, 50, 50, 50], sb=1, bb=2, rng=random.Random(3))
    g.play([e.calling_station] * 4)
    survivors = [i for i, p in enumerate(g.players) if p.stack > 0]
    assert len(survivors) == 1
    assert sum(p.stack for p in g.players) == 200            # chips conserved to the end


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"ALL {passed} TESTS PASSED")
