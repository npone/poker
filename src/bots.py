"""Bot policies shared by every front end (terminal CLI, web server, later the mobile apps)."""
import random

import odds

BOT_NAMES = ["Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi"]
SIMS = 250                       # Monte Carlo showdowns per decision (~10 ms per opponent)


def make_bot(seed: int, risk: float | None = None):
    """An equity bot. Each decision it estimates its chance to win against the hands still in
    (Monte Carlo vs random holdings, discounted when facing a big bet, since bettors are rarely
    random), then weighs that against the pot odds and how much of its stack is at stake.

    `risk` (0-1, random by default) is its risk tolerance: a rock (0) wants a clear edge before it
    puts chips in, especially a big share of its stack, and seldom bluffs; a maniac (1) calls
    close spots, bets bigger and bluffs often. The policy carries it as `policy.risk`."""
    rng = random.Random(seed)
    risk = rng.random() if risk is None else risk

    def policy(view):
        pot, to_call, stack = max(view["pot"], 1), view["to_call"], view["my_stack"]
        opp = sum(not f for f in view["folded"]) - 1
        eq = odds.equity(view["hole"], view["board"], opp, SIMS, rng)
        if to_call:                                  # a bet narrows the bettor's range
            eq *= 1 - 0.45 * min(1.0, to_call / pot) * (1 - 0.5 * risk)
        edge = eq * (opp + 1)                        # 1.0 = a fair share of the pot

        def bet(frac):
            to = view["my_street_bet"] + to_call + int(frac * (pot + to_call))
            return ("raise", max(view["min_raise_to"], min(to, view["allin_to"])))

        if view["can_raise"] and edge > 1.7 - 0.5 * risk:          # value: build the pot
            if rng.random() < 0.15 * (1 - risk) and to_call:       # sometimes just call (trap)
                return ("call",)
            return bet(0.5 + 0.5 * risk + 0.2 * (edge - 1))
        if view["can_check"]:
            if view["can_raise"] and opp <= 2 and rng.random() < 0.04 + 0.18 * risk:
                return bet(0.5 + 0.3 * risk)                       # bluff into few players
            return ("check",)
        at_stake = min(1.0, to_call / max(stack, 1))
        need = odds.pot_odds(to_call, pot) + (1 - risk) * (0.06 + 0.2 * at_stake) - 0.05 * risk
        if eq >= need:
            return ("call",)
        if view["can_raise"] and opp == 1 and rng.random() < 0.06 * risk:
            return bet(0.8)                                        # the occasional re-bluff
        return ("fold",)

    policy.risk = risk
    return policy
