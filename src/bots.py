"""Bot policies shared by every front end (terminal CLI, web server, later the mobile apps)."""
import random

import engine as e

BOT_NAMES = ["Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi"]


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
