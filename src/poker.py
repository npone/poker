"""Headless demo of the Hold'em backend engine — plays a short game and prints each hand.

    python poker.py

For the engine API see engine.py; the legacy ASCII card renderer lives in demo_ascii.py
(python demo_ascii.py) using display.py / pokerClass.py.
"""
import random

import engine as e


def simple_policy(view):
    """A tiny demo bot: bets/raises with a made hand, calls cheaply, folds to big bets with
    nothing. Not a serious strategy — just to make the demo lively."""
    made = e.evaluate(view["hole"] + view["board"])[0] if view["board"] else 0
    if view["can_check"]:
        if made >= 3 and view["can_raise"]:
            return ("raise", min(view["min_raise_to"] + view["pot"], view["allin_to"]))
        return ("check",)
    if made >= 4 and view["can_raise"]:
        return ("raise", min(view["min_raise_to"] + view["pot"], view["allin_to"]))
    if view["to_call"] <= view["my_stack"] // 8 or made >= 1:
        return ("call",)
    return ("fold",)


def main():
    names = ["Alice", "Bob", "Carol", "Dave"]
    g = e.HoldemGame([100] * 4, sb=1, bb=2, button=0, rng=random.Random(2026))
    print(f"Seats: {', '.join(names)} — 100 chips each, blinds 1/2\n")

    for h in range(1, 9):
        if len([p for p in g.players if p.stack > 0]) < 2:
            break
        res = g.play_hand([simple_policy] * 4)
        board = " ".join(str(c) for c in res["board"]) or "(no showdown)"
        print(f"Hand {h}  button={names[res['button']]}")
        print(f"  board: {board}")
        for pot in res["pots"]:
            winners = ", ".join(names[w] for w in pot["winners"])
            if len(pot["eligible"]) > 1:
                score = e.evaluate(g.players[pot["winners"][0]].hole + g.board)
                print(f"  pot {pot['amount']}: {winners} wins ({e.hand_name(score)})")
            else:
                print(f"  pot {pot['amount']}: {winners} wins (uncontested)")
        print("  stacks: " + ", ".join(f"{n} {p.stack}" for n, p in zip(names, g.players)))
        print()
        g.advance_button()

    print("Final chips: " + ", ".join(f"{n} {p.stack}" for n, p in zip(names, g.players)))


if __name__ == "__main__":
    main()
