"""Tests for the interactive CLI (play.py): human input parsing + bot legality."""
import builtins

import engine as e
import play


def _view(**kw):
    base = dict(hole=e.cards("As Kd"), board=[], pot=6, my_stack=100, to_call=0,
                can_check=True, can_raise=True, min_raise_to=6, allin_to=100,
                seat=0, street="flop", my_street_bet=0, num_active=3)
    base.update(kw)
    return base


def _feed(inputs):
    it = iter(inputs)
    builtins.input = lambda prompt="": next(it)


def human(view):
    return play.make_human(["You", "Bob"])(view)


def test_human_parses_actions():
    _feed(["k"]);      assert human(_view(can_check=True)) == ("check",)
    _feed(["c"]);      assert human(_view(can_check=False, to_call=4)) == ("call",)
    _feed(["f"]);      assert human(_view(can_check=False, to_call=4)) == ("fold",)
    _feed(["a"]);      assert human(_view()) == ("allin",)
    _feed(["r 20"]);   assert human(_view()) == ("raise", 20)
    _feed(["b"]);      assert human(_view(min_raise_to=6)) == ("raise", 6)   # bare bet -> min
    _feed([""]);       assert human(_view(can_check=True)) == ("check",)     # enter = check


def test_human_reprompts_on_bad_input():
    _feed(["huh", "r 999", "r 8"])                       # junk, out-of-range, then valid
    assert human(_view(min_raise_to=6, allin_to=100)) == ("raise", 8)


def test_human_quit_raises():
    _feed(["q"])
    try:
        human(_view())
        assert False, "expected Quit"
    except play.Quit:
        pass


def test_bot_returns_legal_actions():
    bot = play.make_bot(42)
    for board in ([], e.cards("As Kd 5c"), e.cards("As Kd 5c 9h 2s")):
        act = bot(_view(board=board, can_check=True))
        assert act[0] in ("check", "raise")
        if act[0] == "raise":
            assert _view()["min_raise_to"] <= act[1] <= _view()["allin_to"]
        act2 = bot(_view(board=board, can_check=False, to_call=4))
        assert act2[0] in ("fold", "call", "raise")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"ALL {len(fns)} TESTS PASSED")
