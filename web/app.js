// Web client for the poker server. Holds no game rules: it renders /api/v1 snapshots and
// replays each snapshot's `events` so the bots' moves are visible one by one.
"use strict";

const API = "api/v1";
const STORE_KEY = "poker.table";
const ODDS_KEY = "poker.odds";
const SOUND_KEY = "poker.sound";           // "0" = muted
const VOLUME_KEY = "poker.volume";         // 0-100
const NEXT_KEY = "poker.next";             // auto-deal countdown, seconds; "0" = deal by hand
const SUIT = { c: "♣", d: "♦", h: "♥", s: "♠" };
const DELAY = { think: 340, action: 320, street: 600, chip: 320, showdown: 900 };
const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
const reduced = () => motionQuery.matches;

const $ = (id) => document.getElementById(id);
let tid = null;          // table id: the only credential for our seat
let cur = null;          // last server snapshot
let busy = false;        // replaying events or waiting on the server
let disp = null;         // what the felt shows mid-replay: {stacks, bets, board, pot, folded}
let said = {};           // each seat's last move this street (stays up until the street ends)
let lastActor = null;    // whose move is newest, highlighted
let seatEls = [];        // per seat: {root, cards, plate, name, stack, say, bet}
let nextTimer = null;    // pending auto-deal
let held = false;        // the player paused auto-deal
let oddsCache = { key: null, data: null };

// ── storage (per-viewer convenience only) ───────────────────────────────
function load(k) { try { return localStorage.getItem(k); } catch { return null; } }
function save(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch {} }

// ── server ───────────────────────────────────────────────────────────────
async function api(path, body) {
  let res;
  try {
    res = await fetch(`${API}/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),          // a hung request must not freeze the table
    });
  } catch (err) {
    throw new Error(err.name === "TimeoutError" ? "The server took too long to answer." : "Network error.");
  }
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

// ── small helpers ────────────────────────────────────────────────────────
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced() ? Math.min(ms, 120) : ms));
function cardText(code) { return (code[0] === "T" ? "10" : code[0]) + SUIT[code[1]]; }
function name(seat) { return seat === cur.hero ? "You" : cur.players[seat].name; }
const pct = (x) => (x * 100).toFixed(x > 0 && x < 0.1 ? 1 : 0) + "%";

function center(elm) {
  const f = $("felt").getBoundingClientRect(), r = elm.getBoundingClientRect();
  return { x: r.left + r.width / 2 - f.left, y: r.top + r.height / 2 - f.top };
}
function toFeltCenter(elm) {
  const f = $("felt").getBoundingClientRect(), c = center(elm);
  return { dx: f.width / 2 - c.x, dy: f.height / 2 - c.y };
}

// count a number up/down instead of jumping
function tween(node, to, fmt = String) {
  const from = node._v ?? to;
  node._v = to;
  if (from === to || reduced()) { node.textContent = fmt(to); return; }
  const t0 = performance.now(), dur = 420;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
    if (node._v !== to) return;                     // a newer tween took over
    node.textContent = fmt(Math.round(from + (to - from) * e));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── sound: synthesized with Web Audio, no files to load ──────────────────
const gainFor = (v) => 0.9 * (v / 100) ** 2;          // squared: the slider feels even to the ear
const sfx = (() => {
  let ctx = null, master = null, noiseBuf = null;
  function ready() {
    if (!$("sound-toggle").checked || document.hidden) return false;
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = gainFor($("volume").value);
      master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    return ctx.state === "running";                   // never queue sounds up to blast out later
  }
  const at = (ms) => ctx.currentTime + Math.max(0, ms) / 1000;
  function env(t, peak, attack, decay) {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
    g.connect(master);
    return g;
  }
  function burst(t, freq, q, peak, decay) {         // filtered noise: card slides, snaps, clacks
    if (!noiseBuf) {
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate / 2, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    const src = ctx.createBufferSource(), f = ctx.createBiquadFilter();
    src.buffer = noiseBuf;
    f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q;
    src.connect(f); f.connect(env(t, peak, 0.003, decay));
    src.start(t, Math.random() * 0.3); src.stop(t + decay + 0.05);
  }
  function tone(t, freq, type, peak, decay) {
    const o = ctx.createOscillator();
    o.type = type; o.frequency.value = freq;
    o.connect(env(t, peak, 0.005, decay));
    o.start(t); o.stop(t + decay + 0.05);
  }
  return {
    card(ms) { if (!ready()) return; const t = at(ms); burst(t, 2600 + Math.random() * 800, 0.8, 0.5, 0.07); burst(t + 0.02, 5200, 1.5, 0.15, 0.04); },
    flip(ms) { if (!ready()) return; const t = at(ms); burst(t, 1800, 1.2, 0.45, 0.05); burst(t + 0.045, 3200, 1.2, 0.3, 0.05); },
    muck() { if (!ready()) return; burst(at(0), 1200, 0.6, 0.35, 0.18); },
    knock() { if (!ready()) return; const t = at(0); for (const d of [0, 0.12]) { tone(t + d, 140, "sine", 0.5, 0.09); burst(t + d, 600, 1, 0.25, 0.04); } },
    chips(ms, n = 3) {
      if (!ready()) return;
      const t = at(ms);
      for (let i = 0; i < n; i++) {
        const ti = t + i * 0.035 + Math.random() * 0.015, f = 3800 + Math.random() * 1600;
        tone(ti, f, "sine", 0.12, 0.05); tone(ti, f * 1.48, "sine", 0.05, 0.035); burst(ti, 6000, 2, 0.12, 0.02);
      }
    },
    win(big) {
      if (!ready()) return;
      const t = at(0), notes = big ? [523.25, 659.25, 783.99, 1046.5, 1318.5] : [659.25, 987.77];
      notes.forEach((f, i) => { tone(t + i * 0.11, f, "triangle", big ? 0.28 : 0.18, big ? 0.9 : 0.6); tone(t + i * 0.11, f * 2, "sine", 0.06, 0.4); });
    },
    volume(v) { if (master) master.gain.setTargetAtTime(gainFor(v), ctx.currentTime, 0.03); },
    unlock() { if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {}); },
  };
})();

// a stack of chips sliding across the felt
function fly(from, to, amount, { duration = DELAY.chip, delay = 0 } = {}) {
  if (!from || !to) return Promise.resolve();
  sfx.chips(delay + (reduced() ? 0 : duration * 0.85), amount >= 20 ? 5 : 3);   // the landing clink
  if (reduced()) return Promise.resolve();
  const a = center(from), b = center(to);
  const chip = el("div", "fly-chip");
  chip.append(el("i"), el("i"), el("i"));
  if (amount) chip.append(el("span", "", String(amount)));
  chip.style.left = a.x + "px";
  chip.style.top = a.y + "px";
  $("fx").append(chip);
  const anim = chip.animate([
    { transform: "translate(0,0) scale(.5)", opacity: 0 },
    { transform: "translate(0,0) scale(1)", opacity: 1, offset: 0.12 },
    { transform: `translate(${b.x - a.x}px, ${b.y - a.y}px) scale(.85)`, opacity: 1, offset: 0.92 },
    { transform: `translate(${b.x - a.x}px, ${b.y - a.y}px) scale(.7)`, opacity: 0 },
  ], { duration, delay, easing: "cubic-bezier(.35,.75,.3,1)", fill: "both" });
  return anim.finished.catch(() => {}).then(() => chip.remove());
}

function floatText(target, text, cls) {
  if (!target) return;
  const c = center(target), f = el("div", "float " + (cls || ""), text);
  f.style.left = c.x + "px";
  f.style.top = c.y + "px";
  $("fx").append(f);
  const anim = f.animate([
    { transform: "translate(-50%, -20%) scale(.6)", opacity: 0 },
    { transform: "translate(-50%, -90%) scale(1.15)", opacity: 1, offset: 0.25 },
    { transform: "translate(-50%, -190%) scale(1)", opacity: 0 },
  ], { duration: reduced() ? 1 : 1800, easing: "ease-out", fill: "both" });
  anim.finished.catch(() => {}).then(() => f.remove());
}

// ── cards ────────────────────────────────────────────────────────────────
function cardFace(code) {
  const c = el("div", "pcard");
  if (!code) { c.classList.add("back"); return c; }
  const rank = code[0] === "T" ? "10" : code[0], suit = code[1];
  if (suit === "h" || suit === "d") c.classList.add("red");
  c.setAttribute("aria-label", code);
  c.append(el("span", "r", rank), el("span", "s", SUIT[suit]), el("span", "pip", SUIT[suit]));
  return c;
}

// show `codes` (null = face down) in `box`; animate only what changed:
// new cards fly in from the dealer, face-down cards turning up flip, removed cards are mucked
function setCards(box, codes, mode) {
  const key = codes.map((c) => c || "x").join(",");
  if (box.dataset.key === key) return;
  const old = box.dataset.key ? box.dataset.key.split(",") : [];
  box.dataset.key = key;
  if (!codes.length) {
    const kids = [...box.children];
    if (kids.length) sfx.muck();
    if (!kids.length || reduced()) { box.replaceChildren(); return; }
    const { dx, dy } = toFeltCenter(box);
    kids.forEach((k) => k.animate([{ transform: "none", opacity: 1 },
      { transform: `translate(${dx * 0.6}px, ${dy * 0.6}px) rotate(35deg) scale(.5)`, opacity: 0 }],
      { duration: 380, easing: "ease-in", fill: "forwards" }));
    setTimeout(() => { if (box.dataset.key === "") box.replaceChildren(); }, 390);
    return;
  }
  box.replaceChildren(...codes.map(cardFace));
  const still = reduced();
  let n = 0;
  [...box.children].forEach((c, i) => {
    const was = old[i], now = codes[i] || "x";
    if (was === now) return;
    if (was === "x") {                                          // reveal
      const delay = i * 120;
      sfx.flip(still ? 0 : delay);
      if (!still) c.animate([{ transform: "rotateY(90deg)", filter: "brightness(.6)" }, { transform: "none" }],
        { duration: 340, delay, easing: "cubic-bezier(.2,.8,.3,1)", fill: "backwards" });
    } else if (mode === "board") {
      const delay = n++ * 140;
      sfx.card(still ? 0 : delay);
      if (!still) c.animate([{ transform: "translateY(-26px) rotateY(100deg) scale(.8)", opacity: 0 }, { transform: "none", opacity: 1 }],
        { duration: 420, delay, easing: "cubic-bezier(.2,.8,.3,1)", fill: "backwards" });
    } else {
      const delay = (mode.order || 0) * 70 + i * 260;
      sfx.card(still ? 0 : delay);
      if (still) return;
      const { dx, dy } = toFeltCenter(c);
      c.animate([{ transform: `translate(${dx}px, ${dy}px) rotate(-25deg) scale(.45)`, opacity: 0 },
        { transform: "none", opacity: 1 }],
        { duration: 460, delay, easing: "cubic-bezier(.2,.8,.25,1)", fill: "backwards" });
    }
  });
}

// ── table layout ─────────────────────────────────────────────────────────
function seatPositions(n, hero) {
  // hero at the bottom centre, the rest clockwise around the oval
  const narrow = matchMedia("(max-width: 640px)").matches;
  const rx = narrow ? 44 : 50, ry = narrow ? 50 : 54;
  const out = [];
  for (let k = 0; k < n; k++) {
    const a = (Math.PI / 2) + (k * 2 * Math.PI) / n;
    out[(hero + k) % n] = { left: 50 + rx * Math.cos(a), top: 50 + ry * Math.sin(a) };
  }
  return out;
}

function buildSeats(state) {
  $("seats").replaceChildren();
  $("bets").replaceChildren();
  seatEls = state.players.map((p) => {
    const root = el("div", "seat" + (p.seat === state.hero ? " hero" : ""));
    const say = el("div", "say"), cards = el("div", "cards"), plate = el("div", "plate");
    const nm = el("div", "name"), stack = el("div", "stack");
    plate.append(nm, stack);
    root.append(say, cards, plate);
    const bet = el("div", "bet");
    bet.append(el("span", "chip-ico"), el("span", "amt"));
    $("seats").append(root);
    $("bets").append(bet);
    return { root, cards, plate, name: nm, stack, say, bet };
  });
  positionSeats(state);
}

function positionSeats(state) {
  const pos = seatPositions(state.players.length, state.hero);
  seatEls.forEach((s, i) => {
    s.root.style.left = pos[i].left + "%";
    s.root.style.top = pos[i].top + "%";
    s.bet.style.left = 50 + (pos[i].left - 50) * 0.58 + "%";
    s.bet.style.top = 50 + (pos[i].top - 50) * 0.5 + "%";
  });
  const d = pos[state.button];
  const dl = $("dealer");
  dl.hidden = !state.hand_no;
  dl.style.left = 50 + (d.left - 50) * 0.7 + 6 + "%";
  dl.style.top = 50 + (d.top - 50) * 0.66 + "%";
}

function holeCodes(p) {
  const folded = disp ? !!disp.folded[p.seat] : p.folded;
  if (!p.in_hand || (folded && p.bot) || (disp && disp.noCards)) return [];
  if (p.bot && disp && !disp.revealed) return [null, null];
  return p.hole || [null, null];
}

function updateSeats(state, { acting = null, thinking = false, winners = [] } = {}) {
  if (seatEls.length !== state.players.length) buildSeats(state);
  for (const p of state.players) {
    const s = seatEls[p.seat];
    const folded = disp ? !!disp.folded[p.seat] : p.folded;
    s.root.classList.toggle("out", p.out);
    s.root.classList.toggle("folded", !p.out && folded && p.in_hand);
    s.root.classList.toggle("acting", acting === p.seat);
    s.root.classList.toggle("thinking", acting === p.seat && thinking);
    s.root.classList.toggle("winner", winners.includes(p.seat));
    s.name.textContent = p.name + (p.allin && p.in_hand ? " · all-in" : "");
    tween(s.stack, disp ? disp.stacks[p.seat] : p.stack, (v) => `${v} chips`);
    const bet = disp ? disp.bets[p.seat] : p.street_bet;
    s.bet.classList.toggle("show", !!bet);
    if (bet) tween(s.bet.lastChild, bet); else s.bet.lastChild._v = undefined;
    const words = thinking && acting === p.seat ? "" : said[p.seat] || "";
    s.say.classList.toggle("show", !!words);
    s.say.classList.toggle("latest", lastActor === p.seat);
    if (words) s.say.textContent = words;
    setCards(s.cards, holeCodes(p), { order: p.seat });
  }
  positionSeats(state);
}

function updateCenter(board, pot) {
  setCards($("board"), board, "board");
  $("pot").classList.toggle("show", !!pot);
  if (pot) tween($("pot-amt"), pot, (v) => `Pot ${v}`); else $("pot-amt")._v = undefined;
}

function log(text, cls) {
  const li = el("li", cls || "", text);
  $("log").append(li);
  while ($("log").childElementCount > 300) $("log").firstElementChild.remove();
  li.scrollIntoView({ block: "nearest" });
}

const VERB = { fold: "folds", check: "checks", call: "calls", bet: "bets", raise: "raises to", allin: "is all-in" };
const MY_VERB = { fold: "fold", check: "check", call: "call", bet: "bet", raise: "raise to", allin: "go all-in" };
function describe(ev, short) {
  const verb = (ev.seat === cur.hero ? MY_VERB : VERB)[ev.action];
  const amt = ev.action === "call" ? ` ${ev.chips}`
    : (ev.action === "bet" || ev.action === "raise" || ev.action === "allin") ? ` ${ev.street_bet}` : "";
  return short ? (VERB[ev.action] + amt) : `${name(ev.seat)} ${verb}${amt}`;
}

function resultText(result) {
  return result.pots.map((p) => {
    const who = p.winners.map(name).join(" & ");
    const verb = p.winners.length > 1 ? "split" : (p.winners[0] === cur.hero ? "win" : "wins");
    return `${who} ${verb} ${p.amount}` + (p.hand ? ` with ${p.hand}` : "");
  }).join(" · ");
}

// ── end of hand: who won, how much, then the next deal ───────────────────
function showWinner(result, state) {
  const pots = result.pots;
  const heroWon = pots.some((p) => p.winners.includes(state.hero));
  const first = pots[0];
  const title = first.winners.length > 1 ? "Split pot"
    : first.winners[0] === state.hero ? "You win!" : `${name(first.winners[0])} wins`;
  $("win-title").textContent = (heroWon ? "🏆 " : "") + title;
  $("win-pots").replaceChildren(...pots.map((p, i) => {
    const li = el("li");
    const share = Math.floor(p.amount / p.winners.length);
    li.append(el("span", "who", p.winners.map(name).join(" & ")),
      el("span", "amt", `+${p.winners.length > 1 ? share + " each" : p.amount}`),
      el("span", "how", (pots.length > 1 ? (i ? "side pot" : "main pot") + (p.hand ? " · " : "") : "")
        + (p.hand || (state.players.length > 1 && !result.showdown ? "everyone else folded" : ""))));
    return li;
  }));
  const net = result.net[state.hero];
  const w = $("win-net");
  w.textContent = net > 0 ? `You +${net}` : net < 0 ? `You −${-net}` : "";
  w.className = "win-net " + (net > 0 ? "up" : net < 0 ? "down" : "");
  $("winner").classList.toggle("hero-won", heroWon);
  const over = state.game_over;
  $("next").hidden = over;
  $("btn-again").hidden = !over;
  if (over) $("win-net").textContent = state.winner === state.hero ? "You won the table!" : "You're out of chips.";
  $("winner").hidden = false;
  $("felt").classList.add("result");
}

function hideWinner() { $("winner").hidden = true; $("felt").classList.remove("result"); }

const nextMs = () => +$("next-secs").value * 1000;

function scheduleNext() {
  if (nextTimer || held || busy) return;
  const ring = $("next-ring"), ms = nextMs();
  ring.style.animation = "none";
  $("next").classList.toggle("manual", !ms);
  $("btn-now").textContent = ms ? "Deal now" : "Deal next hand";
  if (!ms) {                                          // countdown off: wait for the player
    $("next-label").textContent = "Ready when you are";
    return;
  }
  void ring.getBoundingClientRect();                 // restart the countdown animation
  ring.style.setProperty("--next-ms", ms + "ms");
  ring.style.animation = `ring ${ms}ms linear forwards`;
  $("next-label").textContent = "Next hand…";
  $("btn-hold").textContent = "Hold";
  nextTimer = setTimeout(() => { nextTimer = null; dealOrRestart(); }, ms);
}

function cancelNext() { clearTimeout(nextTimer); nextTimer = null; }

function hold() {
  if (held) { dealOrRestart(); return; }
  held = true;
  cancelNext();
  $("next-ring").style.animation = "none";
  $("next-label").textContent = "Paused";
  $("btn-hold").textContent = "Resume";
}

// ── replaying events ─────────────────────────────────────────────────────
async function gatherBets() {
  const flights = disp.bets.map((b, i) => b ? fly(seatEls[i].bet, $("pot"), 0, { delay: i * 40 }) : null);
  if (!flights.some(Boolean)) return;
  disp.bets = disp.bets.map(() => 0);
  updateSeats(cur);                                  // bets leave their spots as the chips fly
  await Promise.all(flights);
}

async function replay(state) {
  const prev = cur;
  cur = state;
  if (seatEls.length !== state.players.length) buildSeats(state);
  if (!disp) {
    const base = prev && prev.in_hand ? prev : state;
    disp = { stacks: base.players.map((p) => p.stack), bets: base.players.map((p) => p.street_bet),
             board: [...base.board], pot: base.pot,
             folded: Object.fromEntries(((prev && prev.players) || []).map((p) => [p.seat, p.folded])) };
  }
  for (const ev of state.events) {
    if (ev.type === "hand") {
      hideWinner();
      disp = { stacks: (prev || state).players.map((p) => p.stack), bets: state.players.map(() => 0),
               board: [], pot: 0, folded: {}, noCards: true };
      said = {}; lastActor = null;
      for (const s of seatEls) { s.cards.replaceChildren(); s.cards.dataset.key = ""; }
      $("board").replaceChildren(); $("board").dataset.key = "";
      log(`Hand ${ev.hand_no} — ${name(ev.button)} has the button`, "street");
      cur = { ...state, button: ev.button };
      updateCenter([], 0);
      updateSeats(cur);
      await sleep(250);
    } else if (ev.type === "street") {
      if (ev.street !== "preflop") await gatherBets();
      said = {}; lastActor = null;
      if (ev.street === "preflop") {                     // blinds go out, then the cards
        disp.stacks = ev.stacks;
        updateSeats(state);
        const posted = ev.bets.map((b, i) => b ? fly(seatEls[i].plate, seatEls[i].bet, 0) : null);
        await Promise.all(posted);
      } else {
        log(`${ev.street[0].toUpperCase() + ev.street.slice(1)}: ${ev.board.map(cardText).join(" ")}`, "street");
      }
      disp.board = ev.board; disp.stacks = ev.stacks; disp.bets = ev.bets; disp.pot = ev.pot;
      disp.noCards = false;
      updateCenter(disp.board, disp.pot);
      updateSeats(state);
      await sleep(ev.street === "preflop" ? 300 + state.players.length * 140 : DELAY.street);
    } else if (ev.type === "action") {
      const bot = ev.seat !== state.hero;
      // once you can't act any more (folded or all-in), the bots play out at double speed
      const pace = disp.folded[state.hero] || disp.stacks[state.hero] === 0 ? 0.5 : 1;
      if (bot) {
        updateSeats(state, { acting: ev.seat, thinking: true });
        await sleep(DELAY.think * pace);
      }
      if (ev.chips > 0) {
        await fly(seatEls[ev.seat].plate, seatEls[ev.seat].bet, ev.chips, { duration: DELAY.chip * pace });
      }
      disp.stacks[ev.seat] = ev.stack; disp.bets[ev.seat] = ev.street_bet; disp.pot = ev.pot;
      if (ev.action === "fold") disp.folded[ev.seat] = true;
      if (ev.action === "check") sfx.knock();
      else if (ev.action === "fold" && !bot) sfx.muck();          // a bot's muck sounds as its cards leave
      said[ev.seat] = describe(ev, true);
      lastActor = ev.seat;
      log(describe(ev));
      updateCenter(disp.board, disp.pot);
      updateSeats(state, { acting: ev.seat });
      await sleep(bot ? DELAY.action * pace : 120);
    } else if (ev.type === "result") {
      await gatherBets();
      lastActor = null;
      if (ev.showdown) {
        disp.revealed = true;
        updateSeats(state);
        for (const [seat, s] of Object.entries(ev.shown)) {
          log(`${name(+seat)} show${+seat === state.hero ? "" : "s"} ${s.hole.map(cardText).join(" ")} — ${s.hand}`);
        }
        await sleep(DELAY.showdown);
      }
      const winners = [...new Set(ev.pots.flatMap((p) => p.winners))];
      await Promise.all(ev.pots.flatMap((p, k) => p.winners.map((w, j) =>
        fly($("pot"), seatEls[w].plate, Math.floor(p.amount / p.winners.length),
            { duration: 560, delay: (k * 2 + j) * 150 }))));
      disp.pot = 0;
      disp.stacks = state.players.map((p) => p.stack);
      updateCenter(disp.board, 0);
      updateSeats(state, { winners });
      for (const w of winners) {
        const won = ev.pots.reduce((t, p) => t + (p.winners.includes(w) ? Math.floor(p.amount / p.winners.length) : 0), 0);
        floatText(seatEls[w].plate, `+${won}`, w === state.hero ? "hero" : "");
      }
      const text = resultText(ev);
      log(text, "win");
      showWinner(ev, state);
      sfx.win(winners.includes(state.hero));
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
  updateSeats(s, { acting: s.to_act ? s.hero : null, winners });
  updateCenter(s.board, s.pot);

  const a = s.to_act;
  $("actions").hidden = !a || busy;
  const between = !s.in_hand && !busy && !s.result && !s.game_over;   // first hand, or a voided one
  $("between").hidden = !between;
  $("btn-deal").innerHTML = (s.hand_no ? "Deal next hand" : "Deal first hand") + " <kbd>Space</kbd>";
  if (a) renderActions(s, a);
  if (!s.in_hand && s.result && !busy) {
    if ($("winner").hidden) showWinner(s.result, s);
    if (!s.game_over) scheduleNext();
    else $("btn-again").focus({ preventScroll: true });
  } else if (between) $("btn-deal").focus({ preventScroll: true });
  renderOdds();
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
  sizingHint();
}

// ── odds helper ──────────────────────────────────────────────────────────
const oddsOn = () => $("odds-toggle").checked;

async function renderOdds() {
  const s = cur, a = s && s.to_act;
  const panel = $("odds");
  panel.hidden = !oddsOn();
  panel.classList.toggle("idle", !a || busy);
  if (!oddsOn()) return;
  if (!a || busy) {                                    // keep its place; nothing to decide yet
    if (!busy) $("odds-body").textContent = "Your numbers appear here on your turn.";
    return;
  }
  const key = `${tid}|${s.hand_no}|${s.street}|${s.pot}|${a.to_call}`;
  if (oddsCache.key !== key) {
    panel.classList.add("loading");
    try {
      const o = await api(`tables/${tid}/odds`);
      if (cur !== s) return;                           // the game moved on meanwhile
      oddsCache = { key, data: o };
    } catch {
      if (cur === s) $("odds-body").textContent = "Odds unavailable right now.";
      return;
    } finally {
      panel.classList.remove("loading");
    }
  }
  drawOdds(oddsCache.data);
}

function drawOdds(o) {
  if (busy) return;
  const body = $("odds-body");
  const need = o.pot_odds, eq = o.equity;
  const row = (label, value, cls) => {
    const r = el("div", "orow " + (cls || ""));
    r.append(el("span", "olabel", label), el("b", "", value));
    return r;
  };
  const gauge = el("div", "gauge");
  const fill = el("div", "fill " + (o.verdict === "call_minus_ev" ? "bad" : "good"));
  fill.style.width = pct(eq);
  gauge.append(fill);
  if (o.to_call) {
    const mark = el("div", "mark");
    mark.style.left = pct(need);
    mark.title = "break-even equity";
    gauge.append(mark);
  }
  const kids = [o.to_call ? row(`Call ${o.to_call} to win ${o.pot}`, `need ${pct(need)}`)
                          : row("Nothing to call", "free to check")];
  kids.push(row(`Your equity vs ${o.opponents} opponent${o.opponents === 1 ? "" : "s"}`, pct(eq)), gauge);
  const ev = Math.abs(o.ev).toFixed(1);
  const verdict = {
    call_plus_ev: ["good", `Calling is +EV: about +${ev} chips a call.`],
    call_minus_ev: ["bad", `Calling is −EV: about −${ev} chips a call. Fold, unless you plan to bluff.`],
    value_bet: ["good", `Ahead of your fair share (${pct(o.fair_share)}): bet for value.`],
    check: ["", `Fair share is ${pct(o.fair_share)}. Check, or bluff sparingly.`],
  }[o.verdict];
  kids.push(el("p", "verdict " + verdict[0], verdict[1]));
  if (o.made) kids.push(row("You have", o.made));
  if (o.outs.length) {
    kids.push(row(`${o.outs.length} outs`, `≈${pct(o.hit_by_river)} by the river`));
    const list = el("div", "outs");
    list.append(...o.outs.map((c) => el("span", "mini" + (c[1] === "h" || c[1] === "d" ? " red" : ""), cardText(c))));
    kids.push(list);
  }
  kids.push(el("p", "hint", "Equity is simulated against random hands; bettors usually hold better."));
  const size = el("p", "size");
  size.id = "odds-size";
  kids.push(size);
  body.replaceChildren(...kids);
  sizingHint();
}

// how good a hand a caller needs against the raise on the slider (the server does the maths)
let sizeTimer = null;
function sizingHint() {
  clearTimeout(sizeTimer);
  const out = $("odds-size");
  const s = cur, a = s && s.to_act;
  if (!out || !a || !oddsOn() || $("raise-group").hidden) { if (out) out.textContent = ""; return; }
  const to = parseInt($("raise-amount").value, 10);
  if (!Number.isFinite(to) || to < a.min_raise_to || to > a.allin_to) { out.textContent = ""; return; }
  sizeTimer = setTimeout(async () => {
    if (busy || cur !== s) return;
    try {
      const o = await api(`tables/${tid}/odds?raise_to=${to}`);
      if (cur === s && !busy && $("odds-size")) $("odds-size").textContent = `Raising to ${to}: a caller needs ${pct(o.caller_needs)} equity.`;
    } catch {}
  }, 180);
}

// ── actions ──────────────────────────────────────────────────────────────
async function send(path, body) {
  if (busy) return;
  busy = true;
  cancelNext();
  clearTimeout(sizeTimer);
  $("new-game").disabled = true;
  $("error").textContent = "";
  $("actions").hidden = true;
  $("between").hidden = true;
  $("odds").classList.add("idle");
  try {
    const state = await api(path, body);
    await replay(state);
  } catch (err) {
    disp = null;
    if (err.status === 404) { save(STORE_KEY, null); showSetup("That table has expired. Start a new one."); return; }
    $("error").textContent = err.message;
    try { await replay(await api(`tables/${tid}`)); } catch {}   // resync (e.g. another tab acted)
  } finally {
    busy = false;
    $("new-game").disabled = false;
    if (cur && !$("table-view").hidden) render();
  }
}

function act(kind, amount) {
  if (!cur || !cur.to_act || busy) return;
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
  cancelNext();
  held = false;
  if (!cur || cur.in_hand || busy) return;
  if (cur.game_over) { showSetup(); return; }
  send(`tables/${tid}/deal`, {});
}

function showSetup(msg) {
  cancelNext();
  held = false;
  hideWinner();
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
    save(STORE_KEY, tid);
    cur = res.state;
    seatEls = [];
    $("log").replaceChildren();
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
$("btn-now").addEventListener("click", dealOrRestart);
$("btn-hold").addEventListener("click", hold);
$("btn-again").addEventListener("click", () => showSetup());
$("raise-range").addEventListener("input", (e) => { $("raise-amount").value = e.target.value; sizingHint(); });
$("raise-amount").addEventListener("input", (e) => { $("raise-range").value = e.target.value; sizingHint(); });
$("raise-amount").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); raise(); } });
document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => preset(b.dataset.preset)));
$("odds-toggle").checked = load(ODDS_KEY) === "1";
$("sound-toggle").checked = load(SOUND_KEY) !== "0";
$("sound-toggle").addEventListener("change", (e) => {
  save(SOUND_KEY, e.target.checked ? null : "0");
  $("volume").disabled = !e.target.checked;
  if (e.target.checked) sfx.chips(0);
});
{
  const v = parseInt(load(VOLUME_KEY), 10);
  if (v >= 0 && v <= 100) $("volume").value = v;
  $("volume").disabled = !$("sound-toggle").checked;
}
$("volume").addEventListener("input", (e) => { sfx.volume(e.target.value); save(VOLUME_KEY, e.target.value); });
$("volume").addEventListener("change", () => sfx.chips(0));            // a sample at the new level
addEventListener("pointerdown", sfx.unlock);           // browsers start audio only after a gesture
addEventListener("keydown", sfx.unlock);
$("next-secs").value = [...$("next-secs").options].some((o) => o.value === load(NEXT_KEY)) ? load(NEXT_KEY) : "4";
$("next-secs").addEventListener("change", (e) => {
  save(NEXT_KEY, e.target.value);
  if (!$("winner").hidden && !held) { cancelNext(); scheduleNext(); }   // apply to this countdown
});
$("odds-toggle").addEventListener("change", (e) => { save(ODDS_KEY, e.target.checked ? "1" : null); if (cur) renderOdds(); });
addEventListener("resize", () => { if (cur && seatEls.length) positionSeats(cur); });

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input") || e.metaKey || e.ctrlKey || e.altKey || !cur) return;
  if ($("table-view").hidden) return;
  const k = e.key.toLowerCase();
  if (k === "o") { $("odds-toggle").click(); return; }
  if (k === "m") { $("sound-toggle").click(); return; }
  if (busy) return;
  if (cur.to_act) {
    if (k === "f") act("fold");
    else if (k === "c" || k === "k") act(cur.to_act.can_check ? "check" : "call");
    else if (k === "a" && cur.to_act.can_raise) act("allin");
    else if (k === "r" && !$("raise-group").hidden) raise();
    else return;
    e.preventDefault();
  } else if ((k === " " || k === "enter") && !cur.in_hand && document.activeElement?.tagName !== "BUTTON") {
    e.preventDefault();
    if (cur.game_over) showSetup(); else dealOrRestart();
  }
});

(async function boot() {
  tid = load(STORE_KEY);
  if (!tid) { showSetup(); return; }
  try {
    cur = await api(`tables/${tid}`);
    render();
  } catch (err) {
    if (err.status === 404) { save(STORE_KEY, null); showSetup(); return; }
    showSetup(`Couldn't load your table (${err.message}). Reload to try again.`);
  }
})();
