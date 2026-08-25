"""Play No-Limit Texas Hold'em against the bots, in your terminal.

    python play.py                       # you + 3 bots, 100 chips, blinds 1/2
    python play.py --players 6 --stack 200 --sb 1 --bb 2 --seed 7

You are seat 0 ("You"). At your turn, type one of:
    k=check   c=call   f=fold   b/r <N>=bet/raise to N   a=all-in   q=quit
(Enter alone = check if free, else call.)
"""
import argparse
import random

import engine as e

_SUIT_SYM = {0: "♣", 1: "♦", 2: "♥", 3: "♠"}   # ♣ ♦ ♥ ♠
_RANK_CH = {**{r: str(r) for r in range(2, 10)},
            10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
BOT_NAMES = ["Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi"]


class Quit(Exception):
    pass


def fmt(card) -> str:
    return f"{_RANK_CH[card.rank]}{_SUIT_SYM[card.suit]}"


def fmt_cards(cs) -> str:
    return " ".join(fmt(c) for c in cs) if cs else "-"


def make_bot(seed: int):
    """A simple heat-varied bot: bets/raises with a made hand, calls cheap, folds to pressure."""
    rng = random.Random(seed)
    aggression = rng.uniform(0.6, 1.4)

    def policy(view):
        made = e.evaluate(view["hole"] + view["board"])[0] if view["board"] else 0
        pot = max(view["pot"], 1)
        if view["can_check"]:
            if made >= 3 and view["can_raise"] and rng.random() < 0.7 * aggression:
                return ("raise", min(view["min_raise_to"] + int(pot * 0.6), view["allin_to"]))
            return ("check",)
        # facing a bet
        odds = view["to_call"] / (pot + view["to_call"])
        if made >= 4 and view["can_raise"]:
            return ("raise", min(view["min_raise_to"] + int(pot * 0.75), view["allin_to"]))
        if made >= 1 or odds < 0.2 * aggression:
            return ("call",)
        return ("fold",)
    return policy


def make_human(names):
    def policy(view):
        board = view["board"]
        print(f"\n  Your hand: {fmt_cards(view['hole'])}    Board: {fmt_cards(board)}")
        print(f"  Pot {view['pot']}   |   your stack {view['my_stack']}", end="")
        if not view["can_check"]:
            print(f"   |   to call {view['to_call']}")
        else:
            print()
        opts = []
        if view["can_check"]:
            opts.append("(k)check")
        else:
            opts.append(f"(c)all {view['to_call']}")
        if view["can_raise"]:
            verb = "bet" if view["can_check"] else "raise"
            opts.append(f"({verb[0]}){verb} {view['min_raise_to']}-{view['allin_to']}")
        opts += ["(f)old", "(q)uit"]
        print("  " + "   ".join(opts))
        while True:
            try:
                raw = input("  > ").strip().lower()
            except EOFError:
                raise Quit()
            if raw in ("q", "quit"):
                raise Quit()
            if raw == "":
                return ("check",) if view["can_check"] else ("call",)
            cmd, _, arg = raw.partition(" ")
            if cmd in ("f", "fold"):
                return ("fold",)
            if cmd in ("k", "check", "c", "call"):
                return ("check",) if view["can_check"] else ("call",)
            if cmd in ("a", "allin", "all-in", "all"):
                return ("allin",)
            if cmd in ("b", "bet", "r", "raise"):
                if not view["can_raise"]:
                    print("  can't raise here.")
                    continue
                if arg == "":
                    return ("raise", view["min_raise_to"])
                try:
                    total = int(arg)
                except ValueError:
                    print("  amount must be a number.")
                    continue
                if total < view["min_raise_to"] or total > view["allin_to"]:
                    print(f"  raise must be {view['min_raise_to']}-{view['allin_to']}.")
                    continue
                return ("raise", total)
            print("  didn't understand that.")
    return policy


def main():
    ap = argparse.ArgumentParser(description="Play Hold'em against the bots.")
    ap.add_argument("--players", type=int, default=4, help="total players incl. you (2-8)")
    ap.add_argument("--stack", type=int, default=100)
    ap.add_argument("--sb", type=int, default=1)
    ap.add_argument("--bb", type=int, default=2)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    n = max(2, min(8, args.players))
    rng = random.Random(args.seed)

    names = ["You"] + BOT_NAMES[: n - 1]
    g = e.HoldemGame([args.stack] * n, sb=args.sb, bb=args.bb, button=0, rng=rng)
    policies = [make_human(names)] + [make_bot(rng.randrange(1 << 30)) for _ in range(n - 1)]

    def on_street(street, board):
        if street != "preflop":
            print(f"  -- {street.capitalize()}: {fmt_cards(board)} --")

    def on_action(p, action, amount):
        if p.seat == 0:
            return                                        # you saw your own action
        kind = action[0]
        if kind == "fold":
            msg = "folds"
        elif kind == "check":
            msg = "checks"
        elif kind == "call":
            msg = f"calls {amount}" if amount else "checks"
        else:
            msg = ("is all-in for " if p.stack == 0 else "raises to ") + str(action[1])
        print(f"  {names[p.seat]} {msg}")

    g.on_street = on_street
    g.on_action = on_action

    print(f"\nHold'em — {', '.join(names)} — {args.stack} chips, blinds {args.sb}/{args.bb}")
    print("You are 'You' (seat 0).  Good luck!\n")
    hand = 0
    while len([p for p in g.players if p.stack > 0]) >= 2 and g.players[0].stack > 0:
        hand += 1
        print("=" * 60)
        print(f"Hand {hand}   button: {names[g.button]}   "
              f"stacks: " + ", ".join(f"{names[i]} {p.stack}" for i, p in enumerate(g.players)
                                      if p.stack > 0))
        try:
            res = g.play_hand(policies)
        except Quit:
            print("\nThanks for playing!")
            return
        print(f"  Board: {fmt_cards(res['board'])}")
        for pot in res["pots"]:
            winners = ", ".join(names[w] for w in pot["winners"])
            if len(pot["eligible"]) > 1:
                score = e.evaluate(g.players[pot["winners"][0]].hole + g.board)
                extra = f" with {e.hand_name(score)}"
                shown = "   ".join(f"{names[s]}: {fmt_cards(g.players[s].hole)}"
                                   for s in pot["eligible"] if not g.players[s].folded)
                print(f"  Showdown — {shown}")
            else:
                extra = ""
            print(f"  Pot {pot['amount']} -> {winners}{extra}")
        g.advance_button()
        if g.players[0].stack <= 0:
            break

    if g.players[0].stack <= 0:
        print("\nYou're out of chips. Game over.")
    else:
        print(f"\nYou win! Final stack: {g.players[0].stack}")


if __name__ == "__main__":
    main()
