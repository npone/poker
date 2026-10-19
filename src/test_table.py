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


def test_bot_crash_voids_hand_without_wedging_table():
    t = Table(players=3, stack=50, seed=2)
    def boom(view):
        raise RuntimeError("bot bug")
    t.bots = {s: boom for s in t.bots}
    try:
        for _ in range(5):                             # the hero may act first; keep going
            s = t.deal() if not t.in_hand else t.act("call")
        assert False, "expected the bot error to surface"
    except RuntimeError:
        pass
    assert not t.in_hand
    assert sum(p["stack"] for p in t.state()["players"]) == 150     # chips returned
    t.bots = {s: e.calling_station for s in t.bots}
    s = t.deal()                                                     # table still usable
    assert s["hand_no"] >= 2


def test_events_narrate_the_hand():
    t = Table(players=2, seed=5)
    s = t.deal()
    kinds = [ev["type"] for ev in s["events"]]
    assert kinds[0] == "hand" and kinds[1] == "street"
    assert s["players"][0]["hole"] and len(s["players"][0]["hole"]) == 2
    s = t.act("fold") if s["in_hand"] else s
    assert s["events"][-1]["type"] == "result"
    assert t.state()["events"] == []                  # events are delivered once


def test_hand_history_records_what_the_hero_saw():
    rng = random.Random(9)
    t = Table(players=4, stack=200, seed=9)
    shown_any = False
    for _ in range(60):
        if t.game_over:
            break
        s = t.deal()
        while s["in_hand"]:
            s = _hero_random(t, s, rng)
        rec = t.hand_record(s["hand_no"])
        assert rec["hole"] and len(rec["hole"]) == 2
        assert [p["stack"] for p in rec["players"]] == [st - n for st, n in zip(
            [p["stack"] for p in s["players"]], s["result"]["net"])]       # start stacks
        kinds = [ev["type"] for ev in rec["events"]]
        assert kinds[0] == "hand" and kinds[-1] == "result" and "street" in kinds
        res = rec["events"][-1]
        # no bot's hole cards anywhere except the ones shown at showdown
        text = json.dumps(rec["events"])
        for p in t.game.players[1:]:
            if p.hole and p.seat not in res["shown"]:
                assert not all(repr(c) in text for c in p.hole) or res["showdown"]
        shown_any |= bool(res["shown"])
    assert shown_any
    hands = t.hands()
    assert [h["hand_no"] for h in hands] == [r["hand_no"] for r in t.history]
    assert sum(h["net"] for h in hands) == sum(r["events"][-1]["net"][0] for r in t.history)
    assert t.hand_record(10_000) is None


def test_history_keeps_only_the_last_hands():
    import table
    t = Table(players=2, stack=10_000, sb=1, bb=2, seed=1)
    for _ in range(table.HISTORY + 5):
        s = t.deal()
        while s["in_hand"]:
            s = t.act("fold") if not s["to_act"]["can_check"] else t.act("check")
    assert len(t.history) == table.HISTORY
    assert t.history[0]["hand_no"] == 6 and t.hand_record(1) is None


def test_snapshot_restore_round_trip():
    t = Table(players=5, stack=80, sb=2, bb=4, seed=3)
    rng = random.Random(3)
    for _ in range(6):
        if t.game_over:
            break
        s = t.deal()
        while s["in_hand"]:
            s = _hero_random(t, s, rng)
            if s["in_hand"]:
                try:
                    t.snapshot(); assert False, "saved mid-hand"
                except TableError:
                    pass
    snap = json.loads(json.dumps(t.snapshot()))                     # survives JSON storage
    r = Table.restore(snap)
    assert r.snapshot() == snap
    assert [b.risk for b in r.bots.values()] == [b.risk for b in t.bots.values()]
    if not r.game_over:
        s = r.deal()                                                 # and it plays on
        assert s["hand_no"] == snap["hand_no"] + 1
        assert sum(p.stack + p.contributed for p in r.game.players) == 400
