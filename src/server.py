"""HTTP JSON API over table.Table, plus the static web client. All game logic is in the engine
and table.py; this file only maps requests to Table calls, so the iOS/Android apps can use the
same /api/v1 endpoints the web client does.

    cd src && uvicorn server:app --host 127.0.0.1 --port 8092

    POST /api/v1/tables                 {players, stack, sb, bb, token?}  -> {id, state, ranked}
    GET  /api/v1/tables/{id}                                      -> state
    POST /api/v1/tables/{id}/deal                                 -> state
    POST /api/v1/tables/{id}/act        {action, amount?}         -> state
    GET  /api/v1/tables/{id}/odds[?raise_to=N]  hero's pot odds, equity, EV, outs (hero's turn)
    GET  /api/v1/tables/{id}/hands               finished hands kept for replay (last 50)
    GET  /api/v1/tables/{id}/hands/{n}           one hand's record: stacks, your cards, events
    POST /api/v1/session                {token}  -> {account, table?, state?, ranked?}  (signed in)
    POST /api/v1/leaderboard            {token?} -> {top, you, ranked}
    GET  /api/v1/health

`state` is Table.state(); its `events` list holds what happened since the previous response.
A table id is the only credential: whoever holds it plays that seat. Tables live in memory
and idle ones are evicted.

Signed-in players (an npone.dev account; `token` comes from https://npone.dev/auth/token?aud=poker
and is checked at npone.dev's /auth/introspect) also get: their table saved between hands, so it
comes back after a reload, on another device or after a restart; and lifetime stats on the
leaderboard, counted only at the ranked settings (RANKED). Guests start fresh every time.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import urllib.error
import urllib.request
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from store import DEFAULT_PATH, Store
from table import HERO, Table, TableError

MAX_TABLES = 2000                   # shortcut: in-memory store, single process; a DB if scaled
IDLE_SECONDS = 2 * 3600             # only idle tables are evicted; when full of live ones -> 503
CREATE_LIMIT = (20, 600)            # new tables per client IP per window (count, seconds)
AUTH_LIMIT = (120, 600)             # sign-in checks (each one asks npone.dev) per client IP
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
AUTH_URL = os.environ.get("POKER_AUTH_URL", "http://127.0.0.1:8090")   # npone-site, same box
RANKED = {"players": 4, "stack": 100, "sb": 1, "bb": 2}   # only this counts on the leaderboard
BOOT = secrets.token_hex(6)         # tells "server restarted mid-hand" from "player walked away"


class NewTable(BaseModel):
    players: int = Field(4, ge=2, le=8)
    stack: int = Field(100, ge=10, le=1_000_000)
    sb: int = Field(1, ge=1)
    bb: int = Field(2, ge=1)
    token: str | None = Field(None, max_length=2000)


class Token(BaseModel):
    token: str | None = Field(None, max_length=2000)


class Action(BaseModel):
    action: str = Field(..., max_length=10)
    amount: int | None = Field(None, ge=0, le=10_000_000)


class _Entry:
    def __init__(self, table: Table):
        self.table = table
        self.lock = threading.Lock()                 # the hand generator is not re-entrant
        self.seen = time.monotonic()
        self.tid = None
        self.account = None                          # signed-in owner's account id, if any
        self.ranked = False
        self.recorded = table.hand_no                # last hand counted in the owner's stats


_tables: OrderedDict[str, _Entry] = OrderedDict()
_store_lock = threading.Lock()
_creates: dict[str, list[float]] = {}
_auth_tries: dict[str, list[float]] = {}
_by_account: dict[str, str] = {}                     # account id -> its live table id
_account_lock = threading.Lock()                     # binding/replacing an account's table
_db: Store | None = None


def store() -> Store:
    global _db
    if _db is None:
        _db = Store(os.environ.get("POKER_DB") or DEFAULT_PATH)
    return _db

app = FastAPI(title="poker", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(RequestValidationError)
def _invalid(request: Request, exc: RequestValidationError):
    # the default handler echoes the input back, and fails (500) on NaN/Infinity
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": [str(x) for x in err.get("loc", ())], "msg": str(err.get("msg", ""))}
        for err in exc.errors()]})


def _evict():
    """Drop idle tables (oldest first; _tables is kept in last-used order)."""
    now = time.monotonic()
    while _tables:
        tid, ent = next(iter(_tables.items()))
        if now - ent.seen <= IDLE_SECONDS:
            break
        del _tables[tid]


def _rate_limited(ip: str, seen: dict[str, list[float]], limit: tuple[int, int]) -> bool:
    count, window = limit
    now = time.monotonic()
    for k in [k for k, ts in seen.items() if now - ts[-1] > window]:
        del seen[k]                                  # forget clients idle past the window
    ts = [t for t in seen.get(ip, []) if now - t <= window]
    if len(ts) >= count:
        seen[ip] = ts
        return True
    seen[ip] = ts + [now]
    return False


def _get(tid: str) -> _Entry:
    with _store_lock:
        ent = _tables.get(tid)
        if ent is None:
            raise HTTPException(404, "no such table (expired or server restarted)")
        ent.seen = time.monotonic()
        _tables.move_to_end(tid)
        return ent


def _call(tid: str, fn, persist: bool = False):
    ent = _get(tid)
    with ent.lock:
        try:
            out = fn(ent.table)
        except TableError as err:
            raise HTTPException(400, str(err))
        if persist and ent.account:
            _persist(ent)
        return out


def _ip(request: Request) -> str:
    # behind the Cloudflare tunnel every request comes from localhost; CF names the client
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


# -- signed-in players ------------------------------------------------------------
def _introspect(token: str) -> tuple[str, str | None] | None:
    """(account id, display name) for a valid npone.dev token, else None."""
    req = urllib.request.Request(f"{AUTH_URL}/auth/introspect", method="POST",
                                 data=json.dumps({"aud": "poker", "token": token}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.load(r)
    except urllib.error.HTTPError as err:
        if err.code == 401:
            return None
        raise HTTPException(503, "sign-in service unavailable")
    except (OSError, ValueError):
        raise HTTPException(503, "sign-in service unavailable")
    return (body["id"], body.get("name")) if body.get("ok") else None


def _account(token: str | None, ip: str) -> str:
    with _store_lock:                                # each check is a call to npone.dev: bounded
        if _rate_limited(ip, _auth_tries, AUTH_LIMIT):
            raise HTTPException(429, "too many sign-in checks; try again in a few minutes")
    who = _introspect(token) if token else None
    if who is None:
        raise HTTPException(401, "not signed in (or the sign-in expired); reload to retry")
    store().touch(*who)
    return who[0]


def _persist(ent: _Entry):
    """After a deal or act on a signed-in player's table (under its lock): count a finished
    hand and save the table, or mark the chips at risk while a ranked hand runs. A replaced
    table never gets here: _retire clears ent.account under the same lock _call holds, so
    whichever of them takes the lock first decides (hand counted, or hand forfeit), never both
    or neither."""
    t, acct, db = ent.table, ent.account, store()
    if t.in_hand:
        if ent.ranked:
            db.set_pending(acct, {"hand_no": t.hand_no, "boot": BOOT,
                                  "at_risk": t.game.players[HERO].contributed})
        return
    if t.result is None or t.hand_no == ent.recorded:
        return
    ent.recorded = t.hand_no
    won = sum(p["amount"] // len(p["winners"]) for p in t.result["pots"] if HERO in p["winners"])
    db.finish_hand(acct, ent.ranked, t.result["net"][HERO], won,
                   win=t.game_over and t.game.players[HERO].stack > 0,
                   snap=None if t.game_over else t.snapshot())   # game over: next time is fresh


def _forfeit(acct: str, at_risk: int):
    """A ranked hand was abandoned (new game, or walked away until evicted): the chips the
    player had in the pot count as lost, as if they had folded."""
    if at_risk:
        store().add_hand(acct, -at_risk, 0)


def _retire(acct: str):
    """Put away the player's previous table before they start another (under _account_lock)."""
    db, old = store(), _by_account.pop(acct, None)
    with _store_lock:
        ent = _tables.pop(old, None) if old else None
    if ent is not None:
        with ent.lock:                               # waits out a request already running on it
            if ent.ranked and ent.table.in_hand:
                _forfeit(acct, ent.table.game.players[HERO].contributed)
            ent.account = None                       # retired: nothing more is counted or saved
    else:
        saved = db.load_table(acct)
        p = saved and saved["pending"]
        if p and saved["ranked"] and p["boot"] == BOOT:
            _forfeit(acct, p["at_risk"])
    db.drop_table(acct)


def _add(t: Table, ip: str | None = None) -> tuple[str, _Entry]:
    tid, ent = secrets.token_urlsafe(16), _Entry(t)
    ent.tid = tid
    with _store_lock:
        if ip is not None and _rate_limited(ip, _creates, CREATE_LIMIT):
            raise HTTPException(429, "too many new tables; try again in a few minutes")
        _evict()
        if len(_tables) >= MAX_TABLES:
            raise HTTPException(503, "server is full; try again later")
        _tables[tid] = ent
    return tid, ent


@app.get("/api/v1/health")
def health():
    return {"ok": True, "tables": len(_tables)}


@app.post("/api/v1/tables")
def create_table(req: NewTable, request: Request):
    ip = _ip(request)
    try:
        t = Table(players=req.players, stack=req.stack, sb=req.sb, bb=req.bb)
    except TableError as err:
        raise HTTPException(400, str(err))
    acct = _account(req.token, ip) if req.token else None
    if not acct:
        tid, _ = _add(t, ip)
        return {"id": tid, "state": t.state(), "ranked": False}
    ranked = {"players": req.players, "stack": req.stack, "sb": req.sb, "bb": req.bb} == RANKED
    with _account_lock:                              # one bound table per account, ever
        tid, ent = _add(t, ip)
        _retire(acct)
        ent.account, ent.ranked = acct, ranked
        _by_account[acct] = tid
        if ranked:
            store().add_session(acct)
        store().save_table(acct, t.snapshot(), ranked)
    return {"id": tid, "state": t.state(), "ranked": ranked}


@app.post("/api/v1/session")
def session(req: Token, request: Request):
    """A signed-in player's way back in: their live table, or the one saved between hands."""
    acct = _account(req.token, _ip(request))
    db = store()
    with _account_lock:
        tid = _by_account.get(acct)
        with _store_lock:
            ent = _tables.get(tid) if tid else None
        saved = db.load_table(acct) if ent is None else None
        if saved:
            t = Table.restore(saved["snap"])         # as it was before any unfinished hand
            p = saved["pending"]
            # walked away mid-hand and the table was evicted: the chips in the pot are lost, in
            # the stats and on the table. (From an earlier boot, a restart cut it short: void.)
            if p and saved["ranked"] and p["boot"] == BOOT and p["at_risk"]:
                _forfeit(acct, p["at_risk"])
                me = t.game.players[HERO]
                lost = min(p["at_risk"], me.stack)
                me.stack -= lost
                next((q for q in t.game.players[1:] if q.stack > 0), t.game.players[1]).stack += lost
            tid, ent = _add(t)
            ent.account, ent.ranked = acct, saved["ranked"]
            _by_account[acct] = tid
            if t.game_over:
                db.drop_table(acct)
            else:
                db.save_table(acct, t.snapshot(), saved["ranked"])
    out = {"account": db.stats(acct), "ranked_settings": RANKED}
    if ent is not None:
        with ent.lock:
            out |= {"table": tid, "state": ent.table.state(), "ranked": ent.ranked}
    return out


@app.post("/api/v1/leaderboard")
def leaderboard(req: Token, request: Request):
    you = None
    if req.token:
        try:
            you = store().stats(_account(req.token, _ip(request)))
        except HTTPException:
            pass                                     # an expired token just means no "you" row
    return {"top": store().leaderboard(), "you": you, "ranked_settings": RANKED}


@app.get("/api/v1/tables/{tid}")
def get_table(tid: str):
    return _call(tid, lambda t: t.state())


@app.post("/api/v1/tables/{tid}/deal")
def deal(tid: str):
    return _call(tid, lambda t: t.deal(), persist=True)


@app.post("/api/v1/tables/{tid}/act")
def act(tid: str, req: Action):
    return _call(tid, lambda t: t.act(req.action, req.amount), persist=True)


@app.get("/api/v1/tables/{tid}/odds")
def table_odds(tid: str, raise_to: int | None = Query(None, ge=0, le=10_000_000)):
    return _call(tid, lambda t: t.odds(raise_to))


@app.middleware("http")
async def _revalidate_web(request: Request, call_next):
    # Cloudflare's edge otherwise keeps app.js/style.css for hours after a deploy
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/v1/tables/{tid}/hands")
def table_hands(tid: str):
    return _call(tid, lambda t: t.hands())


@app.get("/api/v1/tables/{tid}/hands/{hand_no}")
def table_hand(tid: str, hand_no: int):
    rec = _call(tid, lambda t: t.hand_record(hand_no))
    if rec is None:
        raise HTTPException(404, "no such hand (only the last 50 are kept)")
    return rec


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
