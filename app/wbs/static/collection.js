"use strict";
const BASE = document.documentElement.dataset.base || "";   // set when a proxy serves the app under a path
// The collection book: a sticker for every bird found this year, with its first visit; blanks for the rest.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const thisYear = new Date().getFullYear();
let year = parseInt(new URLSearchParams(location.search).get("year"), 10) || thisYear;
const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: "long", day: "numeric" });

async function load() {
  const r = await (await fetch(`${BASE}/api/public/collection?year=${year}`)).json();
  const total = r.found.length + r.to_find.length;
  $("#year-label").textContent = year;
  $("#prev-year").disabled = year <= r.first_year;
  $("#next-year").disabled = year >= thisYear;
  $("#subtitle").textContent = `${r.found.length} of ${total} birds found${year === thisYear ? " so far this year" : ` in ${year}`}`;
  const found = r.found.map((b) => `
    <a class="sticker" href="${BASE}/?species=${encodeURIComponent(b.species)}&day=${new Date(b.first * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)}">
      <img loading="lazy" src="${BASE}${esc(b.portrait)}" alt="">
      <div class="name">${esc(b.species)}</div>
      <div class="when">First seen ${esc(fmtDay(b.first))} · ${b.visits} visit${b.visits === 1 ? "" : "s"}</div>
    </a>`).join("");
  const blanks = year === thisYear ? r.to_find.map((n) => `
    <div class="sticker blank"><div class="q" aria-hidden="true">?</div><div class="name">${esc(n)}</div>
      <div class="when">Still to find</div></div>`).join("") : "";
  $("#book").innerHTML = found + blanks || '<p class="empty">No birds yet.</p>';
}

$("#prev-year").addEventListener("click", () => { year--; history.replaceState(null, "", `?year=${year}`); load(); });
$("#next-year").addEventListener("click", () => { year++; history.replaceState(null, "", year === thisYear ? location.pathname : `?year=${year}`); load(); });
load();
