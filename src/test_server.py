"""Tests for server.py: the HTTP contract the web and mobile clients depend on."""
import random

from fastapi.testclient import TestClient

import server

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
    for _ in range(200):
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


def test_health_and_web_client_served():
    assert client.get("/api/v1/health").json()["ok"]
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_eviction_caps_table_count(monkeypatch):
    monkeypatch.setattr(server, "MAX_TABLES", 3)
    ids = [_new()["id"] for _ in range(5)]
    assert len(server._tables) <= 3
    assert client.get(f"/api/v1/tables/{ids[0]}").status_code == 404
    assert client.get(f"/api/v1/tables/{ids[-1]}").status_code == 200
