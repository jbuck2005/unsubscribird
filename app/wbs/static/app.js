"use strict";
const BASE = document.documentElement.dataset.base || "";   // set when a proxy serves the app under a path
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (url, opts = {}) => {
  const r = await fetch(BASE + url, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
};
const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

// ---- lightbox -----------------------------------------------------------------
const lightbox = $("#lightbox");
function zoom(src) { $("img", lightbox).src = src; lightbox.hidden = false; }
lightbox.addEventListener("click", () => (lightbox.hidden = true));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") lightbox.hidden = true; });

// ---- review page ----------------------------------------------------------------
const Review = {
  queue: "review", offset: 0, visits: [], focus: 0, species: [],

  async init() {
    this.species = await api("/api/species");
    $("#species-list").innerHTML = this.species.map((s) => `<option value="${esc(s.name)}">`).join("");
    $$("#queues button").forEach((b) => b.addEventListener("click", () => this.switchQueue(b.dataset.q)));
    $("#more").addEventListener("click", () => this.load(true));
    $("#confirm-all").addEventListener("click", () => this.confirmAll());
    document.addEventListener("keydown", (e) => this.key(e));
    const only = new URLSearchParams(location.search).get("visit");
    if (only) {   // opened from the Model page: show just this visit
      const v = await api(`/api/visits/${encodeURIComponent(only)}`);
      this.visits = [v];
      $("#visits").innerHTML = `<p class="hint">Showing one visit. <a href="${BASE}/admin">Back to the queue</a></p>`;
      $("#visits").append(this.card(v, 0));
      this.setFocus(0, false); this.updateConfirmAll(); this.counts();
      return;
    }
    await this.load();
    this.counts();
    setInterval(() => this.counts(), 30000);
  },

  async counts() {
    for (const q of ["review", "uncertain", "disagree", "check", "waiting", "labelled", "failed", "excluded"]) {
      const r = await api(`/api/visits?queue=${q}&limit=0`);
      $(`[data-count="${q}"]`).textContent = r.total;
    }
  },

  switchQueue(q) {
    this.queue = q;
    $(".hint").innerHTML = q === "check"
      ? "Confirmed visits the latest model doubts, most doubtful first. It checked each one <b>without having seen it</b> (cross-validation). <b>Keep</b> if your label is right, type a new species and <b>Update</b> if not, or <b>Exclude</b> a visit that shouldn't train at all."
      : q === "excluded" ? "Visits kept out of training. <b>Restore</b> puts one back."
      : q === "disagree" ? "Visits to review where the trained model and LM Studio name different things, newest first. Each card starts on LM Studio's answer, so check the frames before you confirm. These are also in <b>To review</b>; a squirrel and a bird in one clip often lands here. <b>Confirm all</b> skips them: confirm each with Enter (or change the card first)."
      : "Correct any visits that are wrong, then <b>Confirm all</b> saves every loaded visit with its current species. Only confirmed visits become training data. Frames with a ✓ are used; click a frame to include or exclude it, ↻ to swap a blurry frame for a sharper one from the clip, or 🏷 when a frame shows another species (a squirrel in a chickadee visit).";
    $$("#queues button").forEach((b) => b.classList.toggle("on", b.dataset.q === q));
    this.load();
  },

  async load(more = false) {
    if (!more) { this.offset = 0; this.visits = []; this.focus = 0; $("#visits").innerHTML = ""; }
    const r = await api(`/api/visits?queue=${this.queue}&limit=50&offset=${this.offset}`);
    this.offset += r.visits.length;
    for (const v of r.visits) { this.visits.push(v); $("#visits").append(this.card(v, this.visits.length - 1)); }
    $("#more").hidden = this.offset >= r.total;
    if (!this.visits.length) $("#visits").innerHTML = `<div class="empty-state">Nothing here yet.</div>`;
    this.setFocus(this.focus, false);
    this.updateConfirmAll();
  },

  // Which frames to include by default for a given species.
  defaultFrames(v, species) {
    const byFrame = Object.fromEntries(v.suggestions.filter((s) => s.frame_id).map((s) => [s.frame_id, s]));
    const isEmpty = species === "Empty";
    const chosen = v.frames.filter((f) => {
      const s = byFrame[f.id];
      if (!s) return true;
      if (isEmpty) return !s.bird_present && !s.other_animal;
      if (["Squirrel", "Chipmunk", "Other animal"].includes(species)) return !!s.other_animal;
      return !!s.bird_present;
    }).map((f) => f.id);
    return chosen.length ? chosen : v.frames.map((f) => f.id);
  },

  card(v, i) {
    // Vicohome's own snapshot is a 640x360 thumbnail: only show it when the visit has no clip frames.
    if (v.frames.some((f) => f.kind === "clip")) v.frames = v.frames.filter((f) => f.kind === "clip");
    const el = document.createElement("section");
    el.className = "visit" + (v.label ? " done" : "");
    el.tabIndex = 0;
    el.dataset.i = i;
    const cons = v.consensus;
    const initial = v._preset?.species ?? (v.label?.species || (cons && cons.known ? cons.species : ""));
    v._species = initial;
    v._frames = v._preset?.frames ?? new Set(v.label ? v.label.frame_ids : this.defaultFrames(v, initial));
    // Mixed visits: frame id -> the species that frame shows instead of the visit's species.
    v._fs = v._preset?.fs ?? new Map(Object.entries(v.label?.frame_species || {}).map(([k, s]) => [+k, s]));
    v._edited = !!v._preset?.edited;
    const byFrame = Object.fromEntries(v.suggestions.filter((s) => s.frame_id).map((s) => [s.frame_id, s]));
    const frames = v.frames.map((f, n) => {
      const s = byFrame[f.id];
      // LM Studio's guess for this frame, never the label: say so, so it isn't mistaken for what the frame counts as.
      const cap = s ? "LM Studio: " + (s.bird_present ? `${esc(s.species || "bird?")} ${s.confidence != null ? Math.round(s.confidence * 100) + "%" : ""}`
        : esc(s.other_animal || "no bird")) : (f.kind === "snapshot" ? "snapshot" : "LM Studio: not checked");
      const why = s?.notes ? `<br><span class="why">${esc(s.notes)}</span>` : "";
      return `<div class="frame ${v._frames.has(f.id) ? "in" : ""}" data-f="${f.id}">
          <div class="imgwrap"><img loading="lazy" src="${BASE}/img/${esc(f.thumb || f.path)}" data-full="${BASE}/img/${esc(f.path)}" alt="">
          ${f.x1 != null ? `<span class="det ${f.det_source}" title="${f.det_source === "owlvit" ? `detector: ${esc(f.det_label)} ${Math.round(f.det_score * 100)}%` : "moving region"}"
            style="left:${f.x1 * 100}%;top:${f.y1 * 100}%;width:${(f.x2 - f.x1) * 100}%;height:${(f.y2 - f.y1) * 100}%"></span>` : ""}</div>
          <span class="tick">${v._frames.has(f.id) ? "✓" : "✕"}</span><span class="num">${n + 1}${f.t != null ? " · " + f.t + "s" : ""}</span>
          ${v.clip ? `<button class="regrab" title="Blurry? Grab a different frame from the clip (Shift+${n + 1})">↻</button>` : ""}
          <button class="tagbtn" title="This frame shows a different species (Alt+${n + 1}, or t then ${n + 1})">🏷</button>
          <span class="ftag" ${v._fs.has(f.id) ? "" : "hidden"}>${esc(v._fs.get(f.id) || "")}</span>
          <div class="cap">${cap}${why}</div></div>`;
    }).join("");
    const other = (s, label) => s ? `<span class="chip alt" title="${esc(s.notes || "")}">${label}: ${esc(s.species || "–")} ${s.confidence != null ? Math.round(s.confidence * 100) + "%" : ""}</span>` : "";
    const ck = v.check;
    const checkChip = ck && v.label ? `<span class="chip ${ck.predicted !== v.label.species ? "unknown" : "alt"}" title="Cross-check by model v${ck.model}, which did not see this visit while training">
        Cross-check: ${esc(ck.predicted)} ${Math.round(ck.p_predicted * 100)}%${ck.predicted !== v.label.species ? ` · your label ${Math.round(ck.p_label * 100)}%` : ""}</span>` : "";
    const altChips = checkChip + other(v.model, `Model ${esc(v.model?.model || "")}`) + other(v.bioclip, "BioCLIP") +
      (v.rec_species ? `<span class="chip ${v.rec_source === "uncertain" ? "unknown" : "alt"}" title="Sent to Home Assistant">HA: ${esc(v.rec_species)}${v.rec_guess ? " (" + esc(v.rec_guess) + "?)" : ""}</span>` : "");
    const consChip = cons ? `<span class="chip sugg ${cons.known ? "" : "unknown"}" title="${cons.known ? "" : "Not in the species list"}">
        Suggested: ${esc(cons.species)} · ${Math.round(cons.confidence * 100)}% · ${cons.votes}/${cons.frames} frames</span>` : "";
    el.innerHTML = `
      <div class="vhead"><span class="time">${esc(fmtTime(v.time))}</span>
        ${v.disagree && !v.label ? `<span class="chip unknown" title="The trained model and LM Studio name different things: look before confirming">⚠ disagree</span>` : ""}
        ${consChip}${altChips}
        ${v.quiet ? '<span class="chip alt" title="The frame picker saw no movement in the clip, so LM Studio was skipped">nothing moved</span>' : ""}
        ${v.error ? `<span class="meta err">${esc(v.error)}</span>` : ""}
        ${v.label ? `<span class="chip label">✓ ${esc(v.label.species)}${(v.label.also || []).length ? " + " + esc(v.label.also.join(", ")) : ""}</span>` : ""}
        <span class="chip edited" ${v._edited ? "" : "hidden"}>✎ changed</span>
        ${v.clip_href ? `<a class="meta" href="${BASE}${esc(v.clip_href)}" target="_blank" title="Play the clip (Save as keeps this name)">▶ ${esc(v.clip_name)}</a>` : ""}</div>
      <div class="frames">${frames || '<span class="msg">No frames yet.</span>'}</div>
      <div class="actions">
        <input list="species-list" placeholder="Species…" value="${esc(initial)}">
        <button class="btn primary" data-a="confirm">${v.label ? "Update" : "Confirm"} ⏎</button>
        <button class="btn" data-a="Empty" title="Set to Empty (confirm later)">Empty (e)</button>
        <button class="btn" data-a="Squirrel">Squirrel (s)</button>
        <button class="btn" data-a="Unknown bird">Unknown bird (u)</button>
        ${v.label ? '<button class="btn" data-a="unlabel">Remove label</button>' : ""}
        ${v.label && v.check ? '<button class="btn" data-a="keep" title="Your label is right (c)">Keep ✓ (c)</button>' : ""}
        <button class="btn" data-a="${v.excluded ? "restore" : "exclude"}" title="${v.excluded ? "Use this visit again" : "Keep this visit out of training"}">${v.excluded ? "Restore" : "Exclude"}</button>
        <span class="msg"></span>
      </div>`;
    $$(".frame .regrab", el).forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation(); this.regrab(v, el, +b.closest(".frame").dataset.f);
    }));
    $$(".frame", el).forEach((fe) => {
      fe.addEventListener("click", (e) => {
        if (e.target.closest(".tagbtn")) { e.stopPropagation(); return this.tagFrame(v, el, +fe.dataset.f); }
        if (e.target.closest(".ftagin")) return;
        if (e.shiftKey) return zoom($("img", fe).dataset.full);
        this.toggle(v, el, +fe.dataset.f);
      });
      fe.addEventListener("dblclick", () => zoom($("img", fe).dataset.full));
    });
    const input = $(".actions input", el);
    input.addEventListener("change", () => this.pickSpecies(v, el, input.value));
    input.addEventListener("input", () => { v._species = input.value; this.markEdited(v, el); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); this.pickSpecies(v, el, input.value); this.save(v, el); } });
    $$("button[data-a]", el).forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.a;
      if (a === "confirm") this.save(v, el);
      else if (a === "unlabel") this.unlabel(v, el);
      else if (a === "keep") this.keep(v, el);
      else if (a === "exclude" || a === "restore") this.exclude(v, el, a === "exclude");
      else { this.pickSpecies(v, el, a); }
    }));
    el.addEventListener("focus", () => this.setFocus(i, false));
    return el;
  },

  toggle(v, el, id) {
    v._frames.has(id) ? v._frames.delete(id) : v._frames.add(id);
    const fe = $(`.frame[data-f="${id}"]`, el);
    fe.classList.toggle("in", v._frames.has(id));
    $(".tick", fe).textContent = v._frames.has(id) ? "✓" : "✕";
    this.markEdited(v, el);
  },

  // Mark one frame as showing another species (a squirrel in a chickadee visit). Empty or the visit's own species
  // clears it. The frame is ticked, since only ticked frames are training data.
  tagFrame(v, el, fid) {
    const fe = $(`.frame[data-f="${fid}"]`, el);
    if (!fe || $(".ftagin", fe)) return;
    const inp = document.createElement("input");
    inp.className = "ftagin"; inp.setAttribute("list", "species-list");
    inp.placeholder = "This frame shows…"; inp.value = v._fs.get(fid) || "";
    $(".imgwrap", fe).append(inp);
    // Kept on Enter, on picking from the list, and on clicking away (e.g. straight to Update): only Esc cancels.
    let closed = false;
    const done = (apply, refocus) => {
      if (closed) return;
      closed = true;
      if (apply && inp.value.trim() !== (v._fs.get(fid) || "")) this.setTag(v, el, fid, inp.value.trim());
      inp.remove();
      if (refocus) el.focus({ preventScroll: true });
    };
    inp.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); done(true, true); }
      else if (e.key === "Escape") { e.preventDefault(); done(false, true); }
    });
    inp.addEventListener("change", () => done(true, false));
    inp.addEventListener("blur", () => done(true, false));
    inp.focus(); inp.select();
  },

  setTag(v, el, fid, name) {
    const known = this.species.find((s) => s.name.toLowerCase() === name.toLowerCase());
    const main = ($(".actions input", el).value || "").trim().toLowerCase();
    const msg = $(".msg", el);
    if (name && !known) { msg.className = "msg err"; msg.textContent = `'${name}' is not in the species list.`; return; }
    const n = v.frames.findIndex((f) => f.id === fid) + 1;
    const mainName = ($(".actions input", el).value || "").trim() || "the visit's species";
    const had = v._fs.get(fid);
    const save = v.label ? "Update" : "Confirm";
    msg.className = "msg";
    if (!name || known.name.toLowerCase() === main) {
      if (!had && v._frames.has(fid)) {   // nothing to change: say so instead of doing nothing silently
        msg.textContent = `Frame ${n} already counts as ${mainName} (the visit's species).`;
        return;
      }
      v._fs.delete(fid);
      if (!v._frames.has(fid)) this.toggle(v, el, fid);
      msg.textContent = `Frame ${n} now counts as ${mainName} (the visit's species). Press ${save} to save.`;
    } else {
      v._fs.set(fid, known.name);
      if (!v._frames.has(fid)) this.toggle(v, el, fid);
      msg.textContent = `Frame ${n} now counts as ${known.name}. Press ${save} to save.`;
    }
    const tag = $(`.frame[data-f="${fid}"] .ftag`, el);
    tag.textContent = v._fs.get(fid) || ""; tag.hidden = !v._fs.has(fid);
    this.markEdited(v, el);
  },

  // What the API gets: per-frame species of ticked frames only.
  frameSpecies(v) {
    return Object.fromEntries([...v._fs].filter(([fid]) => v._frames.has(fid)));
  },

  async regrab(v, el, fid) {
    const fe = $(`.frame[data-f="${fid}"]`, el);
    const msg = $(".msg", el);
    fe.classList.add("busy"); msg.className = "msg"; msg.textContent = "Grabbing a different frame…";
    try {
      const r = await api(`/api/frames/${fid}/replace`, { method: "POST" });
      const nv = await api(`/api/visits/${v.trace_id}`);
      const frames = new Set([...v._frames].filter((x) => x !== fid));
      if (v._frames.has(fid) || !frames.size) frames.add(r.frame.id);
      const fs = new Map(v._fs);
      if (fs.has(fid)) { fs.set(r.frame.id, fs.get(fid)); fs.delete(fid); }
      nv._preset = { species: $(".actions input", el).value, frames, fs, edited: v._edited };
      const i = this.visits.indexOf(v);
      this.visits[i] = nv;
      const ne = this.card(nv, i);
      el.replaceWith(ne);
      const s = r.suggestion;
      $(".msg", ne).textContent = `Replaced with the frame at ${r.frame.t}s` +
        (s ? ` (model: ${s.bird_present ? (s.species || "bird") : (s.other_animal || "no bird")})` : " (model not available)") + ".";
      this.setFocus(i, false);
    } catch (err) { fe.classList.remove("busy"); msg.className = "msg err"; msg.textContent = err.message; }
  },

  markEdited(v, el) {
    v._edited = true;
    const badge = $(".chip.edited", el);
    if (badge) badge.hidden = false;
    el.classList.remove("skipped");
    this.updateConfirmAll();
  },

  // Visits "Confirm all" would save: loaded, not yet labelled.
  pending() {
    return this.visits.map((v, i) => ({ v, el: $$(".visit")[i] })).filter(({ v, el }) => el && !v.label && !v.excluded);
  },

  // The model and LM Studio disagree and nobody has touched the card: Confirm all would save LM Studio's guess
  // unseen, so it leaves these for one-by-one review (Enter). Changing the card on purpose releases it.
  held(v) { return !!v.disagree && !v._edited; },

  // Labelled cards with changes (species, frames, frame tags) that only Update saves: Confirm all never does.
  unsaved() {
    return this.visits.map((v, i) => ({ v, el: $$(".visit")[i] })).filter(({ v, el }) => el && v.label && v._edited);
  },

  updateConfirmAll() {
    const b = $("#confirm-all");
    if (!b) return;
    const n = this.pending().filter(({ v }) => !this.held(v)).length;
    b.textContent = `Confirm all (${n})`;
    b.disabled = n === 0;
  },

  async confirmAll() {
    const known = new Set(this.species.map((s) => s.name.toLowerCase()));
    const items = [], skipped = [], held = [];
    for (const { v, el } of this.pending()) {
      const species = ($(".actions input", el).value || "").trim();
      if (this.held(v)) { held.push(el); continue; }
      if (!species || !known.has(species.toLowerCase()) || !v._frames.size) { skipped.push(el); continue; }
      items.push({ trace_id: v.trace_id, species, frame_ids: [...v._frames], frame_species: this.frameSpecies(v), _v: v, _el: el });
    }
    const unsaved = this.unsaved().map(({ el }) => el);
    const mark = (els, text) => els.forEach((el) => { el.classList.add("skipped"); const m = $(".msg", el); m.className = "msg err"; m.textContent = text; });
    mark(skipped, "Skipped by Confirm all: pick a species from the list (and at least one frame).");
    mark(held, "Skipped by Confirm all: the model and LM Studio disagree. Check the frames, then confirm this one (Enter).");
    mark(unsaved, "Not saved: Confirm all only saves new visits. Press Update to save your changes to this label.");
    const notes = [
      held.length && `${held.length} skipped: the model and LM Studio disagree (check each, then Enter)`,
      skipped.length && `${skipped.length} skipped: no valid species`,
      unsaved.length && `${unsaved.length} already-labelled visit(s) have unsaved changes: press Update on each`,
    ].filter(Boolean);
    if (!items.length) {
      alert("Nothing to confirm." + (notes.length ? "\n\n" + notes.join("\n") : "\n\nEvery loaded visit needs a species from the list."));
      const first = $$(".visit").findIndex((c) => held.includes(c) || unsaved.includes(c));
      if (first >= 0) this.setFocus(first);
      return;
    }
    const tally = {};
    items.forEach((it) => (tally[it.species] = (tally[it.species] || 0) + 1));
    const summary = Object.entries(tally).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ×${n}`).join(", ");
    const edited = items.filter((it) => it._v._edited).length;
    if (!confirm(`Confirm ${items.length} visit(s) as training data?\n\n${summary}\n\n${edited} changed by you.` +
                 (notes.length ? "\n\n" + notes.join("\n") : ""))) return;
    const btn = $("#confirm-all"); btn.disabled = true; btn.textContent = "Saving…";
    try {
      const r = await api("/api/labels/batch", { method: "POST",
        body: JSON.stringify(items.map(({ trace_id, species, frame_ids, frame_species }) => ({ trace_id, species, frame_ids, frame_species }))) });
      r.results.forEach((res, n) => {
        const { _v: v, _el: el } = items[n];
        const m = $(".msg", el);
        if (res.ok) { v.label = { species: res.species, frame_ids: items[n].frame_ids, frame_species: res.frame_species, also: res.also }; el.classList.add("done");
          v._edited = false; const badge = $(".chip.edited", el); if (badge) badge.hidden = true;
          m.className = "msg"; m.textContent = `Saved: ${res.species} (${res.source}).`; }
        else { el.classList.add("skipped"); m.className = "msg err"; m.textContent = res.error; }
      });
      $("#batch-msg").textContent = `Saved ${r.saved}` + (r.failed ? `, ${r.failed} failed (marked in red)` : "") + ".";
    } catch (err) { $("#batch-msg").textContent = err.message; }
    this.counts();
    this.updateConfirmAll();
  },

  pickSpecies(v, el, name) {
    v._species = name;
    $(".actions input", el).value = name;
    this.markEdited(v, el);
    if (!v.label) {
      v._frames = new Set(this.defaultFrames(v, name));
      $$(".frame", el).forEach((fe) => {
        const on = v._frames.has(+fe.dataset.f);
        fe.classList.toggle("in", on); $(".tick", fe).textContent = on ? "✓" : "✕";
      });
    }
  },

  async save(v, el) {
    const msg = $(".msg", el);
    const species = ($(".actions input", el).value || "").trim();
    if (!species) { msg.className = "msg err"; msg.textContent = "Type or pick a species first."; return; }
    try {
      const r = await api(`/api/visits/${v.trace_id}/label`, { method: "POST",
        body: JSON.stringify({ species, frame_ids: [...v._frames], frame_species: this.frameSpecies(v) }) });
      v.label = { species: r.species, frame_ids: [...v._frames], frame_species: r.frame_species, also: r.also };
      v._edited = false; const badge = $(".chip.edited", el); if (badge) badge.hidden = true;
      el.classList.add("done"); el.classList.remove("skipped");
      msg.className = "msg"; msg.textContent = `Saved: ${r.species}${r.also.length ? " + " + r.also.join(", ") : ""} (${r.source}).`;
      this.counts(); this.updateConfirmAll();
      this.setFocus(this.focus + 1);
    } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
  },

  async keep(v, el) {
    try {
      await api(`/api/visits/${v.trace_id}/keep`, { method: "POST" });
      el.classList.add("done"); $(".msg", el).className = "msg"; $(".msg", el).textContent = "Kept: label is right.";
      this.counts(); this.setFocus(this.focus + 1);
    } catch (err) { $(".msg", el).className = "msg err"; $(".msg", el).textContent = err.message; }
  },

  async exclude(v, el, on) {
    try {
      await api(`/api/visits/${v.trace_id}/exclude`, { method: "POST", body: JSON.stringify({ excluded: on }) });
      v.excluded = on ? 1 : 0;
      el.classList.add("done"); $(".msg", el).className = "msg";
      $(".msg", el).textContent = on ? "Excluded from training." : "Restored.";
      const b = $(`button[data-a="${on ? "exclude" : "restore"}"]`, el);
      if (b) { b.dataset.a = on ? "restore" : "exclude"; b.textContent = on ? "Restore" : "Exclude"; }
      this.counts(); this.updateConfirmAll(); this.setFocus(this.focus + 1);
    } catch (err) { $(".msg", el).className = "msg err"; $(".msg", el).textContent = err.message; }
  },

  async unlabel(v, el) {
    await api(`/api/visits/${v.trace_id}/label`, { method: "DELETE" });
    v.label = null; el.classList.remove("done"); $(".msg", el).textContent = "Label removed."; this.counts(); this.updateConfirmAll();
  },

  setFocus(i, scroll = true) {
    const cards = $$(".visit");
    if (!cards.length) return;
    this.focus = Math.max(0, Math.min(i, cards.length - 1));
    cards.forEach((c, n) => c.classList.toggle("focus", n === this.focus));
    if (scroll) { cards[this.focus].scrollIntoView({ block: "center", behavior: "smooth" }); cards[this.focus].focus({ preventScroll: true }); }
  },

  key(e) {
    if (e.target.tagName === "INPUT" || e.ctrlKey || e.metaKey || !lightbox.hidden) return;
    const el = $$(".visit")[this.focus];
    const v = this.visits[this.focus];
    if (!el || !v) return;
    const k = e.key;
    const tagging = this._tagNext; this._tagNext = false;
    const digit = /^Digit[1-9]$/.test(e.code) ? +e.code.slice(5) : 0;
    if (e.altKey) {   // Alt+1-6: species of one frame (some browsers keep Alt+digit for tabs: use t, then the digit)
      if (!digit || !v.frames[digit - 1]) return;
      this.tagFrame(v, el, v.frames[digit - 1].id);
    }
    else if (tagging && digit) { if (v.frames[digit - 1]) this.tagFrame(v, el, v.frames[digit - 1].id); }
    else if (k === "t") { this._tagNext = true; }
    else if (k === "j") this.setFocus(this.focus + 1);
    else if (k === "k") this.setFocus(this.focus - 1);
    else if (k === "x") this.setFocus(this.focus + 1);
    else if (k === "Enter") this.save(v, el);
    else if (k === "/") { e.preventDefault(); $(".actions input", el).focus(); $(".actions input", el).select(); }
    else if (k === "e") { this.pickSpecies(v, el, "Empty"); this.setFocus(this.focus + 1); }
    else if (k === "s") { this.pickSpecies(v, el, "Squirrel"); this.setFocus(this.focus + 1); }
    else if (k === "u") { this.pickSpecies(v, el, "Unknown bird"); this.setFocus(this.focus + 1); }
    else if (k === "A") { this.confirmAll(); }
    else if (k === "c" && v.label && v.check) { this.keep(v, el); }
    else if (k === "z") { const f = $(".frame img", el); if (f) zoom(f.dataset.full); }
    else if (e.shiftKey && /^Digit[1-9]$/.test(e.code)) { const f = v.frames[+e.code.slice(5) - 1]; if (f && v.clip) this.regrab(v, el, f.id); }
    else if (/^[1-9]$/.test(k)) { const f = v.frames[+k - 1]; if (f) this.toggle(v, el, f.id); }
    else return;
    e.preventDefault();
  },
};

// ---- dataset page ---------------------------------------------------------------
// Column sort for the Dataset table (kept per browser). Numbers sort high-to-low first, text A-Z; ties by name.
const NUMERIC_COLS = new Set(["visits", "frames", "corrected"]);
function sortRows(rows, key, dir) {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[key] ?? "", y = b[key] ?? "";
    const c = NUMERIC_COLS.has(key) ? (x - y) : String(x).localeCompare(String(y));
    return c * sign || a.name.localeCompare(b.name);
  });
}
const DatasetSort = {
  get() {
    try { const v = JSON.parse(localStorage.getItem("wbs.datasetSort")); if (v && v.key && !["kind", "family_name"].includes(v.key)) return v; } catch (e) { /* no storage */ }
    return { key: "name", dir: "asc" };
  },
  click(key) {
    const cur = this.get();
    const next = cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" }
                                 : { key, dir: NUMERIC_COLS.has(key) ? "desc" : "asc" };
    try { localStorage.setItem("wbs.datasetSort", JSON.stringify(next)); } catch (e) { /* no storage */ }
    return next;
  },
};

async function datasetPage() {
  const [species, stats] = await Promise.all([api("/api/species"), api("/api/stats")]);
  const bySp = Object.fromEntries(stats.by_species.map((s) => [s.species, s]));
  const withData = stats.by_species.length;
  $("#summary").innerHTML = [
    ["Confirmed visits", stats.labelled_visits], ["Training frames", stats.labelled_frames],
    ["Species with data", withData],
    ["Model agreed", stats.vlm_agreement == null ? "–" : Math.round(stats.vlm_agreement * 100) + "%"],
  ].map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  // Grouped by how likely the species is around Ottawa this month; sorting happens WITHIN each group.
  const groups = [[2, "Expected this month", "s-expected"], [1, "Possible, likely migrating", "s-possible"],
                  [0, "Very unlikely this month", "s-unlikely"], [null, "Not birds and other labels", ""]];
  const rows = species.map((s) => ({ ...s, ...(bySp[s.name] ? { visits: bySp[s.name].visits || 0, frames: bySp[s.name].frames || 0,
                                                              corrected: bySp[s.name].corrected || 0 } : { visits: 0, frames: 0, corrected: 0 }) }));
  const render = () => {
    const { key, dir } = DatasetSort.get();
    $$("#species-table thead th[data-sort]").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.sort === key);
      th.dataset.arrow = th.dataset.sort === key ? (dir === "asc" ? "▲" : "▼") : "";
    });
    $("#species-table tbody").innerHTML = groups.map(([lvl, title, cls]) => {
      const members = sortRows(rows.filter((s) => (s.season ?? null) === lvl), key, dir);
      if (!members.length) return "";
      const seen = members.filter((s) => s.visits > 0).length;
      return `<tr class="group ${cls}"><th colspan="6">${esc(title)} <span class="msg">· ${members.length} species${seen ? `, ${seen} with confirmed visits` : ""}</span></th></tr>` +
        members.map((s) => `<tr class="${s.visits ? "" : "zero"} ${cls}" title="${esc(s.season_text ? "Ottawa this month: " + s.season_text : "")}">
          <td>${esc(s.name)}</td><td><i>${esc(s.scientific)}</i></td>
          <td>${s.family ? `<i>${esc(s.family)}</i> <span class="msg">${esc(s.family_name)}</span>` : '<span class="msg">–</span>'}</td>
          <td class="n">${s.visits}</td><td class="n">${s.frames}</td><td class="n">${s.corrected}</td></tr>`).join("");
    }).join("");
  };
  $$("#species-table thead th[data-sort]").forEach((th) => {
    th.onclick = () => { DatasetSort.click(th.dataset.sort); render(); };
  });
  render();
  $("#add-species").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await api("/api/species", { method: "POST", body: JSON.stringify(Object.fromEntries(f)) });
      $("#add-msg").textContent = "Added."; e.target.reset(); datasetPage();
    } catch (err) { $("#add-msg").textContent = err.message; }
  }, { once: true });
}

// ---- status page ------------------------------------------------------------------
async function statusPage() {
  const s = await api("/api/stats");
  const v = s.visits;
  $("#status").innerHTML = [
    ["Visits", Object.values(v).reduce((a, b) => a + b, 0)],
    ["To review", v.prelabelled || 0], ["Waiting for frames/model", (v.new || 0) + (v.frames || 0)], ["Failed", v.failed || 0],
    ["MQTT", s.collector.mqtt, true], ["Clips fetched", s.collector.clips],
    ["LM Studio", s.prelabel.lmstudio, true], ["Seconds per frame", s.prelabel.seconds_per_frame ?? "–"],
    ["Empty clips deleted", s.retention.empty_clip_days ? `${s.retention.clips_removed} (after ${s.retention.empty_clip_days} days)` : "off", true],
    ["NAS free", s.disk ? `${s.disk.free_gb} GB` : "–"],
  ].map(([k, val, small]) => `<div class="card"><div class="k">${k}</div><div class="v ${small ? "small" : ""}">${esc(val)}</div></div>`).join("");
  $("#raw").textContent = JSON.stringify(s, null, 2);
}

// ---- gallery page (linked from Home Assistant's "Recently seen") -------------------------
async function galleryPage() {
  const q = new URLSearchParams(location.search);
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const day = q.get("day") || today;
  const species = q.get("species") || "";
  const go = (d, s) => { const p = new URLSearchParams(); if (d !== today) p.set("day", d); if (s) p.set("species", s);
    location.search = p.toString(); };
  const shift = (n) => { const d = new Date(day + "T12:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const g = await api(`/api/gallery?day=${day}${species ? "&species=" + encodeURIComponent(species) : ""}`);
  $("#g-day").value = day;
  $("#g-day").max = today;
  $("#g-next").disabled = day >= today;
  $("#g-prev").onclick = () => go(shift(-1), species);
  $("#g-next").onclick = () => go(shift(1), species);
  $("#g-day").onchange = (e) => go(e.target.value, species);
  const sel = $("#g-species");
  sel.innerHTML = `<option value="">All species (${Object.values(g.counts).reduce((a, b) => a + b, 0)})</option>` +
    Object.entries(g.counts).map(([k, n]) => `<option value="${esc(k)}" ${k === species ? "selected" : ""}>${esc(k)} (${n})</option>`).join("") +
    (species && !(species in g.counts) ? `<option selected value="${esc(species)}">${esc(species)} (0)</option>` : "");
  sel.onchange = (e) => go(day, e.target.value);
  const when = new Date(day + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  $("#g-title").textContent = `${species || "All species"} · ${day === today ? "today" : when}`;
  $("#g-summary").textContent = g.visits.length ? `${g.visits.length} visit(s), newest first. Click a frame to zoom.` : "No visits for this day.";
  const src = { model: "model", lmstudio: "LM Studio", confirmed: "confirmed", motion: "no motion", uncertain: "not sure" };
  $("#g-visits").innerHTML = g.visits.map((v) => `
    <section class="visit">
      <div class="vhead"><span class="time">${esc(new Date(v.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span>
        <span class="chip ${v.confirmed ? "label" : "sugg"}">${esc(v.species)}</span>
        <span class="meta">${v.confirmed ? "confirmed by you" : `${src[v.rec_source] || esc(v.rec_source)} · ${Math.round((v.rec_conf || 0) * 100)}%`}</span>
        ${v.clip_href ? `<a class="meta" href="${BASE}${esc(v.clip_href)}" target="_blank" title="Play the clip (Save as keeps this name)">▶ ${esc(v.clip_name)}</a>` : ""}
        <a class="meta" href="${BASE}/admin?visit=${esc(v.trace_id)}">review ↗</a></div>
      <div class="frames">${v.frames.filter((f) => f.kind === "clip" || v.frames.length === 1).map((f) => `
        <div class="frame in"><div class="imgwrap"><img loading="lazy" src="${BASE}/img/${esc(f.thumb || f.path)}" data-full="${BASE}/img/${esc(f.path)}" alt="">
          ${f.x1 != null ? `<span class="det ${f.det_source}" style="left:${f.x1 * 100}%;top:${f.y1 * 100}%;width:${(f.x2 - f.x1) * 100}%;height:${(f.y2 - f.y1) * 100}%"></span>` : ""}</div></div>`).join("")}</div>
    </section>`).join("");
  $$("#g-visits .frame img").forEach((img) => img.addEventListener("click", () => zoom(img.dataset.full)));
}

const page = document.body.dataset.page;
if (page === "gallery") galleryPage();
if (page === "review") Review.init();
if (page === "dataset") datasetPage();
if (page === "status") { statusPage(); setInterval(statusPage, 10000); }
if (page === "settings") settingsPage();

// ---- model page ---------------------------------------------------------------------
const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
async function modelPage(first = false) {
  const m = await api("/api/model");
  const t = m.trainer;
  $("#progress").innerHTML = [
    ["Frames with features", `${m.embedded} / ${m.frames}`, m.frames ? m.embedded / m.frames : 0],
    ["Confirmed frames ready", `${m.labelled_embedded} / ${m.labelled_frames}`, m.labelled_frames ? m.labelled_embedded / m.labelled_frames : 0],
    ["Feature extraction", `${m.embed.state}${m.embed.seconds_per_frame ? " · " + m.embed.seconds_per_frame + " s/frame" : ""}`],
    ["Trainer", `${t.state}${t.message ? ": " + t.message : ""}`],
  ].map(([k, v, f]) => `<div class="card"><div class="k">${k}</div><div class="v small">${esc(v)}</div>${f != null ? `<div class="bar"><i style="width:${Math.round(f * 100)}%"></i></div>` : ""}</div>`).join("");
  $("#minv").textContent = m.min_visits;
  const sp = Object.entries(m.visits_per_species).sort((a, b) => b[1] - a[1]);
  $("#per-species").innerHTML = sp.length ? sp.map(([k, n]) =>
    `<span class="chip ${n >= m.min_visits ? "sugg" : ""}" style="margin:0 6px 6px 0">${esc(k)} ${n}</span>`).join("") : '<span class="msg">No confirmed visits yet.</span>';
  const btn = $("#train");
  btn.disabled = t.state === "running";
  if (first) btn.addEventListener("click", async () => {
    try { await api("/api/model/train", { method: "POST" }); $("#train-msg").textContent = "Training…"; modelPage(); }
    catch (err) { $("#train-msg").textContent = err.message; }
  });
  if (t.state === "failed") $("#train-msg").textContent = "Training failed: " + t.message;
  else if (t.state === "done") $("#train-msg").textContent = t.message;

  const at = m.auto_train;
  $("#auto-msg").textContent = at?.enabled ? `Auto-retrain: every night at ${String(at.hour).padStart(2, "0")}:00 when ${at.min_new}+ visits were confirmed since the active model; the new model is used only if it is not worse on those visits.` : "Auto-retrain is off.";
  $("#models tbody").innerHTML = m.models.map((x) => `<tr><td>v${x.id}${x.kind === "auto" ? " (auto)" : ""}${x.active ? " <span class='chip label'>active</span>" : ""}${x.metrics.auto ? `<br><span class="msg">${esc(x.metrics.auto.decision)}: ${esc(x.metrics.auto.reason)}</span>` : ""}</td>
      <td>${esc(new Date(x.created * 1000).toLocaleString())}</td><td class="n">${x.classes.length}</td><td class="n">${x.n_visits}</td>
      <td class="n">${pct(x.metrics.visit_accuracy)}</td><td class="n">${pct(x.metrics.baselines?.bioclip?.visit_accuracy)}</td>
      <td class="n">${pct(x.metrics.baselines?.vlm?.visit_accuracy)}</td>
      <td>${x.active ? "" : `<button class="btn" data-activate="${x.id}">Use</button>`}</td></tr>`).join("")
    || '<tr><td colspan="8" class="msg">No models yet.</td></tr>';
  $$("[data-activate]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/models/${b.dataset.activate}/activate`, { method: "POST" }); modelPage(); }));

  const latest = m.models.find((x) => x.active) || m.models[0];
  if (!latest) { $("#latest").innerHTML = ""; return; }
  const mt = latest.metrics, cls = latest.classes;
  const rows = cls.map((c) => { const p = mt.per_class?.[c] || {};
    return `<tr><td>${esc(c)}</td><td class="n">${p.visits ?? "–"}</td><td class="n">${pct(p.precision)}</td><td class="n">${pct(p.recall)}</td></tr>`; }).join("");
  const cm = mt.confusion ? `<table class="cm"><thead><tr><th>true ↓ / predicted →</th>${cls.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    mt.confusion.map((r, i) => `<tr><th>${esc(cls[i])}</th>${r.map((n, j) => `<td class="${i === j ? "diag" : n ? "off" : ""}">${n || ""}</td>`).join("")}</tr>`).join("") +
    "</tbody></table>" : "";
  const sus = (mt.suspect_labels || []).map((s) => `<li><a href="${BASE}/admin?visit=${esc(s.trace_id)}">${esc(s.trace_id.slice(-10))}</a>: you said <b>${esc(s.label)}</b>, model says <b>${esc(s.predicted)}</b> (${pct(s.confidence)})</li>`).join("");
  const few = Object.entries(mt.too_few || {}).map(([k, n]) => `${esc(k)} (${n})`).join(", ");
  $("#latest").innerHTML = `<h3>Model v${latest.id}${latest.active ? " (active)" : ""}</h3>
    <div class="cards">
      <div class="card"><div class="k">Visit accuracy (cross-validated)</div><div class="v">${pct(mt.visit_accuracy)}</div></div>
      <div class="card"><div class="k">Frame accuracy</div><div class="v">${pct(mt.frame_accuracy)}</div></div>
      <div class="card"><div class="k">BioCLIP zero-shot, same visits</div><div class="v">${pct(mt.baselines?.bioclip?.visit_accuracy)}</div></div>
      <div class="card"><div class="k">LM Studio, same visits</div><div class="v">${pct(mt.baselines?.vlm?.visit_accuracy)}</div></div>
      ${(() => { const c = (mt.calibration?.calibrated || []).find((x) => x.threshold === 0.75);
        return c ? `<div class="card"><div class="k">Decides alone at ≥75% (calibrated)</div><div class="v">${pct(c.decided)}</div>
          <div class="k">of visits, ${pct(c.accuracy)} of those right</div></div>` : ""; })()}
    </div>
    <p class="hint">${mt.cv_folds ? `${mt.cv_folds}-fold cross-validation over ${mt.visits} visits, C=${mt.C}.` : esc(mt.note || "")}
      ${few ? ` Not learned yet (need ${m.min_visits}+ visits): ${few}.` : ""}</p>
    <table><thead><tr><th>Species</th><th class="n">Visits</th><th class="n">Precision</th><th class="n">Recall</th></tr></thead><tbody>${rows}</tbody></table>
    ${cm ? `<h3>Confusion (visits)</h3>${cm}` : ""}
    ${sus ? `<h3>Labels to double-check</h3><p class="hint">Confirmed visits the model confidently disagrees with (out-of-fold). Usually a slip; sometimes the model is wrong.</p><ul>${sus}</ul>` : ""}`;
}
async function bakeoffPanel(first = false) {
  const b = await api("/api/bakeoff");
  const running = b.status.state === "running";
  if (first || !$("#bake-models").children.length) {
    $("#bake-models").innerHTML = b.models.map((m) => m.error ? `<span class="msg err">${esc(m.error)}</span>` :
      `<label><input type="checkbox" value="${esc(m.id)}" ${m.state === "loaded" ? "checked" : ""}> ${esc(m.id)}
        <span class="msg">${esc(m.quantization || "")}${m.state === "loaded" ? " · loaded now" : ""}</span></label>`).join("");
  }
  $("#bake-run").disabled = running || !b.labelled_visits;
  $("#bake-msg").textContent = running ? "Running: " + b.status.message : (b.status.message || (b.labelled_visits ? "" : "Confirm some visits first."));
  $("#bake tbody").innerHTML = b.results.map((r) => `<tr><td>${esc(r.model)}</td><td>${esc(new Date(r.run * 1000).toLocaleString())}</td>
    <td class="n">${r.visits ?? "–"}</td><td class="n">${pct(r.visit_accuracy)}</td><td class="n">${pct(r.bird_accuracy)}</td>
    <td class="n">${pct(r.json_ok)}</td><td class="n">${r.seconds_per_frame ?? "–"}</td>
    <td>${esc(r.status)}${r.error ? ": " + esc(r.error) : ""}</td></tr>`).join("") || '<tr><td colspan="8" class="msg">No comparisons yet.</td></tr>';
  if (first) $("#bake-run").addEventListener("click", async () => {
    const models = $$("#bake-models input:checked").map((i) => i.value);
    if (!models.length) { $("#bake-msg").textContent = "Tick at least one model."; return; }
    if (!confirm(`Compare ${models.length} model(s) on up to 40 confirmed visits?\n\nLM Studio will load each model in turn, which may unload the one you have loaded now.`)) return;
    try { await api("/api/bakeoff", { method: "POST", body: JSON.stringify({ models }) }); bakeoffPanel(); }
    catch (err) { $("#bake-msg").textContent = err.message; }
  });
}
if (page === "model") { modelPage(true); bakeoffPanel(true); setInterval(() => { modelPage(); bakeoffPanel(); }, 5000); }

// ---- settings page --------------------------------------------------------------
async function settingsPage() {
  const form = $("#prefs"), save = $("#prefs-save"), msg = $("#prefs-msg");
  let prefs = [];
  const show = (p) => (p.kind === "choice" ? (p.choices.find((c) => c[0] === p.default) || [, p.default])[1]
    : p.kind === "bool" ? (p.default ? "on" : "off") : `${p.default}${p.unit && p.unit !== ":00" ? " " + p.unit : p.unit}`);
  const field = (p) => {
    if (p.kind === "bool") return `<input type="checkbox" id="p-${p.key}" ${p.value ? "checked" : ""}>`;
    if (p.kind === "choice") return `<select id="p-${p.key}">${p.choices.map(([v, t]) =>
      `<option value="${esc(v)}" ${v === p.value ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    if (p.kind === "str") return `<input type="text" id="p-${p.key}" value="${esc(p.value)}" maxlength="200">`;
    const step = p.kind === "int" ? "1" : "any";
    return `<input type="number" id="p-${p.key}" value="${esc(p.value)}" step="${step}" min="${p.min ?? ""}" max="${p.max ?? ""}">`;
  };
  const read = (p) => {
    const el = $(`#p-${p.key}`);
    if (p.kind === "bool") return el.checked;
    if (p.kind === "int" || p.kind === "float") return el.value === "" ? "" : Number(el.value);
    return el.value;
  };
  const changes = () => Object.fromEntries(prefs.filter((p) => read(p) !== p.value).map((p) => [p.key, read(p)]));
  const refresh = () => {
    const n = Object.keys(changes()).length;
    save.disabled = n === 0;
    if (n) { msg.className = "msg"; msg.textContent = `${n} unsaved change${n === 1 ? "" : "s"}`; }
  };
  const draw = () => {
    const groups = [...new Set(prefs.map((p) => p.group))];
    form.innerHTML = groups.map((g) => `<fieldset class="pref-group"><legend>${esc(g)}</legend>` +
      prefs.filter((p) => p.group === g).map((p) => `<div class="pref">
        <label for="p-${p.key}">${esc(p.label)}</label>
        <div class="pref-input">${field(p)}${p.unit ? `<span class="meta">${esc(p.unit)}</span>` : ""}
          ${p.saved ? `<button type="button" class="link" data-reset="${p.key}" title="Back to the default: ${esc(show(p))}">↺ default</button>` : ""}</div>
        <p class="meta">${esc(p.help)}</p></div>`).join("") + "</fieldset>").join("");
    $$("input, select", form).forEach((el) => { el.addEventListener("input", refresh); el.addEventListener("change", refresh); });
    $$("[data-reset]", form).forEach((b) => b.addEventListener("click", () => send({ [b.dataset.reset]: null })));
    form.onsubmit = (e) => e.preventDefault();
  };
  async function send(body) {
    save.disabled = true;
    try {
      prefs = (await api("/api/settings", { method: "PUT", body: JSON.stringify(body) })).prefs;
      draw();
      msg.className = "msg";
      msg.textContent = "Saved.";
    } catch (err) {
      refresh();
      msg.className = "msg err";
      msg.textContent = err.message;
    }
  }
  save.addEventListener("click", () => send(changes()));
  window.addEventListener("beforeunload", (e) => { if (Object.keys(changes()).length) e.preventDefault(); });
  prefs = (await api("/api/settings")).prefs;
  draw();
}
