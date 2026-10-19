"""A UI-agnostic game session: one human ("hero", seat 0) against bots.

This is the program every front end drives (the web client now, iOS/Android later). It holds
no UI code and speaks only plain JSON-able dicts:

    t = Table(players=4, stack=100, sb=1, bb=2)
    s = t.deal()                      # start a hand; bots act until it is the hero's turn
    s = t.act("raise", 10)            # hero acts; bots act until the hero's next turn or hand end
    s = t.state()                     # current snapshot, from the hero's seat

Each snapshot carries `events`: what happened since the previous call (actions, streets dealt,
hand result), in order, so a client can animate them. Other players' hole cards are never in a
snapshot unless they were shown at showdown.
"""
from __future__ import annotations

import random
from collections import deque

import engine as e
import odds
from bots import BOT_NAMES, make_bot

HERO = 0
HISTORY = 50                                    # finished hands kept per table, for replay
ACTIONS = ("fold", "check", "call", "raise", "allin")


class TableError(ValueError):
    """An action the hero may not take now (not their turn, hand over, bad amount...)."""


def _card(c: e.Card) -> str:
    return repr(c)                                   # 'Ah', 'Tc', ...


class Table:
    def __init__(self, players: int = 4, stack: int = 100, sb: int = 1, bb: int = 2,
                 seed: int | None = None):
        if not 2 <= players <= 8:
            raise TableError("players must be 2-8")
        if not (1 <= sb <= bb <= stack):
            raise TableError("need 1 <= sb <= bb <= stack")
        rng = random.Random(seed)
        self.names = ["You"] + BOT_NAMES[: players - 1]
        self.game = e.HoldemGame([stack] * players, sb=sb, bb=bb, button=0, rng=rng)
        self.bots = {s: make_bot(rng.randrange(1 << 30)) for s in range(1, players)}
        self.hand_no = 0
        self.street = None
        self._bet_open = False
        self._hand = None                           # the engine's hand generator, while live
        self._view = None                            # hero's pending decision view
        self.result = None                           # last finished hand's summary
        self._events: list[dict] = []
        self.history: deque[dict] = deque(maxlen=HISTORY)
        self._rec = None                             # the hand being recorded for history
        self._odds = (None, None)                    # (decision view, its odds): one per decision
        self.game.on_action = self._on_action
        self.game.on_street = self._on_street

    # -- engine hooks -> event log ---------------------------------------------
    def _on_action(self, p, action, chips):
        kind = action[0]
        if kind == "call" and chips == 0:
            kind = "check"
        elif kind == "raise":
            kind = "allin" if p.stack == 0 else ("raise" if self._bet_open else "bet")
            self._bet_open = True
        elif kind == "call" and p.stack == 0:
            kind = "allin"
        self._emit({"type": "action", "seat": p.seat, "action": kind,
                             "chips": chips, "street_bet": p.street_bet, "stack": p.stack,
                             "pot": self.game.pot_total()})

    def _on_street(self, street, board):
        self.street = street
        self._bet_open = street == "preflop"          # the big blind is the opening bet
        ps = self.game.players                        # preflop: blinds are already posted
        self._emit({"type": "street", "street": street,
                             "board": [_card(c) for c in board],
                             "stacks": [p.stack for p in ps],
                             "bets": [p.street_bet if street == "preflop" else 0 for p in ps],
                             "pot": self.game.pot_total()})

    # -- driving the hand ------------------------------------------------------
    @property
    def in_hand(self) -> bool:
        return self._hand is not None

    @property
    def game_over(self) -> bool:
        alive = [p for p in self.game.players if p.stack > 0]
        return self.game.players[HERO].stack == 0 or len(alive) < 2

    def deal(self) -> dict:
        if self.in_hand:
            raise TableError("a hand is already in progress")
        if self.game_over:
            raise TableError("game over")
        if self.hand_no:
            self.game.advance_button()
        self.hand_no += 1
        self.result = None
        self._hand = self.game.hand()
        self._rec = {"hand_no": self.hand_no, "button": self.game.button, "hole": None,
                     "players": [{"seat": p.seat, "name": self.names[p.seat], "stack": p.stack}
                                 for p in self.game.players],
                     "events": []}
        self._emit({"type": "hand", "hand_no": self.hand_no, "button": self.game.button})
        self._run(None)
        return self.state()

    def act(self, kind: str, amount: int | None = None) -> dict:
        if self._view is None:
            raise TableError("not your turn")
        v = self._view
        if kind not in ACTIONS:
            raise TableError(f"unknown action {kind!r}")
        if kind == "check" and not v["can_check"]:
            raise TableError("cannot check: there is a bet to call")
        if kind == "call" and v["can_check"]:
            kind = "check"
        if kind == "raise":
            if not v["can_raise"]:
                raise TableError("cannot raise")
            if not isinstance(amount, int) or not v["min_raise_to"] <= amount <= v["allin_to"]:
                raise TableError(f"raise must be {v['min_raise_to']}-{v['allin_to']}")
        action = ("raise", amount) if kind == "raise" else (kind,)
        self._view = None
        self._run(action)
        return self.state()

    def _run(self, action):
        """Advance the hand: send `action` (None to start), let bots answer, stop at the hero's
        decision or the end of the hand."""
        try:
            view = next(self._hand) if action is None else self._hand.send(action)
            while view["seat"] != HERO:
                view = self._hand.send(self.bots[view["seat"]](view))
            self._view = view
        except StopIteration as done:
            self._hand = None
            self._view = None
            self.result = self._summarize(done.value)
            self._emit({"type": "result", **self.result})
            self._rec["hole"] = [_card(c) for c in done.value["holes"][HERO]]
            self.history.append(self._rec)
            self._rec = None
        except BaseException:
            # a bug must not wedge the table: void the hand (everyone gets back what they put
            # in) so the next deal() still works, then let the error surface
            for p in self.game.players:
                p.stack += p.contributed
                p.contributed = p.street_bet = 0
            self._hand = None
            self._view = None
            self._rec = None                         # a voided hand isn't history
            raise

    def _emit(self, ev: dict):
        self._events.append(ev)
        if self._rec is not None:
            self._rec["events"].append(ev)

    # -- hand history ----------------------------------------------------------
    def hands(self) -> list[dict]:
        """One line per finished hand still kept (oldest first), for a history list."""
        out = []
        for r in self.history:
            res = r["events"][-1]
            out.append({"hand_no": r["hand_no"], "net": res["net"][HERO],
                        "pot": sum(p["amount"] for p in res["pots"]),
                        "winners": sorted({w for p in res["pots"] for w in p["winners"]}),
                        "showdown": res["showdown"]})
        return out

    def hand_record(self, hand_no: int) -> dict | None:
        """A finished hand as the hero saw it: start stacks, the hero's cards, and the event log
        (bots' cards only where shown at showdown). None if unknown or no longer kept."""
        return next((r for r in self.history if r["hand_no"] == hand_no), None)

    def _summarize(self, res: dict) -> dict:
        board = res["board"]
        contenders = [s for s, f in enumerate(res["folded"]) if not f and res["holes"][s]]
        showdown = len(contenders) > 1
        shown = {}
        if showdown:
            for s in contenders:
                score = e.evaluate(res["holes"][s] + board)
                shown[s] = {"hole": [_card(c) for c in res["holes"][s]],
                            "hand": e.hand_name(score)}
        pots = [{"amount": p["amount"], "winners": p["winners"],
                 "hand": shown[p["winners"][0]]["hand"] if showdown and len(p["eligible"]) > 1
                 else None}
                for p in res["pots"]]
        return {"showdown": showdown, "shown": shown, "pots": pots,
                "net": [a - b for a, b in zip(res["stacks"], res["stacks_before"])]}

    def odds(self, raise_to: int | None = None, sims: int = 1500) -> dict:
        """The hero's numbers for the decision in front of them: pot odds (the equity a call
        needs), equity against the hands still in, EV of calling, outs, and a verdict. With
        `raise_to`, also the equity a caller would need against that raise. Computed once per
        decision (repeat calls are cached); read-only, no events consumed."""
        if self._view is None:
            raise TableError("not your turn")
        v = self._view
        if self._odds[0] is not v:
            hole, board = v["hole"], v["board"]
            opp = sum(not f for f in v["folded"]) - 1
            eq = odds.equity(hole, board, opp, sims)
            need = odds.pot_odds(v["to_call"], v["pot"])
            outs = odds.outs(hole, board)
            fair = 1 / (opp + 1)
            if v["to_call"]:
                verdict = "call_plus_ev" if eq >= need else "call_minus_ev"
            else:
                verdict = "value_bet" if eq > fair * 1.4 else "check"
            self._odds = (v, {
                "hand_no": self.hand_no, "street": v["street"], "to_call": v["to_call"],
                "pot": v["pot"], "opponents": opp, "pot_odds": round(need, 4),
                "equity": round(eq, 4), "fair_share": round(fair, 4),
                "ev": round(eq * (v["pot"] + v["to_call"]) - v["to_call"], 2),
                "verdict": verdict,
                "made": e.hand_name(e.evaluate(hole + board)) if board else None,
                "outs": [_card(c) for c in outs],
                # rule of 4 (two cards to come) / rule of 2 (one)
                "hit_by_river": min(1.0, len(outs) * (4 if len(board) == 3 else 2) / 100),
            })
        out = dict(self._odds[1])
        if raise_to is not None:
            if not v["can_raise"] or not v["min_raise_to"] <= raise_to <= v["allin_to"]:
                raise TableError(f"raise must be {v['min_raise_to']}-{v['allin_to']}")
            pot_after = v["pot"] + raise_to - v["my_street_bet"]
            their_call = raise_to - v["current_bet"]
            out["raise_to"] = raise_to
            out["caller_needs"] = round(odds.pot_odds(their_call, pot_after), 4)
        return out

    # -- snapshot --------------------------------------------------------------
    def state(self) -> dict:
        g = self.game
        players = []
        for p in g.players:
            hole = None
            if p.seat == HERO and p.hole:
                hole = [_card(c) for c in p.hole]
            elif self.result and p.seat in self.result["shown"]:
                hole = self.result["shown"][p.seat]["hole"]
            players.append({
                "seat": p.seat, "name": self.names[p.seat], "bot": p.seat != HERO,
                "stack": p.stack, "street_bet": p.street_bet if self.in_hand else 0,
                "folded": p.folded, "allin": p.allin,
                "out": p.stack == 0 and (not self.in_hand or not p.hole),
                "in_hand": bool(p.hole), "hole": hole,
            })
        to_act = None
        if self._view:
            v = self._view
            to_act = {k: v[k] for k in ("to_call", "can_check", "can_raise",
                                        "min_raise_to", "allin_to")}
        events, self._events = self._events, []
        over = self.game_over and not self.in_hand
        alive = [p.seat for p in g.players if p.stack > 0]
        return {
            "hand_no": self.hand_no, "in_hand": self.in_hand, "street": self.street,
            "button": g.button, "sb": g.sb, "bb": g.bb,
            "board": [_card(c) for c in g.board], "pot": g.pot_total() if self.in_hand else 0,
            "players": players, "hero": HERO, "to_act": to_act, "result": self.result,
            "game_over": over,
            "winner": alive[0] if over and len(alive) == 1 else None,    # None: you busted
            "events": events,
        }
