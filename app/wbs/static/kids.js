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
                sort: store.get("wbs.kidsSort", document.body.dataset.sort || "new"), visits: [], shown: [], open: -1 };

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
  if (how === "bird") return v.sort((a, b) => a.species.localeCompare(b.species) || b.ts - a.ts);
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
  state.visits = data.visits.map((v) => ({ ...v, clip: BASE + v.clip, poster: v.poster && BASE + v.poster }));
  state.counts = data.counts;
  render(keepPlaying);
}

function render(keepPlaying) {
  $("#day-label").textContent = dayLabel(state.day);
  $("#next-day").disabled = state.day >= localToday();
  const total = Object.values(state.counts || {}).reduce((a, b) => a + b, 0);
  $("#subtitle").textContent = total ? `${total} visit${total === 1 ? "" : "s"} ${state.day === localToday() ? "so far today" : ""}` : "Who came to the feeder?";
  $$(".sort button").forEach((b) => b.classList.toggle("on", b.dataset.sort === state.sort));
  // species chips (filter)
  const dots = Object.fromEntries(state.visits.map((v) => [v.species, v.dot]));
  $("#chips").innerHTML = Object.keys(state.counts || {}).length > 1 || state.species
    ? `<button class="chip ${state.species ? "" : "on"}" data-sp="">All birds</button>` +
      Object.entries(state.counts).map(([sp, n]) =>
        `<button class="chip ${sp === state.species ? "on" : ""}" data-sp="${esc(sp)}">${esc(dots[sp] || "")} ${esc(sp)}<b>${n}</b></button>`).join("")
    : "";
  $$("#chips .chip").forEach((c) => c.addEventListener("click", () => { state.species = c.dataset.sp; setUrl(); render(); }));

  const list = state.visits.filter((v) => !state.species || v.species === state.species);
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
      <div class="label"><span>${esc(v.dot || "")} ${esc(v.species)}</span><span class="time">${esc(fmtTime(v.ts))}</span></div>
    </article>`).join("");
  $$("#grid .tile").forEach((t) => {
    const vid = $("video", t);
    t.addEventListener("mouseenter", () => {
      if (!vid.src) vid.src = vid.dataset.src;
      vid.currentTime = 0;
      vid.play().catch(() => {});
    });
    t.addEventListener("mouseleave", () => vid.pause());
    t.addEventListener("click", () => openViewer(+t.dataset.i));
    t.addEventListener("keydown", (e) => { if (e.key === "Enter") openViewer(+t.dataset.i); });
  });
}

// ---- big player ---------------------------------------------------------------------
const viewer = $("#viewer"), player = $("#v-video");
function openViewer(i) {
  $$("#grid video").forEach((v) => v.pause());
  state.open = i;
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
  $("#v-name").textContent = `${v.dot || ""} ${v.species}`;
  $("#v-time").textContent = fmtTime(v.ts);
  $("#v-count").textContent = `${state.open + 1} / ${state.shown.length}`;
  $("#v-prev").disabled = state.open === 0;
  $("#v-next").disabled = state.open === state.shown.length - 1;
}
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
  if (viewer.hidden) return;
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
