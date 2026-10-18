// Web client for the poker server. Holds no game rules: it renders /api/v1 snapshots and
// replays each snapshot's `events` so the bots' moves are visible one by one.
"use strict";

const API = "api/v1";
const STORE_KEY = "poker.table";
const SUIT = { c: "♣", d: "♦", h: "♥", s: "♠" };
const DELAY = { action: 600, street: 750, result: 300, hero: 120 };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const $ = (id) => document.getElementById(id);
let tid = null;          // table id: the only credential for our seat
let cur = null;          // last server snapshot
let busy = false;        // replaying events or waiting on the server
let disp = null;         // what the felt shows mid-replay: {stacks, bets, board, pot, say}

// ── storage (per-viewer convenience only) ───────────────────────────────
function loadId() { try { return localStorage.getItem(STORE_KEY); } catch { return null; } }
function saveId(v) {
  try { v ? localStorage.setItem(STORE_KEY, v) : localStorage.removeItem(STORE_KEY); } catch {}
}

// ── server ───────────────────────────────────────────────────────────────
async function api(path, body) {
  const res = await fetch(`${API}/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : res.statusText;
    const err = new Error(msg || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// ── rendering helpers ────────────────────────────────────────────────────
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// only cards that were not on screen last render get the deal animation
let shownPrev = new Set(), shownNow = new Set();
function flushShown() { shownPrev = shownNow; shownNow = new Set(); }

function cardEl(code, key) {
  const fresh = key !== undefined && !shownPrev.has(key + code);
  if (key !== undefined) shownNow.add(key + code);
  const c0 = cardEl0(code);
  if (fresh) c0.classList.add("deal");
  return c0;
}

function cardEl0(code) {
  if (!code) return el("div", "pcard back");
  const rank = code[0] === "T" ? "10" : code[0];
  const suit = code[1];
  const c = el("div", "pcard" + (suit === "h" || suit === "d" ? " red" : ""));
  c.setAttribute("aria-label", code);
  c.append(el("span", "r", rank), el("span", "s", SUIT[suit]));
  return c;
}

function cardText(code) { return (code[0] === "T" ? "10" : code[0]) + SUIT[code[1]]; }
function name(seat) { return cur.players[seat].name; }

function seatPositions(n, hero) {
  // hero at the bottom centre, the rest clockwise around the oval
  const narrow = matchMedia("(max-width: 640px)").matches;
  const rx = narrow ? 47 : 50, ry = narrow ? 50 : 54;
  const out = [];
  for (let k = 0; k < n; k++) {
    const a = (Math.PI / 2) + (k * 2 * Math.PI) / n;
    out[(hero + k) % n] = { left: 50 + rx * Math.cos(a), top: 50 + ry * Math.sin(a) };
  }
  return out;
}

let flushQueued = false;
function queueFlush() {
  if (!flushQueued) { flushQueued = true; requestAnimationFrame(() => { flushQueued = false; flushShown(); }); }
}

function renderSeats(state, { acting = null, winners = [] } = {}) {
  queueFlush();
  const seats = $("seats");
  seats.replaceChildren();
  const pos = seatPositions(state.players.length, state.hero);
  for (const p of state.players) {
    const s = el("div", "seat");
    s.style.left = pos[p.seat].left + "%";
    s.style.top = pos[p.seat].top + "%";
    const folded = disp ? !!disp.folded[p.seat] : p.folded;
    if (p.out) s.classList.add("out");
    else if (folded && p.in_hand) s.classList.add("folded");
    if (acting === p.seat) s.classList.add("acting");
    if (winners.includes(p.seat)) s.classList.add("winner");

    const cards = el("div", "cards");
    if (p.in_hand && !(folded && p.bot)) {
      const hole = (p.bot && disp && !disp.revealed) ? [null, null] : (p.hole || [null, null]);
      hole.forEach((c, i) => cards.append(cardEl(c, `s${p.seat}.${i}:`)));
    }
    const plate = el("div", "plate");
    const stack = disp ? disp.stacks[p.seat] : p.stack;
    plate.append(el("div", "name", p.name + (p.allin && p.in_hand ? " · all-in" : "")),
                 el("div", "stack", `${stack} chips`));
    const bet = disp ? disp.bets[p.seat] : p.street_bet;
    const say = el("div", "say" + (disp && disp.say[p.seat] ? " show" : ""),
                   (disp && disp.say[p.seat]) || "");
    s.append(say, cards, plate, el("div", "bet", bet ? String(bet) : ""));
    if (p.seat === state.button) s.append(el("div", "dealer", "D"));
    seats.append(s);
  }
}

function renderCenter(board, pot) {
  queueFlush();
  $("board").replaceChildren(...board.map((c, i) => cardEl(c, `b${i}:`)));
  $("pot").textContent = pot ? `Pot ${pot}` : "";
}

function log(text, cls) {
  const li = el("li", cls || "", text);
  $("log").append(li);
  li.scrollIntoView({ block: "nearest" });
}

const VERB = { fold: "folds", check: "checks", call: "calls", bet: "bets", raise: "raises to", allin: "is all-in" };
function describe(ev) {
  const who = ev.seat === cur.hero ? "You" : name(ev.seat);
  const verb = ev.seat === cur.hero
    ? { fold: "fold", check: "check", call: "call", bet: "bet", raise: "raise to", allin: "go all-in" }[ev.action]
    : VERB[ev.action];
  const amt = ev.action === "call" ? ` ${ev.chips}`
    : (ev.action === "bet" || ev.action === "raise" || ev.action === "allin") ? ` ${ev.street_bet}` : "";
  return `${who} ${verb}${amt}`;
}

function resultText(result) {
  return result.pots.map((p) => {
    const who = p.winners.map((w) => (w === cur.hero ? "You" : name(w))).join(" & ");
    const verb = p.winners.length === 1 && p.winners[0] === cur.hero ? "win" : (p.winners.length > 1 ? "split" : "wins");
    return `${who} ${verb} ${p.amount}` + (p.hand ? ` with ${p.hand}` : "");
  }).join(" · ");
}

// ── replaying events ─────────────────────────────────────────────────────
const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? Math.min(ms, 150) : ms));

async function replay(state) {
  const prev = cur;
  cur = state;
  if (!disp) {
    disp = { stacks: state.players.map((p) => p.stack), bets: state.players.map((p) => p.street_bet),
             board: [...state.board], pot: state.pot, say: {},
             folded: Object.fromEntries(((prev && prev.players) || []).map((p) => [p.seat, p.folded])) };
    disp.board = (prev && prev.in_hand) ? [...prev.board] : disp.board;
    if (prev && prev.in_hand) { disp.stacks = prev.players.map((p) => p.stack); disp.bets = prev.players.map((p) => p.street_bet); disp.pot = prev.pot; }
  }
  for (const ev of state.events) {
    if (ev.type === "hand") {
      disp = { stacks: (prev || state).players.map((p) => p.stack), bets: state.players.map(() => 0),
               board: [], pot: 0, say: {}, folded: {} };
      $("banner").textContent = "";
      log(`Hand ${ev.hand_no} — ${name(ev.button)} has the button`, "street");
    } else if (ev.type === "street") {
      disp.board = ev.board; disp.stacks = ev.stacks; disp.bets = ev.bets; disp.pot = ev.pot;
      disp.say = {};
      if (ev.street !== "preflop") log(`${ev.street[0].toUpperCase() + ev.street.slice(1)}: ${ev.board.map(cardText).join(" ")}`, "street");
      renderCenter(disp.board, disp.pot);
      renderSeats(state);
      await sleep(ev.street === "preflop" ? 250 : DELAY.street);
    } else if (ev.type === "action") {
      disp.stacks[ev.seat] = ev.stack; disp.bets[ev.seat] = ev.street_bet; disp.pot = ev.pot;
      if (ev.action === "fold") disp.folded[ev.seat] = true;
      disp.say = { [ev.seat]: describe(ev).replace(/^\S+ /, "") };
      log(describe(ev));
      renderCenter(disp.board, disp.pot);
      renderSeats(state, { acting: ev.seat });
      await sleep(ev.seat === state.hero ? DELAY.hero : DELAY.action);
    } else if (ev.type === "result") {
      await sleep(DELAY.result);
      disp.revealed = true;
      renderSeats(state);
      const text = resultText(ev);
      for (const [seat, s] of Object.entries(ev.shown)) {
        log(`${+seat === state.hero ? "You" : name(+seat)} show ${s.hole.map(cardText).join(" ")} — ${s.hand}`);
      }
      log(text, "win");
      $("banner").textContent = text;
    }
  }
  disp = null;
  render();
}

// ── main render from `cur` ───────────────────────────────────────────────
function render() {
  const s = cur;
  $("setup").hidden = true;
  $("table-view").hidden = false;
  $("hand-info").textContent = s.hand_no ? `Hand ${s.hand_no} · blinds ${s.sb}/${s.bb}` : `Blinds ${s.sb}/${s.bb}`;
  const winners = s.result && !s.in_hand ? [...new Set(s.result.pots.flatMap((p) => p.winners))] : [];
  renderSeats(s, { acting: s.to_act ? s.hero : null, winners });
  renderCenter(s.board, s.pot);

  const a = s.to_act;
  $("actions").hidden = !a || busy;
  $("between").hidden = s.in_hand || busy;
  if (s.game_over) {
    const won = s.winner === s.hero;
    $("banner").textContent = won ? "You won the table! 🏆" : "You're out of chips.";
    $("btn-deal").textContent = "Play again";
  } else {
    $("btn-deal").innerHTML = (s.hand_no ? "Deal next hand" : "Deal first hand") + " <kbd>Space</kbd>";
  }
  if (a) renderActions(s, a);
  if (!a && !s.in_hand) $("btn-deal").focus({ preventScroll: true });
}

function renderActions(s, a) {
  const me = s.players[s.hero];
  const call = $("btn-call");
  if (a.can_check) call.innerHTML = "Check <kbd>C</kbd>";
  else call.innerHTML = (a.to_call >= me.stack ? `Call all-in ${me.stack}` : `Call ${a.to_call}`) + " <kbd>C</kbd>";

  const opened = s.players.some((p) => p.street_bet > 0);
  const fullRaise = a.can_raise && a.min_raise_to < a.allin_to;
  $("raise-group").hidden = !fullRaise;
  $("btn-allin").hidden = !a.can_raise;
  $("btn-raise").innerHTML = (opened ? "Raise" : "Bet") + " <kbd>R</kbd>";
  if (fullRaise) {
    const r = $("raise-range"), n = $("raise-amount");
    r.min = n.min = a.min_raise_to;
    r.max = n.max = a.allin_to;
    r.step = 1;
    const v = Math.min(Math.max(+n.value || a.min_raise_to, a.min_raise_to), a.allin_to);
    r.value = n.value = (+n.dataset.hand === s.hand_no && n.dataset.street === s.street) ? v : a.min_raise_to;
    n.dataset.hand = s.hand_no; n.dataset.street = s.street;
  }
}

function preset(kind) {
  const s = cur, a = s.to_act;
  if (!a) return;
  const me = s.players[s.hero];
  let to;
  if (kind === "max") to = a.allin_to;
  else {
    const potAfterCall = s.pot + a.to_call;
    const frac = kind === "half" ? 0.5 : 1;
    to = me.street_bet + a.to_call + Math.round(potAfterCall * frac);
  }
  to = Math.min(Math.max(to, a.min_raise_to), a.allin_to);
  $("raise-range").value = $("raise-amount").value = to;
}

// ── actions ──────────────────────────────────────────────────────────────
async function send(path, body) {
  if (busy) return;
  busy = true;
  $("new-game").disabled = true;
  $("error").textContent = "";
  $("actions").hidden = true;
  $("between").hidden = true;
  try {
    const state = await api(path, body);
    await replay(state);
  } catch (err) {
    if (err.status === 404) { saveId(null); showSetup("That table has expired. Start a new one."); return; }
    $("error").textContent = err.message;
    try { await replay(await api(`tables/${tid}`)); } catch {}   // resync (e.g. another tab acted)
  } finally {
    busy = false;
    $("new-game").disabled = false;
    if (cur && !$("table-view").hidden) render();
  }
}

function act(kind, amount) {
  if (!cur || !cur.to_act) return;
  send(`tables/${tid}/act`, amount === undefined ? { action: kind } : { action: kind, amount });
}

function raise() {
  const a = cur && cur.to_act;
  if (!a) return;
  const v = parseInt($("raise-amount").value, 10);
  if (!Number.isFinite(v) || v < a.min_raise_to || v > a.allin_to) {
    $("error").textContent = `Raise must be ${a.min_raise_to}–${a.allin_to}.`;
    return;
  }
  act("raise", v);
}

function dealOrRestart() {
  if (!cur || cur.in_hand) return;
  if (cur.game_over) { showSetup(); return; }
  send(`tables/${tid}/deal`, {});
}

function showSetup(msg) {
  $("setup").hidden = false;
  $("table-view").hidden = true;
  $("hand-info").textContent = "";
  $("setup-error").textContent = msg || "";
}

async function createTable(ev) {
  ev.preventDefault();
  if (busy) return;
  const f = new FormData(ev.target);
  const body = Object.fromEntries([...f].map(([k, v]) => [k, parseInt(v, 10)]));
  $("setup-error").textContent = "";
  try {
    const res = await api("tables", body);
    tid = res.id;
    saveId(tid);
    cur = res.state;
    $("log").replaceChildren();
    $("banner").textContent = "";
    render();
    send(`tables/${tid}/deal`, {});
  } catch (err) {
    $("setup-error").textContent = err.message;
  }
}

// ── wiring ───────────────────────────────────────────────────────────────
$("setup-form").addEventListener("submit", createTable);
$("new-game").addEventListener("click", () => { if (!busy) showSetup(); });
$("btn-fold").addEventListener("click", () => act("fold"));
$("btn-call").addEventListener("click", () => act(cur.to_act.can_check ? "check" : "call"));
$("btn-allin").addEventListener("click", () => act("allin"));
$("btn-raise").addEventListener("click", raise);
$("btn-deal").addEventListener("click", dealOrRestart);
$("raise-range").addEventListener("input", (e) => { $("raise-amount").value = e.target.value; });
$("raise-amount").addEventListener("input", (e) => { $("raise-range").value = e.target.value; });
$("raise-amount").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); raise(); } });
document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => preset(b.dataset.preset)));
addEventListener("resize", () => { if (cur && !busy && !$("table-view").hidden) renderSeats(cur, { acting: cur.to_act ? cur.hero : null }); });

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input") || e.metaKey || e.ctrlKey || e.altKey || busy || !cur) return;
  if ($("table-view").hidden) return;
  const k = e.key.toLowerCase();
  if (cur.to_act) {
    if (k === "f") act("fold");
    else if (k === "c" || k === "k") act(cur.to_act.can_check ? "check" : "call");
    else if (k === "a" && cur.to_act.can_raise) act("allin");
    else if (k === "r" && !$("raise-group").hidden) raise();
    else return;
    e.preventDefault();
  } else if ((k === " " || k === "enter") && !cur.in_hand && document.activeElement?.tagName !== "BUTTON") {
    e.preventDefault();
    dealOrRestart();
  }
});

(async function boot() {
  tid = loadId();
  if (!tid) { showSetup(); return; }
  try {
    cur = await api(`tables/${tid}`);
    render();
  } catch (err) {
    if (err.status === 404) { saveId(null); showSetup(); return; }
    showSetup(`Couldn't load your table (${err.message}). Reload to try again.`);
  }
})();
