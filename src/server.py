"""HTTP JSON API over table.Table, plus the static web client. All game logic is in the engine
and table.py; this file only maps requests to Table calls, so the iOS/Android apps can use the
same /api/v1 endpoints the web client does.

    cd src && uvicorn server:app --host 127.0.0.1 --port 8092

    POST /api/v1/tables                 {players, stack, sb, bb}  -> {id, state}
    GET  /api/v1/tables/{id}                                      -> state
    POST /api/v1/tables/{id}/deal                                 -> state
    POST /api/v1/tables/{id}/act        {action, amount?}         -> state
    GET  /api/v1/health

`state` is Table.state(); its `events` list holds what happened since the previous response.
A table id is the only credential: whoever holds it plays that seat. Tables live in memory
(lost on restart) and idle ones are evicted.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from table import Table, TableError

MAX_TABLES = 2000                   # shortcut: in-memory store, single process; a DB if scaled
IDLE_SECONDS = 6 * 3600
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class NewTable(BaseModel):
    players: int = Field(4, ge=2, le=8)
    stack: int = Field(100, ge=10, le=1_000_000)
    sb: int = Field(1, ge=1)
    bb: int = Field(2, ge=1)


class Action(BaseModel):
    action: str = Field(..., max_length=10)
    amount: int | None = Field(None, ge=0, le=10_000_000)


class _Entry:
    def __init__(self, table: Table):
        self.table = table
        self.lock = threading.Lock()                 # the hand generator is not re-entrant
        self.seen = time.monotonic()


_tables: OrderedDict[str, _Entry] = OrderedDict()
_store_lock = threading.Lock()

app = FastAPI(title="poker", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _evict():
    now = time.monotonic()
    while _tables:
        tid, ent = next(iter(_tables.items()))
        if len(_tables) > MAX_TABLES or now - ent.seen > IDLE_SECONDS:
            del _tables[tid]
        else:
            break


def _get(tid: str) -> _Entry:
    with _store_lock:
        ent = _tables.get(tid)
        if ent is None:
            raise HTTPException(404, "no such table (expired or server restarted)")
        ent.seen = time.monotonic()
        _tables.move_to_end(tid)
        return ent


def _call(tid: str, fn):
    ent = _get(tid)
    with ent.lock:
        try:
            return fn(ent.table)
        except TableError as err:
            raise HTTPException(400, str(err))


@app.get("/api/v1/health")
def health():
    return {"ok": True, "tables": len(_tables)}


@app.post("/api/v1/tables")
def create_table(req: NewTable):
    try:
        t = Table(players=req.players, stack=req.stack, sb=req.sb, bb=req.bb)
    except TableError as err:
        raise HTTPException(400, str(err))
    tid = secrets.token_urlsafe(16)
    with _store_lock:
        _tables[tid] = _Entry(t)
        _evict()
    return {"id": tid, "state": t.state()}


@app.get("/api/v1/tables/{tid}")
def get_table(tid: str):
    return _call(tid, lambda t: t.state())


@app.post("/api/v1/tables/{tid}/deal")
def deal(tid: str):
    return _call(tid, lambda t: t.deal())


@app.post("/api/v1/tables/{tid}/act")
def act(tid: str, req: Action):
    return _call(tid, lambda t: t.act(req.action, req.amount))


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
