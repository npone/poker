"""Tests for table.py, the session every front end drives: hero vs bots, JSON snapshots."""
import json
import random

import engine as e
from table import Table, TableError


def _hero_random(t, s, rng):
    """Pick a random legal hero action from snapshot `s`."""
    a = s["to_act"]
    kinds = ["fold", "call", "allin"] + (["check"] if a["can_check"] else [])
    if a["can_raise"]:
        kinds.append("raise")
    k = rng.choice(kinds)
    if k == "raise":
        return t.act("raise", rng.randint(a["min_raise_to"], a["allin_to"]))
    return t.act(k)


def test_hand_generator_matches_play_hand():
    order = e.make_deck()
    random.Random(3).shuffle(order)
    pols = [e.calling_station, e.fold_to_bet, e.always_allin]
    a = e.HoldemGame([100, 80, 60], button=1).play_hand(pols, order=order)
    g = e.HoldemGame([100, 80, 60], button=1)
    h = g.hand(order)
    try:
        v = next(h)
        while True:
            v = h.send(pols[v["seat"]](v))
    except StopIteration as done:
        b = done.value
    assert a == b


def test_fuzz_sessions_conserve_chips_and_hide_cards():
    for seed in range(60):
        rng = random.Random(seed)
        n = rng.randint(2, 6)
        t = Table(players=n, stack=50, seed=seed)
        total = 50 * n
        for _ in range(300):
            if t.game_over:
                break
            s = t.deal()
            while s["in_hand"]:
                assert s["to_act"] is not None
                json.dumps(s)                                   # must be JSON-able
                for p in s["players"]:
                    if p["seat"] != 0:
                        assert p["hole"] is None, "bot cards leaked mid-hand"
                s = _hero_random(t, s, rng)
            assert s["result"] is not None and s["events"][-1]["type"] == "result"
            assert sum(p["stack"] for p in s["players"]) == total
            assert sum(s["result"]["net"]) == 0
            for seat in s["result"]["shown"]:
                assert s["result"]["showdown"]
        assert t.game_over, f"seed {seed}: game did not finish"
        s = t.state()
        assert s["game_over"]
        if s["winner"] is not None:                             # sole survivor holds every chip
            assert s["players"][s["winner"]]["stack"] == total
        assert s["players"][0]["stack"] == 0 or s["winner"] == 0


def test_illegal_actions_rejected():
    t = Table(players=3, seed=1)
    for bad in (lambda: t.act("call"), lambda: t.state() and t.act("fold")):
        try:
            bad(); assert False, "expected TableError"
        except TableError:
            pass
    s = t.deal()
    while not s["to_act"]:
        s = t.deal()
    a = s["to_act"]
    for kind, amt in (("raise", a["allin_to"] + 1), ("raise", None), ("dance", None)):
        try:
            t.act(kind, amt); assert False, f"expected TableError for {kind} {amt}"
        except TableError:
            pass
    if not a["can_check"]:
        try:
            t.act("check"); assert False
        except TableError:
            pass
    try:
        t.deal(); assert False, "deal mid-hand"
    except TableError:
        pass


def test_bad_table_config_rejected():
    for kw in (dict(players=1), dict(players=9), dict(sb=3, bb=2), dict(bb=200, stack=100)):
        try:
            Table(**kw); assert False, kw
        except TableError:
            pass


def test_events_narrate_the_hand():
    t = Table(players=2, seed=5)
    s = t.deal()
    kinds = [ev["type"] for ev in s["events"]]
    assert kinds[0] == "hand" and kinds[1] == "street"
    assert s["players"][0]["hole"] and len(s["players"][0]["hole"]) == 2
    s = t.act("fold") if s["in_hand"] else s
    assert s["events"][-1]["type"] == "result"
    assert t.state()["events"] == []                  # events are delivered once
