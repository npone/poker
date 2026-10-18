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
