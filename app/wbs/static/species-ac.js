"use strict";
// Shared by the review page (app.js) and the kids' page (kids.js), so both offer the same species picker.
// Loaded before either of them; it defines only the names below, not $ or esc, which each page has its own of.
const acEsc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- species autocomplete -------------------------------------------------------
// Ranks the species list as you type: "chick" or "bcc" finds Black-capped Chickadee, "black capped" ignores the
// hyphen. The best match is highlighted, so Enter or Tab takes it, and leaving the field completes a partial name.
const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/['’.]/g, "").replace(/[-_/]/g, " ").replace(/\s+/g, " ").trim();
function speciesScore(s, q) {
  const name = s._n ??= norm(s.name), words = (s._w ??= name.split(" "));
  if (name === q) return 0;
  if (name.startsWith(q)) return 1;
  const qw = q.split(" ");
  if (qw.every((w) => words.some((x) => x.startsWith(w)))) return 2;
  if (name.includes(q)) return 3;
  if (!q.includes(" ") && words.map((w) => w[0]).join("").startsWith(q)) return 4;
  if (s.scientific && norm(s.scientific).includes(q)) return 5;
  if (q.length >= 3) { let i = 0; for (const c of name) if (c === q[i]) i++; if (i === q.length) return 6; }
  return null;
}
// Ties go to species you've confirmed more often, then to ones expected around here this month.
function matchSpecies(list, text, limit = 8) {
  const q = norm(text);
  if (!q) return [];
  return list.map((s) => [speciesScore(s, q), s]).filter(([n]) => n !== null)
    .sort(([a, x], [b, y]) => a - b || (y.visits || 0) - (x.visits || 0) || (y.season ?? 1) - (x.season ?? 1) || x.name.localeCompare(y.name))
    .slice(0, limit).map(([, s]) => s);
}
const Autocomplete = {
  list: null, input: null, items: [], active: -1, n: 0,

  // opts: species() -> the list, hints() -> names to offer while the field is empty, pick(name) after a choice.
  attach(input, opts) {
    input.setAttribute("role", "combobox"); input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false"); input.autocomplete = "off"; input.spellcheck = false;
    input._ac = opts;
    input.addEventListener("focus", () => this.open(input));
    input.addEventListener("input", () => this.open(input));
    input.addEventListener("blur", () => { if (this.input === input) { this.complete(input); this.close(); } });
    input.addEventListener("keydown", (e) => this.key(e, input));
  },

  open(input) {
    if (!this.list) {
      this.list = document.createElement("ul");
      this.list.className = "ac"; this.list.id = "ac-list"; this.list.setAttribute("role", "listbox"); this.list.hidden = true;
      // mousedown, not click: the input keeps focus, so its blur doesn't complete to the wrong name first.
      this.list.addEventListener("mousedown", (e) => {
        const li = e.target.closest("li[data-i]");
        e.preventDefault();
        if (li) this.choose(+li.dataset.i);
      });
      document.body.append(this.list);
      const place = () => this.place();
      window.addEventListener("scroll", place, true); window.addEventListener("resize", place);
    }
    this.input = input;
    const opts = input._ac, all = opts.species();
    const text = input.value;
    if (norm(text)) this.items = matchSpecies(all, text);
    else {   // empty: the visit's own suggestions first, then the species you confirm most
      const known = new Map(all.map((s) => [s.name.toLowerCase(), s]));
      const hinted = (opts.hints?.() || []).map((h) => known.get(String(h || "").toLowerCase())).filter(Boolean);
      const top = [...all].filter((s) => s.visits).sort((a, b) => b.visits - a.visits);
      this.items = [...new Set([...hinted, ...top])].slice(0, 8);
    }
    // An exact name stays as typed; otherwise the best match is ready for Enter.
    this.active = this.items.length && norm(text) ? 0 : -1;
    this.render(text);
  },

  render(text) {
    const q = norm(text).split(" ").filter(Boolean);
    const mark = (name) => acEsc(name).replace(new RegExp(`\\b(${q.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") || "$^"})`, "gi"), "<b>$1</b>");
    this.list.innerHTML = this.items.map((s, i) => `<li role="option" id="ac-${++this.n}" data-i="${i}" aria-selected="${i === this.active}"
        class="${i === this.active ? "on" : ""}${s.season === 0 ? " unlikely" : ""}" title="${acEsc(s.season_text ? "This month: " + s.season_text : "")}">
        <span>${q.length ? mark(s.name) : acEsc(s.name)}</span>${s.scientific ? `<i>${acEsc(s.scientific)}</i>` : ""}${s.visits ? `<small>${s.visits}</small>` : ""}</li>`).join("")
      || (q.length ? `<li class="none">Not in the species list</li>` : "");
    const show = !!this.list.innerHTML;
    this.list.hidden = !show;
    this.input.setAttribute("aria-expanded", String(show));
    this.input.setAttribute("aria-controls", "ac-list");
    const on = this.list.querySelector("li.on");
    on ? (this.input.setAttribute("aria-activedescendant", on.id), on.scrollIntoView({ block: "nearest" })) : this.input.removeAttribute("aria-activedescendant");
    this.place();
  },

  place() {
    if (!this.input || this.list.hidden) return;
    const r = this.input.getBoundingClientRect();
    const below = innerHeight - r.bottom;
    Object.assign(this.list.style, { left: r.left + "px", minWidth: r.width + "px",
      top: below < 220 && r.top > below ? "" : r.bottom + 2 + "px", bottom: below < 220 && r.top > below ? innerHeight - r.top + 2 + "px" : "" });
  },

  close() {
    if (this.list) this.list.hidden = true;
    if (this.input) { this.input.setAttribute("aria-expanded", "false"); this.input.removeAttribute("aria-activedescendant"); }
    this.input = null;
  },

  choose(i) {
    const s = this.items[i], input = this.input;
    if (!s || !input) return;
    input.value = s.name;
    this.close();
    input._ac.pick?.(s.name);
  },

  // A partial name becomes its best match; a name already in the list keeps its spelling from the list.
  complete(input) {
    const text = input.value.trim();
    if (!text) return;
    const all = input._ac.species();
    const exact = all.find((s) => norm(s.name) === norm(text));
    const best = exact || (this.input === input && this.active >= 0 ? this.items[this.active] : matchSpecies(all, text, 1)[0]);
    if (best && best.name !== input.value) { input.value = best.name; input._ac.pick?.(best.name); }
  },

  key(e, input) {
    const open = this.input === input && !this.list.hidden && this.items.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!open) { this.open(input); if (this.active < 0 && this.items.length) { this.active = 0; this.render(input.value); } e.preventDefault(); return; }
      const n = this.items.length;
      this.active = e.key === "ArrowDown" ? (this.active + 1) % n : (this.active - 1 + n) % n;
      this.render(input.value); e.preventDefault();
    } else if ((e.key === "Enter" || e.key === "Tab") && open && this.active >= 0) {
      if (e.key === "Tab") { this.choose(this.active); return; }
      this.choose(this.active);   // the input's own Enter handler then runs with the chosen name
    } else if (e.key === "Enter") {
      this.complete(input); this.close();
    } else if (e.key === "Escape" && this.input === input && !this.list.hidden) {
      this.close(); e.preventDefault(); e.stopImmediatePropagation();   // only the list closes, not a frame tag
    }
  },
};
