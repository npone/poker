"""Persistence for signed-in players: lifetime stats for the leaderboard, and each player's table
saved between hands so it survives reloads, other devices and server restarts. Guests never
reach this module. SQLite, one connection per call (the server runs requests in threads).

An account id is the opaque per-app id npone.dev's /auth/introspect hands out; no email is
stored here.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "poker.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, name TEXT,
    net INTEGER NOT NULL DEFAULT 0,        -- ranked chips won (lost if negative), all sessions
    hands INTEGER NOT NULL DEFAULT 0, sessions INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,       -- ranked tables won outright
    best_pot INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS saved (
    id TEXT PRIMARY KEY,                   -- account id: one table per player
    snap TEXT NOT NULL, ranked INTEGER NOT NULL,
    pending TEXT,                          -- JSON {hand_no, boot, at_risk} while a ranked hand runs
    updated REAL NOT NULL);
"""


class Store:
    def __init__(self, path: str | os.PathLike = DEFAULT_PATH):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()                # one writer at a time; reads are cheap
        with self._db() as db:
            db.executescript(_SCHEMA)
        os.chmod(self.path, 0o600)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _write(self, sql: str, args=()):
        with self._lock, self._db() as db:
            db.execute(sql, args)

    # -- accounts ---------------------------------------------------------------
    def touch(self, acct: str, name: str | None):
        now = time.time()
        self._write("INSERT INTO accounts (id, name, created, updated) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET name = excluded.name, updated = excluded.updated",
                    (acct, name, now, now))

    def add_session(self, acct: str):
        self._write("UPDATE accounts SET sessions = sessions + 1, updated = ? WHERE id = ?",
                    (time.time(), acct))

    def add_hand(self, acct: str, net: int, won: int):
        self._write("UPDATE accounts SET net = net + ?, hands = hands + 1, "
                    "best_pot = MAX(best_pot, ?), updated = ? WHERE id = ?",
                    (net, won, time.time(), acct))

    def add_win(self, acct: str):
        self._write("UPDATE accounts SET wins = wins + 1, updated = ? WHERE id = ?",
                    (time.time(), acct))

    def stats(self, acct: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT * FROM accounts WHERE id = ?", (acct,)).fetchone()
            if r is None:
                return None
            rank = None
            if r["hands"]:
                rank = 1 + db.execute("SELECT COUNT(*) FROM accounts WHERE hands > 0 AND "
                                      "(net > ? OR (net = ? AND hands < ?))",
                                      (r["net"], r["net"], r["hands"])).fetchone()[0]
        return _public(r) | {"rank": rank}

    def leaderboard(self, limit: int = 25) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM accounts WHERE hands > 0 "
                              "ORDER BY net DESC, hands ASC LIMIT ?", (limit,)).fetchall()
        return [_public(r) | {"rank": i + 1} for i, r in enumerate(rows)]

    # -- saved tables -------------------------------------------------------------
    def save_table(self, acct: str, snap: dict, ranked: bool):
        self._write("INSERT INTO saved (id, snap, ranked, pending, updated) VALUES (?, ?, ?, NULL, ?) "
                    "ON CONFLICT(id) DO UPDATE SET snap = excluded.snap, ranked = excluded.ranked, "
                    "pending = NULL, updated = excluded.updated",
                    (acct, json.dumps(snap), int(ranked), time.time()))

    def set_pending(self, acct: str, pending: dict | None):
        self._write("UPDATE saved SET pending = ?, updated = ? WHERE id = ?",
                    (json.dumps(pending) if pending else None, time.time(), acct))

    def load_table(self, acct: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT * FROM saved WHERE id = ?", (acct,)).fetchone()
        if r is None:
            return None
        return {"snap": json.loads(r["snap"]), "ranked": bool(r["ranked"]),
                "pending": json.loads(r["pending"]) if r["pending"] else None}

    def drop_table(self, acct: str):
        self._write("DELETE FROM saved WHERE id = ?", (acct,))


def _public(r) -> dict:
    return {"name": r["name"] or f"Player {r['id'][:4]}", "net": r["net"], "hands": r["hands"],
            "sessions": r["sessions"], "wins": r["wins"], "best_pot": r["best_pot"]}
