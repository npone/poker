"""Headless No-Limit Texas Hold'em backend engine.

Self-contained, pure-Python (no numpy). Provides:
  - Card / Deck                       — 52-card deck, real shuffle + deal
  - evaluate(cards)                   — best 5-card hand from 5..7 cards, as a fully
                                        COMPARABLE (category, tiebreakers) tuple (kickers incl.)
  - HoldemGame                        — runs a hand: blinds, betting rounds, all-ins,
                                        side pots, showdown, payouts; and multi-hand play.

The engine is driven by *policies*: a policy is `callable(view) -> action`, where `view` is a
read-only snapshot for the acting player (hole cards, board, pot, amount to call, legal raise
bounds, ...) and `action` is one of:
    ('fold',) ('check',) ('call',) ('raise', total) ('allin',)
`total` is the player's TOTAL wagered on the current street after the raise. This makes the
engine usable as a backend for a UI, a bot, or tests. Built-in policies are at the bottom.

Cards: rank 2..14 (11=J 12=Q 13=K 14=A), suit 0..3 ('c','d','h','s').

Rules note: standard NLHE — blinds, min-raise = size of the last raise (BB preflop), side pots
for all-ins, split pots with odd chips going left of the button. Simplification: a short all-in
(less than a full raise) does not formally reopen re-raising rights, but players still owe the
extra to call — chip accounting and pot awards are exact.
"""
from __future__ import annotations

import random
from collections import Counter
from itertools import combinations

RANKS = list(range(2, 15))                 # 2..14 (14 = Ace)
SUITS = list(range(4))                      # 0..3
_RANK_CH = {**{r: str(r) for r in range(2, 10)},
            10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
_CH_RANK = {v: k for k, v in _RANK_CH.items()}
_SUIT_CH = {0: "c", 1: "d", 2: "h", 3: "s"}
_CH_SUIT = {v: k for k, v in _SUIT_CH.items()}

CATEGORY_NAMES = {
    0: "High Card", 1: "Pair", 2: "Two Pair", 3: "Three of a Kind", 4: "Straight",
    5: "Flush", 6: "Full House", 7: "Four of a Kind", 8: "Straight Flush",
}
STREETS = ("preflop", "flop", "turn", "river")


class Card:
    __slots__ = ("rank", "suit")

    def __init__(self, rank: int, suit: int):
        self.rank = rank
        self.suit = suit

    @classmethod
    def parse(cls, s: str) -> "Card":
        return cls(_CH_RANK[s[0].upper()], _CH_SUIT[s[1].lower()])

    def __repr__(self):
        return _RANK_CH[self.rank] + _SUIT_CH[self.suit]

    def __eq__(self, o):
        return isinstance(o, Card) and self.rank == o.rank and self.suit == o.suit

    def __hash__(self):
        return hash((self.rank, self.suit))


def make_deck() -> list[Card]:
    return [Card(r, s) for s in SUITS for r in RANKS]


def cards(spec: str) -> list[Card]:
    """cards('As Kh Qh') -> [Card,...]  (whitespace-separated)."""
    return [Card.parse(t) for t in spec.split()]


class Deck:
    def __init__(self, order: list[Card] | None = None, rng: random.Random | None = None):
        # order: predetermined deal order (index 0 dealt first). None => shuffled 52.
        self._rng = rng or random.Random()
        if order is not None:
            self.cardstack = list(order)
        else:
            self.cardstack = make_deck()
            self._rng.shuffle(self.cardstack)
        self._i = 0

    def deal(self) -> Card:
        c = self.cardstack[self._i]
        self._i += 1
        return c

    def remaining(self) -> int:
        return len(self.cardstack) - self._i


# ─────────────────────────────────────────────────────────────────────────────
# Hand evaluation — returns a fully comparable (category, tiebreaker-tuple).
# A bigger tuple is the stronger hand, so `max(...)` / `>` / `==` just work.
# ─────────────────────────────────────────────────────────────────────────────

def _straight_high(rank_set: set[int]) -> int | None:
    """Highest card of a 5-in-a-row within rank_set. Ace (14) also plays low (wheel A-2-3-4-5)."""
    s = set(rank_set)
    if 14 in s:
        s.add(1)                                    # Ace low
    for high in range(14, 4, -1):
        if all((high - o) in s for o in range(5)):
            return high
    return None


def evaluate5(five: list[Card]) -> tuple:
    """Rank exactly five cards -> (category:int, tiebreakers:tuple)."""
    ranks = sorted((c.rank for c in five), reverse=True)
    counts = Counter(ranks)
    by = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)   # (count,rank) desc
    pattern = [c for _, c in by]
    is_flush = len({c.suit for c in five}) == 1
    sh = _straight_high(set(ranks))

    if is_flush and sh:
        return (8, (sh,))                            # straight flush (royal when sh == 14)
    if pattern == [4, 1]:
        return (7, (by[0][0], by[1][0]))             # quads + kicker
    if pattern == [3, 2]:
        return (6, (by[0][0], by[1][0]))             # full house: trips, pair
    if is_flush:
        return (5, tuple(ranks))                     # flush: all 5 desc
    if sh:
        return (4, (sh,))                            # straight
    if pattern == [3, 1, 1]:
        return (3, (by[0][0],) + tuple(r for r in ranks if r != by[0][0]))
    if pattern == [2, 2, 1]:
        return (2, (by[0][0], by[1][0], by[2][0]))   # two pair: hi, lo, kicker
    if pattern == [2, 1, 1, 1]:
        return (1, (by[0][0],) + tuple(r for r in ranks if r != by[0][0]))
    return (0, tuple(ranks))                          # high card


def evaluate(hand: list[Card]) -> tuple:
    """Best 5-card hand from 5..7 cards, as a comparable (category, tiebreakers)."""
    if len(hand) < 5:
        raise ValueError("need at least 5 cards to evaluate")
    if len(hand) == 5:
        return evaluate5(hand)
    return max(evaluate5(list(c)) for c in combinations(hand, 5))


def hand_name(score: tuple) -> str:
    cat = score[0]
    if cat == 8 and score[1][0] == 14:
        return "Royal Flush"
    return CATEGORY_NAMES[cat]


# ─────────────────────────────────────────────────────────────────────────────
# Game engine
# ─────────────────────────────────────────────────────────────────────────────

class Player:
    __slots__ = ("seat", "stack", "hole", "folded", "allin", "contributed", "street_bet")

    def __init__(self, seat: int, stack: int):
        self.seat = seat
        self.stack = stack
        self.hole: list[Card] = []
        self.folded = False
        self.allin = False
        self.contributed = 0        # total put in this hand (all streets)
        self.street_bet = 0         # put in on the current street


class HoldemGame:
    def __init__(self, stacks, sb=1, bb=2, button=0, rng: random.Random | None = None):
        self.players = [Player(i, int(s)) for i, s in enumerate(stacks)]
        self.num = len(self.players)
        if self.num < 2:
            raise ValueError("need at least 2 players")
        self.sb = sb
        self.bb = bb
        self.button = button
        self.rng = rng or random.Random()
        self.board: list[Card] = []
        self.current_bet = 0
        self.min_raise = bb
        # Optional narration hooks (default no-ops), used by the interactive CLI:
        #   on_action(player, action, chips_put)  — after each applied action
        #   on_street(street_name, board)         — when a street's cards are dealt
        self.on_action = None
        self.on_street = None

    # -- helpers ---------------------------------------------------------------
    def _alive(self) -> list[int]:
        """Seats with chips, ordered starting just left of the button."""
        seats = [(self.button + 1 + k) % self.num for k in range(self.num)]
        return [s for s in seats if self.players[s].stack > 0]

    def _not_folded(self) -> list[int]:
        return [p.seat for p in self.players if not p.folded]

    def _active_bettors(self) -> list[Player]:
        return [p for p in self.players if not p.folded and not p.allin and p.stack > 0]

    def pot_total(self) -> int:
        return sum(p.contributed for p in self.players)

    def _put(self, p: Player, amount: int):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_bet += amount
        p.contributed += amount
        if p.stack == 0:
            p.allin = True

    # -- per-hand orchestration ------------------------------------------------
    def play_hand(self, policies, order: list[Card] | None = None) -> dict:
        """Play one full hand. `policies[seat]` decides that seat's actions. `order` optionally
        fixes the deal order (for tests). Returns a result dict; stacks are updated in place."""
        alive = self._alive()
        if len(alive) < 2:
            raise ValueError("need >= 2 players with chips")
        for p in self.players:                       # reset per-hand state
            p.hole, p.folded, p.allin, p.contributed, p.street_bet = [], p.stack == 0, False, 0, 0
        self.board = []
        deck = Deck(order, self.rng)
        stacks_before = [p.stack for p in self.players]

        # positions
        if len(alive) == 2:
            sb_seat, bb_seat = self.button, next(s for s in alive if s != self.button)
            preflop_first, postflop_first = sb_seat, bb_seat
        else:
            sb_seat, bb_seat = alive[0], alive[1]
            preflop_first = alive[2 % len(alive)]
            postflop_first = alive[0]

        # deal two hole cards, one at a time, starting left of the button
        for _ in range(2):
            for s in alive:
                self.players[s].hole.append(deck.deal())

        # blinds
        self._put(self.players[sb_seat], self.sb)
        self._put(self.players[bb_seat], self.bb)
        self.current_bet = max(p.street_bet for p in self.players)
        self.min_raise = self.bb

        # preflop
        if self.on_street:
            self.on_street("preflop", [])
        self._betting_round(preflop_first, policies, "preflop")
        # flop / turn / river
        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(self._not_folded()) <= 1:
                break
            for _ in range(n_cards):
                self.board.append(deck.deal())
            if self.on_street:
                self.on_street(street, list(self.board))
            if len(self._active_bettors()) >= 1 and self._someone_can_bet():
                self._reset_street()
                self._betting_round(postflop_first, policies, street)

        pots = self._settle()
        return {
            "board": list(self.board),
            "pots": pots,
            "stacks": [p.stack for p in self.players],
            "stacks_before": stacks_before,
            "folded": [p.folded for p in self.players],
            "holes": [list(p.hole) for p in self.players],
            "button": self.button,
        }

    def _someone_can_bet(self) -> bool:
        # a betting round is only meaningful if >=2 players can still put chips in
        return len([p for p in self.players if not p.folded and not p.allin and p.stack > 0]) >= 2

    def _reset_street(self):
        for p in self.players:
            p.street_bet = 0
        self.current_bet = 0
        self.min_raise = self.bb

    # -- betting ---------------------------------------------------------------
    def _betting_round(self, first: int, policies, street: str):
        n = self.num
        order = [(first + k) % n for k in range(n)]
        acted: set[int] = set()                      # seats squared with current_bet since last raise
        i = 0
        guard = 0
        while True:
            guard += 1
            if guard > 10000:
                raise RuntimeError("betting round did not terminate")
            if len(self._not_folded()) <= 1:
                return
            active = self._active_bettors()
            if not active:
                return
            if all(p.seat in acted and p.street_bet == self.current_bet for p in active):
                return
            seat = order[i % n]
            i += 1
            p = self.players[seat]
            if p.folded or p.allin or p.stack == 0:
                continue
            if p.seat in acted and p.street_bet == self.current_bet:
                continue
            action = self._normalize(p, policies[seat], street)
            self._apply(p, action, acted)

    def _legal(self, p: Player) -> dict:
        to_call = self.current_bet - p.street_bet
        can_check = to_call == 0
        allin_to = p.street_bet + p.stack               # total street bet if shoving
        min_raise_to = self.current_bet + self.min_raise
        can_raise = p.stack > to_call                   # has chips beyond a call
        if min_raise_to > allin_to:                     # can't reach a full raise -> only shove
            min_raise_to = allin_to
        return {"to_call": to_call, "can_check": can_check, "can_raise": can_raise,
                "min_raise_to": min_raise_to, "allin_to": allin_to}

    def _normalize(self, p: Player, policy, street: str):
        lg = self._legal(p)
        view = {
            "seat": p.seat, "street": street, "hole": list(p.hole), "board": list(self.board),
            "pot": self.pot_total(), "current_bet": self.current_bet,
            "to_call": lg["to_call"], "can_check": lg["can_check"], "can_raise": lg["can_raise"],
            "min_raise_to": lg["min_raise_to"], "allin_to": lg["allin_to"],
            "my_stack": p.stack, "my_street_bet": p.street_bet,
            "num_active": len(self._active_bettors()),
            "stacks": [q.stack for q in self.players],
            "contrib": [q.contributed for q in self.players],
            "folded": [q.folded for q in self.players],
        }
        act = policy(view)
        return self._coerce(act, lg, p)

    def _coerce(self, act, lg, p: Player):
        """Force any policy output into a legal action (robust backend; tests pass legal input)."""
        kind = act[0]
        if kind == "fold":
            return ("fold",)
        if kind == "check":
            return ("check",) if lg["can_check"] else ("call",)
        if kind == "call":
            return ("check",) if lg["can_check"] else ("call",)
        if kind == "allin":
            return ("raise", lg["allin_to"]) if lg["allin_to"] > self.current_bet else ("call",)
        if kind == "raise":
            total = int(act[1])
            if not lg["can_raise"]:
                return ("check",) if lg["can_check"] else ("call",)
            total = max(total, lg["min_raise_to"])
            total = min(total, lg["allin_to"])
            return ("raise", total)
        raise ValueError(f"unknown action {act!r}")

    def _apply(self, p: Player, action, acted: set[int]):
        before = p.stack
        kind = action[0]
        if kind == "fold":
            p.folded = True
            acted.discard(p.seat)
        elif kind == "check":
            acted.add(p.seat)
        elif kind == "call":
            self._put(p, self.current_bet - p.street_bet)     # capped at stack (all-in call)
            acted.add(p.seat)
        elif kind == "raise":
            total = action[1]
            self._put(p, total - p.street_bet)
            if total > self.current_bet:
                inc = total - self.current_bet
                self.current_bet = total
                if inc >= self.min_raise:                     # full raise reopens the round
                    self.min_raise = inc
                    acted.clear()
            acted.add(p.seat)
        if self.on_action:
            self.on_action(p, action, before - p.stack)

    # -- pots & showdown -------------------------------------------------------
    def _build_pots(self) -> list[dict]:
        """Split total contributions into main + side pots. Each pot: {amount, eligible(seats)}.
        Eligible = seats that contributed to that layer and did not fold."""
        remaining = {p.seat: p.contributed for p in self.players if p.contributed > 0}
        pots = []
        while remaining:
            level = min(remaining.values())
            contributors = list(remaining.keys())
            amount = level * len(contributors)
            eligible = [s for s in contributors if not self.players[s].folded]
            if pots and pots[-1]["eligible"] == eligible:      # merge adjacent equal-eligibility
                pots[-1]["amount"] += amount
            else:
                pots.append({"amount": amount, "eligible": eligible})
            for s in contributors:
                remaining[s] -= level
                if remaining[s] == 0:
                    del remaining[s]
        return pots

    def _settle(self) -> list[dict]:
        pots = self._build_pots()
        order_from_button = [(self.button + 1 + k) % self.num for k in range(self.num)]
        results = []
        for pot in pots:
            eligible = pot["eligible"]
            amount = pot["amount"]
            if len(eligible) == 1:
                winners = list(eligible)
            else:
                scored = {s: evaluate(self.players[s].hole + self.board) for s in eligible}
                best = max(scored.values())
                winners = [s for s in eligible if scored[s] == best]
            share, rem = divmod(amount, len(winners))
            for s in winners:
                self.players[s].stack += share
            odd_order = [s for s in order_from_button if s in winners]
            for k in range(rem):                               # odd chips: left of button first
                self.players[odd_order[k % len(odd_order)]].stack += 1
            results.append({"amount": amount, "winners": winners, "eligible": list(eligible)})
        return results

    # -- multi-hand ------------------------------------------------------------
    def advance_button(self):
        for k in range(1, self.num + 1):
            s = (self.button + k) % self.num
            if self.players[s].stack > 0:
                self.button = s
                return

    def play(self, policies, hands: int | None = None) -> list[dict]:
        """Play hands until one player has all the chips (or `hands` hands elapse)."""
        results = []
        h = 0
        while len([p for p in self.players if p.stack > 0]) >= 2:
            if hands is not None and h >= hands:
                break
            results.append(self.play_hand(policies))
            self.advance_button()
            h += 1
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Built-in policies (for demos / tests / bots)
# ─────────────────────────────────────────────────────────────────────────────

def fold_to_bet(view):
    """Check when free, otherwise fold."""
    return ("check",) if view["can_check"] else ("fold",)


def calling_station(view):
    """Never folds, never raises: checks or calls."""
    return ("check",) if view["can_check"] else ("call",)


def always_allin(view):
    return ("allin",)


def scripted(actions):
    """A policy that returns queued actions in order (falls back to check/call/fold at the end)."""
    q = list(actions)

    def _policy(view):
        if q:
            return q.pop(0)
        return ("check",) if view["can_check"] else ("fold",)
    return _policy
