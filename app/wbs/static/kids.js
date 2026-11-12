"use strict";
const BASE = document.documentElement.dataset.base || "";   // set when a proxy serves the app under a path
// Kids' page: the day's bird clips. Hover plays a tile silently; click opens a big player with ◀ ▶.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };

const params = new URLSearchParams(location.search);
const localToday = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const state = { day: params.get("day") || localToday(), species: params.get("species") || "",
                sort: store.get("wbs.kidsSort", document.body.dataset.sort || "new"), visits: [], shown: [], open: -1,
                card: false, flagged: {} };

const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const shiftDay = (day, n) => { const d = new Date(day + "T12:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
function dayLabel(day) {
  const today = localToday();
  if (day === today) return "Today";
  if (day === shiftDay(today, -1)) return "Yesterday";
  return new Date(day + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

function sortVisits(visits, how) {
  const v = [...visits];
  if (how === "old") return v.sort((a, b) => a.ts - b.ts);
  // By bird: the rarest visitor of the day first, then the next rarest; each bird's visits newest first.
  const n = (sp) => state.counts?.[sp] || 0;
  if (how === "bird") return v.sort((a, b) => n(a.species) - n(b.species) || a.species.localeCompare(b.species) || b.ts - a.ts);
  return v.sort((a, b) => b.ts - a.ts);   // newest first (default)
}

function setUrl() {
  const p = new URLSearchParams();
  if (state.day !== localToday()) p.set("day", state.day);
  if (state.species) p.set("species", state.species);
  history.replaceState(null, "", `${BASE}/` + (p.toString() ? "?" + p : ""));
}

async function load(keepPlaying = false) {
  const q = new URLSearchParams({ day: state.day });
  const r = await fetch(`${BASE}/api/public/day?${q}`);
  const data = await r.json();
  state.visits = data.visits.map((v) => ({ ...v, clip: BASE + v.clip, poster: v.poster && BASE + v.poster,
    posters: Object.fromEntries(Object.entries(v.posters || {}).map(([s, p]) => [s, p && BASE + p])) }));
  state.counts = data.counts;
  state.dots = data.dots || {};
  state.about = data.about || {};
  render(keepPlaying);
}

function render(keepPlaying) {
  $("#day-label").textContent = dayLabel(state.day);
  $("#next-day").disabled = state.day >= localToday();
  const total = state.visits.length;   // a visit with two species counts once here
  $("#subtitle").textContent = total ? `${total} visit${total === 1 ? "" : "s"} ${state.day === localToday() ? "so far today" : ""}` : "Who came to the feeder?";
  $$(".sort button").forEach((b) => b.classList.toggle("on", b.dataset.sort === state.sort));
  // species chips (filter)
  const dots = { ...state.dots, ...Object.fromEntries(state.visits.map((v) => [v.species, v.dot])) };
  $("#chips").innerHTML = Object.keys(state.counts || {}).length > 1 || state.species
    ? `<button class="chip ${state.species ? "" : "on"}" data-sp="">All birds</button>` +
      Object.entries(state.counts).map(([sp, n]) =>
        `<button class="chip ${sp === state.species ? "on" : ""}" data-sp="${esc(sp)}">${esc(dots[sp] || "")} ${esc(sp)}<b>${n}</b></button>`).join("")
    : "";
  const about = state.about[state.species];
  $("#about").hidden = !about;
  $("#about").replaceChildren(...(about ? [`Learn about the ${state.species}: `, ...Object.entries(about).flatMap(([site, url], i) => {
    const a = Object.assign(document.createElement("a"), { href: url, target: "_blank", rel: "noopener noreferrer", textContent: site });
    return i ? [" · ", a] : [a];   // outside sites: full URLs, so no BASE
  })] : []));
  $$("#chips .chip").forEach((c) => c.addEventListener("click", () => { state.species = c.dataset.sp; setUrl(); render(); }));

  // A visit with two species (say a jay and a squirrel) is under both chips, named by the chip it was found by.
  const list = state.visits.filter((v) => !state.species || v.species === state.species || (v.also || []).includes(state.species))
    .map((v) => !state.species || v.species === state.species ? v
      : { ...v, species: state.species, dot: dots[state.species] || "", poster: v.posters[state.species] || v.poster,
          also: [v.species, ...v.also.filter((s) => s !== state.species)] });
  state.shown = sortVisits(list, state.sort);
  if (keepPlaying && state.open >= 0) return;          // don't reshuffle under an open clip
  $("#empty").hidden = state.shown.length > 0;
  const isToday = state.day === localToday();
  $("#empty-text").textContent = isToday ? "The feeder is quiet. No birds yet today!" : "No birds came to the feeder this day.";
  $("#see-yesterday").hidden = !isToday;
  $("#grid").innerHTML = state.shown.map((v, i) => `
    <article class="tile" data-i="${i}" tabindex="0" aria-label="${esc(v.species)} at ${esc(fmtTime(v.ts))}">
      <video muted loop playsinline preload="none" ${v.poster ? `poster="${esc(v.poster)}"` : ""} data-src="${esc(v.clip)}"></video>
      <span class="play">▶</span>
      <div class="label"><span>${esc(v.dot || "")} ${esc(v.species)}${(v.also || []).length ? ` <small>+ ${esc(v.also.join(", "))}</small>` : ""}</span><span class="time">${esc(fmtTime(v.ts))}</span></div>
    </article>`).join("");
  $$("#grid .tile").forEach((t) => {
    const vid = $("video", t);
    t.addEventListener("mouseenter", () => {
      if (!vid.src) vid.src = vid.dataset.src;
      vid.currentTime = 0;
      vid.play().catch(() => {});
    });
    t.addEventListener("mouseleave", () => vid.pause());
    // Ctrl-click (Cmd on a Mac): the player with the bird's card beside it.
    t.addEventListener("click", (e) => openViewer(+t.dataset.i, e.ctrlKey || e.metaKey));
    t.addEventListener("keydown", (e) => { if (e.key === "Enter") openViewer(+t.dataset.i); });
  });
}

// ---- big player ---------------------------------------------------------------------
const viewer = $("#viewer"), player = $("#v-video");
function openViewer(i, withCard = false) {
  $$("#grid video").forEach((v) => v.pause());
  state.open = i;
  state.card = withCard;
  showClip();
  viewer.hidden = false;
}
function showClip() {
  const v = state.shown[state.open];
  if (!v) return closeViewer();
  player.src = v.clip;
  if (v.poster) player.poster = v.poster;
  player.muted = false;
  player.play().catch(() => { player.muted = true; player.play().catch(() => {}); });
  $("#v-name").textContent = `${v.dot || ""} ${v.species}${(v.also || []).length ? " + " + v.also.join(", ") : ""}`;
  $("#v-time").textContent = fmtTime(v.ts);
  $("#v-count").textContent = `${state.open + 1} / ${state.shown.length}`;
  $("#v-prev").disabled = state.open === 0;
  $("#v-next").disabled = state.open === state.shown.length - 1;
  $("#v-flag").hidden = true;
  $("#v-flag-msg").hidden = true;
  $("#v-flag-btn").disabled = !!state.flagged[v.trace_id];
  showCard();
}

// ---- the bird's card: a trading card with its stats (public visits only) -----------------
const cards = {};   // species -> card data, fetched once per page load
const hourName = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
async function showCard() {
  const box = $("#v-card");
  viewer.classList.toggle("with-card", state.card);
  box.hidden = !state.card;
  $("#v-card-btn").classList.toggle("on", state.card);
  if (!state.card) return;
  const sp = state.shown[state.open].species;
  if (sp === "Mystery bird") { box.innerHTML = '<div class="bc-name">Mystery bird</div><p class="bc-note">Nobody knows yet!</p>'; return; }
  if (!cards[sp]) {
    box.innerHTML = '<p class="bc-note">Loading…</p>';
    const r = await fetch(`${BASE}/api/public/species-card?species=${encodeURIComponent(sp)}`);
    cards[sp] = r.ok ? await r.json() : { species: sp, missing: true };
  }
  if (state.shown[state.open]?.species !== sp || !state.card) return;   // moved on while loading
  const c = cards[sp];
  if (c.missing) { box.innerHTML = `<div class="bc-name">${esc(sp)}</div>`; return; }
  const stat = (n, label) => `<div class="bc-stat"><b>${n ?? "–"}</b><span>${esc(label)}</span></div>`;
  const facts = [
    c.first_seen && ["First seen", fmtDate(c.first_seen)],
    c.busiest_hour !== null && ["Favourite time", `around ${hourName(c.busiest_hour)}`],
    c.most_at_once && ["Most at once", c.most_at_once],
    c.rank && ["Rank this year", `#${c.rank} of ${c.ranked}`],
    ["Days seen this year", c.days_this_year],
    c.streak > 1 && ["Visits in a row", `${c.streak} days`],
  ].filter(Boolean);
  box.innerHTML = `
    <div class="bc-top">${c.portrait ? `<img src="${BASE}${esc(c.portrait)}" alt="">` : '<div class="bc-q">?</div>'}</div>
    <div class="bc-name">${esc(c.species)}</div>
    ${c.scientific ? `<div class="bc-sci">${esc(c.scientific)}</div>` : ""}
    <div class="bc-stats">${stat(c.today, "today")}${stat(c.week, "this week")}${stat(c.year, "this year")}${stat(c.all_time, "all time")}</div>
    <dl class="bc-facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    ${c.note ? `<p class="bc-note">${esc(c.note)}</p>` : ""}
    <div class="bc-links"></div>`;
  $(".bc-links", box).replaceChildren(...Object.entries(c.about || {}).flatMap(([site, url], i) => {
    const a = Object.assign(document.createElement("a"), { href: url, target: "_blank", rel: "noopener noreferrer", textContent: site });
    return i ? [" · ", a] : [a];   // outside sites: full URLs, so no BASE
  }));
}
$("#v-card-btn").addEventListener("click", () => { state.card = !state.card; showCard(); });

// ---- "Wrong bird?": into the grown-ups' Flagged queue --------------------------------
$("#v-flag-btn").addEventListener("click", () => { $("#v-flag").hidden = false; $("#v-flag-note").focus(); });
$("#v-flag-cancel").addEventListener("click", () => { $("#v-flag").hidden = true; });
$("#v-flag").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = state.shown[state.open];
  const r = await fetch(`${BASE}/api/public/flag/${encodeURIComponent(v.trace_id)}`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: $("#v-flag-note").value }) });
  $("#v-flag").hidden = true;
  $("#v-flag-note").value = "";
  const msg = $("#v-flag-msg");
  msg.hidden = false;
  msg.textContent = r.ok ? "Thanks! A grown-up will check this bird." : "Sorry, that didn't work.";
  if (r.ok) { state.flagged[v.trace_id] = true; $("#v-flag-btn").disabled = true; }
});
function step(n) {
  const i = state.open + n;
  if (i >= 0 && i < state.shown.length) { state.open = i; showClip(); }
}
function closeViewer() {
  player.pause();
  player.removeAttribute("src");
  player.load();
  viewer.hidden = true;
  state.open = -1;
  render();
}
$("#v-prev").addEventListener("click", () => step(-1));
$("#v-next").addEventListener("click", () => step(1));
$("#v-close").addEventListener("click", closeViewer);
viewer.addEventListener("click", (e) => { if (e.target === viewer) closeViewer(); });
document.addEventListener("keydown", (e) => {
  if (viewer.hidden || e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft") step(-1);
  else if (e.key === "ArrowRight") step(1);
  else if (e.key === "Escape") closeViewer();
  else return;
  e.preventDefault();
});
let touchX = null;   // swipe left/right on phones
viewer.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
viewer.addEventListener("touchend", (e) => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 60) step(dx < 0 ? 1 : -1);
  touchX = null;
});

// ---- controls -----------------------------------------------------------------------
$$(".sort button").forEach((b) => b.addEventListener("click", () => {
  state.sort = b.dataset.sort; store.set("wbs.kidsSort", state.sort); render();
}));
$("#prev-day").addEventListener("click", () => { state.day = shiftDay(state.day, -1); setUrl(); load(); });
$("#see-yesterday").addEventListener("click", () => { state.day = shiftDay(localToday(), -1); setUrl(); load(); });
$("#next-day").addEventListener("click", () => { if (state.day < localToday()) { state.day = shiftDay(state.day, 1); setUrl(); load(); } });

load();
setInterval(() => { if (state.day === localToday()) load(true); }, 60000);   // new visits appear by themselves
