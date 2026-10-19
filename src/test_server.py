"""Tests for server.py: the HTTP contract the web and mobile clients depend on."""
import json
import random

import pytest
from fastapi.testclient import TestClient

import server
from store import Store

client = TestClient(server.app)


def _new(**kw):
    r = client.post("/api/v1/tables", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_play_a_session_over_http():
    rng = random.Random(7)
    body = _new(players=3, stack=40)
    tid, s = body["id"], body["state"]
    assert s["hand_no"] == 0 and not s["in_hand"]
    for _ in range(3000):                        # equity bots are careful; games run long
        if s["game_over"]:
            break
        s = client.post(f"/api/v1/tables/{tid}/deal").json()
        while s["in_hand"]:
            a = s["to_act"]
            kind = rng.choice(["call", "fold", "allin"] + (["check"] if a["can_check"] else []))
            r = client.post(f"/api/v1/tables/{tid}/act", json={"action": kind})
            assert r.status_code == 200, r.text
            s = r.json()
        assert sum(p["stack"] for p in s["players"]) == 120
    assert s["game_over"]
    assert client.get(f"/api/v1/tables/{tid}").json()["game_over"]


def test_errors_are_4xx():
    assert client.get("/api/v1/tables/nope").status_code == 404
    assert client.post("/api/v1/tables", json={"players": 9}).status_code == 422
    assert client.post("/api/v1/tables", json={"sb": 5, "bb": 2}).status_code == 400
    tid = _new()["id"]
    assert client.post(f"/api/v1/tables/{tid}/act", json={"action": "fold"}).status_code == 400
    s = client.post(f"/api/v1/tables/{tid}/deal").json()
    assert client.post(f"/api/v1/tables/{tid}/deal").status_code == (400 if s["in_hand"] else 200)
    if s["in_hand"]:
        r = client.post(f"/api/v1/tables/{tid}/act", json={"action": "raise", "amount": 10**6})
        assert r.status_code == 400


def test_odds_endpoint():
    tid = _new(players=3)["id"]
    assert client.get(f"/api/v1/tables/{tid}/odds").status_code == 400      # no hand yet
    s = client.post(f"/api/v1/tables/{tid}/deal").json()
    while not s["to_act"]:
        s = client.post(f"/api/v1/tables/{tid}/deal").json()
    o = client.get(f"/api/v1/tables/{tid}/odds").json()
    assert {"pot_odds", "equity", "outs", "opponents", "to_call"} <= set(o)


def test_hand_history_endpoints():
    tid = _new(players=3)["id"]
    assert client.get(f"/api/v1/tables/{tid}/hands").json() == []
    s = client.post(f"/api/v1/tables/{tid}/deal").json()
    while s["in_hand"]:
        s = client.post(f"/api/v1/tables/{tid}/act", json={"action": "fold"}).json()
    hands = client.get(f"/api/v1/tables/{tid}/hands").json()
    assert [h["hand_no"] for h in hands] == [1]
    rec = client.get(f"/api/v1/tables/{tid}/hands/1").json()
    assert rec["hole"] and rec["events"][-1]["type"] == "result"
    assert client.get(f"/api/v1/tables/{tid}/hands/2").status_code == 404


def test_web_files_revalidate():
    assert client.get("/app.js").headers["cache-control"] == "no-cache"


def test_health_and_web_client_served():
    assert client.get("/api/v1/health").json()["ok"]
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_full_server_refuses_instead_of_evicting_live_tables(monkeypatch):
    server._tables.clear()
    monkeypatch.setattr(server, "MAX_TABLES", 3)
    ids = [_new()["id"] for _ in range(3)]
    assert client.post("/api/v1/tables", json={}).status_code == 503
    assert all(client.get(f"/api/v1/tables/{t}").status_code == 200 for t in ids)
    monkeypatch.setattr(server, "IDLE_SECONDS", -1)              # now every table counts as idle
    assert client.post("/api/v1/tables", json={}).status_code == 200
    assert client.get(f"/api/v1/tables/{ids[0]}").status_code == 404


def test_new_tables_rate_limited_per_client(monkeypatch):
    monkeypatch.setattr(server, "CREATE_LIMIT", (2, 600))
    h = {"cf-connecting-ip": "203.0.113.7"}
    codes = [client.post("/api/v1/tables", json={}, headers=h).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    other = client.post("/api/v1/tables", json={}, headers={"cf-connecting-ip": "203.0.113.8"})
    assert other.status_code == 200


def test_non_finite_numbers_are_422_not_500():
    for raw in ('{"players": NaN}', '{"stack": Infinity}', '{"players": 1e400}'):
        r = client.post("/api/v1/tables", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 422, (raw, r.status_code)
    tid = _new()["id"]
    r = client.post(f"/api/v1/tables/{tid}/act", content='{"action": "raise", "amount": NaN}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


# -- signed-in players -----------------------------------------------------------

ACCOUNTS = {"tok-ann": ("acct-ann", "Ann"), "tok-bo": ("acct-bo", None)}


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_db", Store(tmp_path / "poker.db"))
    monkeypatch.setattr(server, "_introspect", lambda tok: ACCOUNTS.get(tok))
    monkeypatch.setattr(server, "_by_account", {})
    return server._db


def _finish_hands(tid, s, n, rng):
    """Play n hands to the end with random legal actions; returns the hero's total net."""
    net = 0
    for _ in range(n):
        if s["game_over"]:
            break
        s = client.post(f"/api/v1/tables/{tid}/deal").json()
        while s["in_hand"]:
            a = s["to_act"]
            kind = rng.choice(["call", "fold"] + (["check"] if a["can_check"] else []))
            s = client.post(f"/api/v1/tables/{tid}/act", json={"action": kind}).json()
        net += s["result"]["net"][0]
    return net, s


def test_guest_tables_touch_no_storage(accounts):
    body = _new(players=3)
    assert body["ranked"] is False
    assert client.post("/api/v1/session", json={"token": None}).status_code == 401
    assert client.post("/api/v1/session", json={"token": "forged"}).status_code == 401
    assert client.post("/api/v1/leaderboard", json={}).json()["top"] == []


def test_ranked_progress_counts_and_survives_restart(accounts):
    rng = random.Random(4)
    body = _new(players=3, token="tok-ann")                          # defaults are the ranked ones
    assert body["ranked"] is True
    tid = body["id"]
    net, s = _finish_hands(tid, body["state"], 6, rng)
    me = accounts.stats("acct-ann")
    assert me["hands"] == s["hand_no"] and me["net"] == net and me["sessions"] == 1
    board = client.post("/api/v1/leaderboard", json={"token": "tok-ann"}).json()
    assert board["top"][0]["name"] == "Ann" and board["you"]["rank"] == 1
    assert "acct-ann" not in json.dumps(board)                        # ids stay private

    # same server: session hands back the live table
    again = client.post("/api/v1/session", json={"token": "tok-ann"}).json()
    assert again["table"] == tid
    if s["game_over"]:
        return
    # "restart": memory gone, the saved table comes back where it was
    stacks = [p["stack"] for p in s["players"]]
    server._tables.clear(); server._by_account.clear()
    back = client.post("/api/v1/session", json={"token": "tok-ann"}).json()
    assert back["table"] != tid and back["state"]["hand_no"] == s["hand_no"]
    assert [p["stack"] for p in back["state"]["players"]] == stacks


def test_abandoned_ranked_hand_is_forfeit_but_restart_is_void(accounts):
    body = _new(players=2, token="tok-bo")
    tid = body["id"]
    s = client.post(f"/api/v1/tables/{tid}/deal").json()
    while not s["in_hand"]:                                           # want a live hand
        s = client.post(f"/api/v1/tables/{tid}/deal").json()
    if s["to_act"]["can_raise"]:
        s = client.post(f"/api/v1/tables/{tid}/act", json={"action": "raise",
                        "amount": s["to_act"]["min_raise_to"]}).json()
    if not s["in_hand"]:
        return                                                        # the bot folded: nothing at risk
    at_risk = 100 - s["players"][0]["stack"]
    before = accounts.stats("acct-bo")["net"]
    # walk away until evicted (same boot) -> the chips in the pot are lost
    server._tables.clear()
    back = client.post("/api/v1/session", json={"token": "tok-bo"}).json()
    assert accounts.stats("acct-bo")["net"] == before - at_risk
    assert back["state"]["players"][0]["stack"] == 100 - at_risk
    assert sum(p["stack"] for p in back["state"]["players"]) == 200

    # mid-hand again, but now the server restarts (new boot): void, nothing charged
    tid = back["table"]
    s = client.post(f"/api/v1/tables/{tid}/deal").json()
    if s["in_hand"]:
        net = accounts.stats("acct-bo")["net"]
        server._tables.clear()
        server.BOOT, boot = "another-boot", server.BOOT
        try:
            client.post("/api/v1/session", json={"token": "tok-bo"})
        finally:
            server.BOOT = boot
        assert accounts.stats("acct-bo")["net"] == net


def test_practice_settings_are_saved_but_not_ranked(accounts):
    body = _new(players=3, stack=500, token="tok-ann")
    assert body["ranked"] is False
    _finish_hands(body["id"], body["state"], 2, random.Random(1))
    assert accounts.stats("acct-ann")["hands"] == 0
    assert accounts.load_table("acct-ann") is not None                # but it is kept to resume
