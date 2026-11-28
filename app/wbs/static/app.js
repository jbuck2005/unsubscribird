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
// Species that aren't birds: their frames are never picked by the bird detector's box.
const NOT_BIRDS = ["Squirrel", "Chipmunk", "Other animal"];
// The detector (OWL-ViT) boxed a bird in this frame: the solid yellow box on the review card.
const birdBoxed = (f) => f.det_source === "owlvit" && f.det_label === "bird";

const Review = {
  queue: "review", offset: 0, visits: [], focus: 0, species: [],

  async init() {
    this.species = await api("/api/species");
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
    for (const q of ["review", "uncertain", "disagree", "check", "flagged", "waiting", "filed", "labelled", "failed", "excluded"]) {
      const r = await api(`/api/visits?queue=${q}&limit=0`);
      $(`[data-count="${q}"]`).textContent = r.total;
    }
  },

  switchQueue(q) {
    this.queue = q;
    $(".hint").innerHTML = q === "check"
      ? "Confirmed visits the latest model doubts, most doubtful first. It checked each one <b>without having seen it</b> (cross-validation). <b>Keep</b> if your label is right, type a new species and <b>Update</b> if not, or <b>Exclude</b> a visit that shouldn't train at all."
      : q === "excluded" ? "Visits kept out of counts, eBird and training. <b>Restore</b> puts one back."
      : q === "filed" ? "Visits every signal calls Empty: nothing moved (or LM Studio saw nothing), the detector boxed nothing and the trained model agrees. They count as Empty but don't train, and their clips are deleted like confirmed Empty ones. Each morning a few of the day before come back to <b>To review</b> as training negatives. <b>Back to review</b> if one isn't empty, or <b>Confirm all</b> to make the loaded ones training data."
      : q === "disagree" ? "Visits to review where the trained model and LM Studio name different things, newest first. Each card starts on LM Studio's answer, so check the frames before you confirm. These are also in <b>To review</b>; a squirrel and a bird in one clip often lands here. <b>Confirm all</b> skips them: confirm each with Enter (or change the card first)."
      : "Correct any visits that are wrong, then <b>Confirm all</b> saves every loaded visit with its current species. Only confirmed visits become training data. Frames with a ✓ are used, and only frames where the detector boxed a bird (yellow box) start ticked; click a frame to include or exclude it, ↻ to swap a blurry frame for a sharper one from the clip, ◀ ▶ to move a frame 1 s back or forward (Shift+click: 0.2 s), <b>🎞 Pick a frame from the clip</b> to step through the clip and add the exact frame on screen, or 🏷 when a frame shows another species (a squirrel in a chickadee visit). Tick <b>Count only</b> when the bird is too hidden or blurry to learn from: it still counts, but trains nothing.";
    $$("#queues button").forEach((b) => b.classList.toggle("on", b.dataset.q === q));
    $("#queues button.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });   // phones: the chips scroll sideways
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

  // Which frames to include by default for a given species. For a bird, only the frames where the detector boxed
  // a bird (the yellow box) start ticked; LM Studio decides only when the detector found no bird in the visit
  // (detector off, frames not scanned yet, or a miss), so a visit never starts with nothing ticked.
  defaultFrames(v, species) {
    const isEmpty = species === "Empty";
    if (!isEmpty && !NOT_BIRDS.includes(species)) {
      const boxed = v.frames.filter(birdBoxed).map((f) => f.id);
      if (boxed.length) return boxed;
    }
    const byFrame = Object.fromEntries(v.suggestions.filter((s) => s.frame_id).map((s) => [s.frame_id, s]));
    const chosen = v.frames.filter((f) => {
      const s = byFrame[f.id];
      if (!s) return true;
      if (isEmpty) return !s.bird_present && !s.other_animal;
      if (NOT_BIRDS.includes(species)) return !!s.other_animal;
      return !!s.bird_present;
    }).map((f) => f.id);
    return chosen.length ? chosen : v.frames.map((f) => f.id);
  },

  // The species box starts with the best guess for an unlabelled visit: the combined guess (the model and LM Studio
  // together, as Home Assistant gets it), then LM Studio's consensus, what Home Assistant was told, the trained
  // model and BioCLIP. Only names in the species list, so Confirm all never saves free text.
  bestGuess(v) {
    const known = new Map(this.species.map((s) => [s.name.toLowerCase(), s.name]));
    const rec = v.rec_species === "Uncertain" ? v.rec_guess : v.rec_species;
    for (const name of [v.best?.species, v.consensus?.species, rec, v.model?.species, v.bioclip?.species]) {
      const hit = name && known.get(String(name).toLowerCase());
      if (hit) return hit;
    }
    return "";
  },

  card(v, i) {
    // Vicohome's own snapshot is a 640x360 thumbnail: only show it when the visit has no clip frames.
    if (v.frames.some((f) => f.kind === "clip")) v.frames = v.frames.filter((f) => f.kind === "clip");
    const el = document.createElement("section");
    el.className = "visit" + (v.label ? " done" : "");
    el.tabIndex = 0;
    el.dataset.i = i;
    const cons = v.consensus;
    const initial = v._preset?.species ?? (v.label?.species || this.bestGuess(v));
    v._species = initial;
    v._frames = v._preset?.frames ?? new Set(v.label ? v.label.frame_ids : this.defaultFrames(v, initial));
    // Mixed visits: frame id -> the species that frame shows instead of the visit's species.
    v._fs = v._preset?.fs ?? new Map(Object.entries(v.label?.frame_species || {}).map(([k, s]) => [+k, s]));
    v._edited = !!v._preset?.edited;
    // Other species seen in the visit without a frame of their own (two birds in one frame). Not training data.
    v._also = new Set(v._preset?.also ?? v.label?.also_seen ?? []);
    // Count only: the species and count go into counts and eBird, the frames never train the model.
    v._train = v._preset?.train ?? (v.label ? v.label.train !== 0 && v.label.train !== false : true);
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
          ${v.clip ? `<span class="fnav"><button class="step" data-step="-1" title="1 s earlier in the clip (Shift+click: 0.2 s)" aria-label="1 second earlier">◀</button>` +
            `<button class="regrab" title="Blurry? Grab a different frame from the clip (Shift+${n + 1})">↻</button>` +
            `<button class="step" data-step="1" title="1 s later in the clip (Shift+click: 0.2 s)" aria-label="1 second later">▶</button></span>` : ""}
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
    const from = { model: "trained model", lmstudio: "LM Studio", uncertain: "uncertain", motion: "nothing moved" };
    const bestChip = v.best && !v.label ? `<span class="chip ${v.best.source === "uncertain" ? "unknown" : "sugg"}"
        title="The model and LM Studio combined, as Home Assistant gets it">Best guess: ${esc(v.best.species)} · ${esc(from[v.best.source] || v.best.source)}${v.best.confidence != null ? " " + Math.round(v.best.confidence * 100) + "%" : ""}</span>` : "";
    // The lead guess, then the rest. On a phone the rest folds behind a "+N" button (style.css) and the
    // predictions sit under the frames, so the picture comes first.
    const lead = bestChip || consChip;
    const rest = (bestChip ? consChip : "") + altChips;
    const nRest = (rest.match(/<span class="chip /g) || []).length;
    const preds = lead || rest ? `<div class="preds">${lead}<span class="more">${rest}</span>${lead && nRest
      ? `<button type="button" class="chip morebtn" aria-expanded="false" title="Show the other guesses">+${nRest}</button>` : ""}</div>` : "";
    el.innerHTML = `
      <div class="vhead"><span class="time">${esc(fmtTime(v.time))}</span>
        ${v.disagree && !v.label ? `<span class="chip unknown" title="The trained model and LM Studio name different things: look before confirming">⚠ disagree</span>` : ""}
        ${v.flagged ? `<span class="chip unknown" title="Someone pressed Wrong bird? on the home page. Saving a label answers it.">⚑ flagged${v.flag_note ? `: “${esc(v.flag_note)}”` : ""}</span>` : ""}
        ${v.quiet ? '<span class="chip alt" title="The frame picker saw no movement in the clip, so LM Studio was skipped">nothing moved</span>' : ""}
        ${v.triage === "sample" && !v.label ? '<span class="chip alt" title="A filed Empty visit picked back for review as a training negative, from a time of day with few confirmed Empty visits">Empty sample</span>' : ""}
        ${v.triage === "filed" && !v.label ? '<span class="chip alt" title="Every signal called this visit Empty, so it skipped To review">filed Empty</span>' : ""}
        ${v.error ? `<span class="meta err">${esc(v.error)}</span>` : ""}
        ${v.label ? `<span class="chip label">✓ ${esc(v.label.species)}${(v.label.also || []).length ? " + " + esc(v.label.also.join(", ")) : ""}</span>` : ""}
        <span class="chip alt countonly-chip" title="Counted, but its frames are not training data" ${v.label && !v._train ? "" : "hidden"}>count only</span>
        <span class="chip edited" ${v._edited ? "" : "hidden"}>✎ changed</span>
        ${v.clip_href ? `<a class="meta clip" href="${BASE}${esc(v.clip_href)}" target="_blank" title="Play the clip (Save as keeps this name)">▶ ${esc(v.clip_name)}</a>` : ""}</div>
      ${preds}
      <div class="frames">${frames || '<span class="msg">No frames yet.</span>'}</div>
      ${v.clip && v.clip_href ? `<div class="picker">
        <button type="button" class="btn pickopen" aria-expanded="false" title="Play the clip here and pick the exact moment to use as a frame">🎞 Pick a frame from the clip</button>
        <div class="player" hidden>
          <video controls playsinline muted preload="none"></video>
          <div class="pbtns">
            <button type="button" class="btn" data-d="-1" title="Back 1 s">−1 s</button>
            <button type="button" class="btn" data-d="-0.1" title="Back about one frame">−0.1</button>
            <span class="ptime" aria-live="polite">0.00 s</span>
            <button type="button" class="btn" data-d="0.1" title="Forward about one frame">+0.1</button>
            <button type="button" class="btn" data-d="1" title="Forward 1 s">+1 s</button>
            <button type="button" class="btn primary pickthis" title="Add the frame shown in the player to this visit, ticked">Select this frame</button>
          </div></div></div>` : ""}
      <div class="actions">
        <input placeholder="Species…" value="${esc(initial)}" aria-label="Species">
        <span class="alsoseen" title="Another species in the visit with no frame of its own, e.g. two birds in one frame. Not used for training.">
          <span class="also-chips"></span><input class="alsoin" placeholder="+ Also seen…" aria-label="Also seen"></span>
        <input class="countin" type="number" min="1" max="99" placeholder="How many?" value="${esc(v._preset?.count ?? v.label?.count ?? "")}" aria-label="How many at once"
          title="The most birds of this species at once, for a FeederWatch count. Leave empty for one, or LM Studio's count.">
        <label class="countonly" title="Count this visit (species, how many, eBird) but keep its frames out of training, e.g. a bird hidden behind the feeder or a blurry clip (o)">
          <input type="checkbox" ${v._train ? "" : "checked"}> Count only</label>
        <button class="btn primary" data-a="confirm">${v.label ? "Update" : "Confirm"} ⏎</button>
        <button class="btn" data-a="Empty" title="Set to Empty (confirm later)">Empty (e)</button>
        <button class="btn" data-a="Squirrel">Squirrel (s)</button>
        <button class="btn" data-a="Unknown bird">Unknown bird (u)</button>
        ${v.label ? '<button class="btn" data-a="unlabel">Remove label</button>' : ""}
        ${v.triage === "filed" && !v.label ? '<button class="btn" data-a="unfile" title="Not empty, or worth a look: put it in To review">Back to review</button>' : ""}
        ${v.label && v.check ? '<button class="btn" data-a="keep" title="Your label is right (c)">Keep ✓ (c)</button>' : ""}
        <button class="btn" data-a="${v.excluded ? "restore" : "exclude"}" title="${v.excluded ? "Use this visit again" : "Not a real visit: keep it out of counts, eBird and training"}">${v.excluded ? "Restore" : "Exclude"}</button>
        <span class="msg"></span>
      </div>`;
    $(".morebtn", el)?.addEventListener("click", (e) => {
      const b = e.currentTarget, open = b.closest(".preds").classList.toggle("open");
      b.setAttribute("aria-expanded", open);
    });
    $$(".frame .regrab", el).forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation(); this.regrab(v, el, +b.closest(".frame").dataset.f);
    }));
    $$(".frame .step", el).forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      this.regrab(v, el, +b.closest(".frame").dataset.f, { step: +b.dataset.step * (e.shiftKey ? 0.2 : 1) });
    }));
    this.bindPicker(v, el);
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
    // Attached first: on Enter it puts the highlighted name in the field before the handler below saves it.
    Autocomplete.attach(input, { species: () => this.species, pick: (name) => this.pickSpecies(v, el, name),
      hints: () => [v.flag_note, v.consensus?.species, v.model?.species, v.bioclip?.species, v.rec_species] });   // a kid's "Wrong bird?" pick first
    input.addEventListener("change", () => this.pickSpecies(v, el, input.value));
    input.addEventListener("input", () => { v._species = input.value; this.markEdited(v, el); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); this.pickSpecies(v, el, input.value); this.save(v, el); } });
    const alsoIn = $(".alsoin", el);
    Autocomplete.attach(alsoIn, { species: () => this.species,
      hints: () => [v.model?.species, v.bioclip?.species, ...v.suggestions.map((s) => s.species)],
      pick: (name) => { alsoIn.value = ""; if (!v._also.has(name)) { v._also.add(name); this.renderAlso(v, el); this.markEdited(v, el); } } });
    $(".also-chips", el).addEventListener("click", (e) => {
      const b = e.target.closest("button[data-s]");
      if (b) { v._also.delete(b.dataset.s); this.renderAlso(v, el); this.markEdited(v, el); }
    });
    this.renderAlso(v, el);
    el.classList.toggle("notrain", !v._train);
    $(".countonly input", el).addEventListener("change", (e) => this.setTrain(v, el, !e.target.checked));
    $$("button[data-a]", el).forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.a;
      if (a === "confirm") this.save(v, el);
      else if (a === "unlabel") this.unlabel(v, el);
      else if (a === "keep") this.keep(v, el);
      else if (a === "unfile") this.unfile(v, el);
      else if (a === "exclude" || a === "restore") this.exclude(v, el, a === "exclude");
      else { this.pickSpecies(v, el, a); }
    }));
    el.addEventListener("focus", () => this.setFocus(i, false));
    return el;
  },

  // After a save: the clip is named after the new species.
  setClip(v, el, res) {
    const a = $("a.clip", el);
    if (!a || !res.clip_href) return;
    v.clip_href = res.clip_href; v.clip_name = res.clip_name;
    a.href = BASE + res.clip_href; a.textContent = `▶ ${res.clip_name}`;
  },

  setTrain(v, el, on) {
    v._train = on;
    $(".countonly input", el).checked = !on;
    el.classList.toggle("notrain", !on);
    const m = $(".msg", el);
    m.className = "msg";
    m.textContent = on ? "Ticked frames will be training data." : "Count only: the species and count are kept, the frames won't train the model.";
    this.markEdited(v, el);
  },

  renderAlso(v, el) {
    $(".also-chips", el).innerHTML = [...v._also].map((s) =>
      `<button type="button" class="chip also" data-s="${esc(s)}" title="Remove ${esc(s)}">+ ${esc(s)} ×</button>`).join("");
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
    inp.className = "ftagin"; inp.setAttribute("aria-label", `Species in frame ${v.frames.findIndex((f) => f.id === fid) + 1}`);
    inp.placeholder = "This frame shows…"; inp.value = v._fs.get(fid) || "";
    $(".imgwrap", fe).append(inp);
    // Kept on Enter, on picking from the list, and on clicking away (e.g. straight to Update): only Esc cancels.
    let closed = false;
    Autocomplete.attach(inp, { species: () => this.species, pick: () => done(true, document.activeElement === inp),
      hints: () => [v.consensus?.species, ...v.suggestions.filter((s) => s.frame_id === fid).map((s) => s.species || s.other_animal)] });
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

  // The clip player under the frames: step through it, then "Select this frame" adds the frame on screen, ticked.
  bindPicker(v, el) {
    const box = $(".picker", el);
    if (!box) return;
    const player = $(".player", box), vid = $("video", box), open = $(".pickopen", box), shown = $(".ptime", box);
    // The time of the frame actually on screen. currentTime can sit between two frames; where the browser
    // reports the presented frame (requestVideoFrameCallback), use that, so the server cuts the same picture.
    let onScreen = null;
    const watch = () => vid.requestVideoFrameCallback((now, meta) => { onScreen = meta.mediaTime; show(); watch(); });
    const at = () => (onScreen != null && Math.abs(onScreen - vid.currentTime) < 0.25 ? onScreen : vid.currentTime);
    const show = () => { shown.textContent = (Math.floor(at() * 100 + 1e-6) / 100).toFixed(2) + " s"; };   // as the server rounds
    open.addEventListener("click", () => {
      player.hidden = !player.hidden;
      open.setAttribute("aria-expanded", !player.hidden);
      if (!player.hidden && !vid.src) {
        vid.src = BASE + v.clip_href; vid.load();
        if (vid.requestVideoFrameCallback) watch();
      }
      if (player.hidden) vid.pause();
    });
    vid.addEventListener("timeupdate", show);
    vid.addEventListener("seeked", show);
    $$("[data-d]", box).forEach((b) => b.addEventListener("click", () => {
      vid.pause();
      const end = isFinite(vid.duration) ? vid.duration : Infinity;
      vid.currentTime = Math.min(Math.max(0, at() + +b.dataset.d), end);
    }));
    $(".pickthis", box).addEventListener("click", () => { vid.pause(); this.pickFrame(v, el, at()); });
  },

  async pickFrame(v, el, t) {
    const msg = $(".msg", el);
    msg.className = "msg"; msg.textContent = `Adding the frame at ${t.toFixed(2)}s…`;
    try {
      const r = await api(`/api/visits/${v.trace_id}/frames`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ t: Math.round(t * 1000) / 1000 }) });
      const nv = await api(`/api/visits/${v.trace_id}`);
      const frames = new Set(v._frames); frames.add(r.frame.id);
      nv._preset = { species: $(".actions input", el).value, frames, fs: new Map(v._fs), also: v._also,
        count: $(".countin", el)?.value, edited: v._edited || !!v.label, train: v._train };
      const ne = this.rerender(v, nv, el);
      const s = r.suggestion;
      $(".msg", ne).textContent = `Added the frame at ${r.frame.t}s, ticked` +
        (s ? ` (model: ${s.bird_present ? (s.species || "bird") : (s.other_animal || "no bird")})` : "") +
        (v.label ? ". Press Update to save it." : ".");
    } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
  },

  rerender(v, nv, el) {
    const i = this.visits.indexOf(v);
    this.visits[i] = nv;
    const ne = this.card(nv, i);
    el.replaceWith(ne);
    if (nv._preset.edited) this.markEdited(nv, ne);
    this.setFocus(i, false);
    return ne;
  },

  async regrab(v, el, fid, body = null) {
    const fe = $(`.frame[data-f="${fid}"]`, el);
    const msg = $(".msg", el);
    fe.classList.add("busy"); msg.className = "msg";
    msg.textContent = body?.step ? `Stepping ${body.step < 0 ? "back" : "forward"} ${Math.abs(body.step)} s…` : "Grabbing a different frame…";
    try {
      const r = await api(`/api/frames/${fid}/replace`, body ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) } : { method: "POST" });
      const nv = await api(`/api/visits/${v.trace_id}`);
      const frames = new Set([...v._frames].filter((x) => x !== fid));
      if (v._frames.has(fid) || !frames.size) frames.add(r.frame.id);
      const fs = new Map(v._fs);
      if (fs.has(fid)) { fs.set(r.frame.id, fs.get(fid)); fs.delete(fid); }
      nv._preset = { species: $(".actions input", el).value, frames, fs, also: v._also, count: $(".countin", el)?.value, edited: v._edited, train: v._train };
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
      if (!species || !known.has(species.toLowerCase()) || (v._train && !v._frames.size)) { skipped.push(el); continue; }
      items.push({ trace_id: v.trace_id, species, frame_ids: [...v._frames], frame_species: this.frameSpecies(v),
                   also_seen: [...v._also], count: this.count(el), train: v._train, _v: v, _el: el });
    }
    const unsaved = this.unsaved().map(({ el }) => el);
    const mark = (els, text) => els.forEach((el) => { el.classList.add("skipped"); const m = $(".msg", el); m.className = "msg err"; m.textContent = text; });
    mark(skipped, "Skipped by Confirm all: pick a species from the list (and at least one frame, or tick Count only).");
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
    const countOnly = items.filter((it) => !it.train).length;
    if (!confirm(`Confirm ${items.length} visit(s)?\n\n${summary}\n\n${edited} changed by you.` +
                 (countOnly ? ` ${countOnly} count only (not training data).` : "") +
                 (notes.length ? "\n\n" + notes.join("\n") : ""))) return;
    const btn = $("#confirm-all"); btn.disabled = true; btn.textContent = "Saving…";
    try {
      const r = await api("/api/labels/batch", { method: "POST",
        body: JSON.stringify(items.map(({ trace_id, species, frame_ids, frame_species, also_seen, count, train }) =>
          ({ trace_id, species, frame_ids, frame_species, also_seen, count, train }))) });
      r.results.forEach((res, n) => {
        const { _v: v, _el: el } = items[n];
        const m = $(".msg", el);
        if (res.ok) { v.label = { count: items[n].count, species: res.species, frame_ids: items[n].frame_ids, frame_species: res.frame_species, also: res.also,
                                  also_seen: res.also_seen, train: res.train };
          this.setClip(v, el, res); el.classList.add("done"); this.showTrain(v, el);
          v._edited = false; const badge = $(".chip.edited", el); if (badge) badge.hidden = true;
          m.className = "msg"; m.textContent = `Saved: ${res.species} (${res.source}${res.train ? "" : ", count only"}).`; }
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

  count(el) { const n = parseInt($(".countin", el)?.value, 10); return n >= 1 ? Math.min(n, 99) : null; },

  async save(v, el) {
    const msg = $(".msg", el);
    const species = ($(".actions input", el).value || "").trim();
    if (!species) { msg.className = "msg err"; msg.textContent = "Type or pick a species first."; return; }
    try {
      const r = await api(`/api/visits/${v.trace_id}/label`, { method: "POST",
        body: JSON.stringify({ species, frame_ids: [...v._frames], frame_species: this.frameSpecies(v), also_seen: [...v._also],
                               count: this.count(el), train: v._train }) });
      v.label = { count: this.count(el), species: r.species, frame_ids: [...v._frames], frame_species: r.frame_species, also: r.also, also_seen: r.also_seen, train: r.train };
      this.setClip(v, el, r); this.showTrain(v, el);
      v._edited = false; const badge = $(".chip.edited", el); if (badge) badge.hidden = true;
      el.classList.add("done"); el.classList.remove("skipped");
      msg.className = "msg"; msg.textContent = `Saved: ${r.species}${r.also.length ? " + " + r.also.join(", ") : ""} (${r.source}${r.train ? "" : ", count only: not training data"}).`;
      this.counts(); this.updateConfirmAll();
      this.setFocus(this.focus + 1);
    } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
  },

  // After a save: the header says whether the label is count only.
  showTrain(v, el) {
    const c = $(".countonly-chip", el);
    if (c) c.hidden = !v.label || v.label.train !== false;
  },

  async keep(v, el) {
    try {
      await api(`/api/visits/${v.trace_id}/keep`, { method: "POST" });
      el.classList.add("done"); $(".msg", el).className = "msg"; $(".msg", el).textContent = "Kept: label is right.";
      this.counts(); this.setFocus(this.focus + 1);
    } catch (err) { $(".msg", el).className = "msg err"; $(".msg", el).textContent = err.message; }
  },

  async unfile(v, el) {
    try {
      await api(`/api/visits/${v.trace_id}/unfile`, { method: "POST" });
      v.triage = "kept"; $('button[data-a="unfile"]', el)?.remove();
      el.classList.add("done"); $(".msg", el).className = "msg"; $(".msg", el).textContent = "Back in To review.";
      this.counts(); this.setFocus(this.focus + 1);
    } catch (err) { $(".msg", el).className = "msg err"; $(".msg", el).textContent = err.message; }
  },

  async exclude(v, el, on) {
    try {
      await api(`/api/visits/${v.trace_id}/exclude`, { method: "POST", body: JSON.stringify({ excluded: on }) });
      v.excluded = on ? 1 : 0;
      el.classList.add("done"); $(".msg", el).className = "msg";
      $(".msg", el).textContent = on ? "Excluded from counts and training." : "Restored.";
      const b = $(`button[data-a="${on ? "exclude" : "restore"}"]`, el);
      if (b) { b.dataset.a = on ? "restore" : "exclude"; b.textContent = on ? "Restore" : "Exclude"; }
      this.counts(); this.updateConfirmAll(); this.setFocus(this.focus + 1);
    } catch (err) { $(".msg", el).className = "msg err"; $(".msg", el).textContent = err.message; }
  },

  async unlabel(v, el) {
    await api(`/api/visits/${v.trace_id}/label`, { method: "DELETE" });
    v.label = null; el.classList.remove("done"); this.showTrain(v, el); $(".msg", el).textContent = "Label removed."; this.counts(); this.updateConfirmAll();
  },

  setFocus(i, scroll = true) {
    const cards = $$(".visit");
    if (!cards.length) return;
    this.focus = Math.max(0, Math.min(i, cards.length - 1));
    cards.forEach((c, n) => c.classList.toggle("focus", n === this.focus));
    if (scroll) { cards[this.focus].scrollIntoView({ block: "center", behavior: "smooth" }); cards[this.focus].focus({ preventScroll: true }); }
  },

  key(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "VIDEO" || e.ctrlKey || e.metaKey || !lightbox.hidden) return;
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
    else if (k === "o") { this.setTrain(v, el, !v._train); }
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
    try { const v = JSON.parse(localStorage.getItem("unsub.datasetSort")); if (v && v.key && !["kind", "family_name"].includes(v.key)) return v; } catch (e) { /* no storage */ }
    return { key: "name", dir: "asc" };
  },
  click(key) {
    const cur = this.get();
    const next = cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" }
                                 : { key, dir: NUMERIC_COLS.has(key) ? "desc" : "asc" };
    try { localStorage.setItem("unsub.datasetSort", JSON.stringify(next)); } catch (e) { /* no storage */ }
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
    ...(stats.count_only_visits ? [["Count only", stats.count_only_visits]] : []),
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
async function refetchStatus() {
  const r = await api("/api/clips/refetch");
  const res = r.result || {};
  $("#refetch-go").disabled = r.running;
  $("#refetch-msg").textContent = r.running ? `Checking the last ${r.hours} h…`
    : res.error ? `Failed: ${res.error}`
    : r.finished ? `Last ${r.hours} h: ${res.checked} checked, ${res.grew} fetched again (longer), ${res.same} unchanged` +
      `${res.gone ? `, ${res.gone} no longer in Home Assistant` : ""}${res.errors ? `, ${res.errors} failed (see the log)` : ""}.` : "";
  return r.running;
}
function refetchInit() {
  refetchStatus();
  $("#refetch-go").addEventListener("click", async () => {
    try { await api("/api/clips/refetch", { method: "POST", body: JSON.stringify({ hours: +$("#refetch-hours").value }) }); }
    catch (err) { $("#refetch-msg").textContent = err.message; return; }
    const tick = async () => { if (await refetchStatus()) setTimeout(tick, 2000); };
    tick();
  });
}
async function statusPage() {
  const s = await api("/api/stats");
  const v = s.visits;
  $("#status").innerHTML = [
    ["Visits", Object.values(v).reduce((a, b) => a + b, 0)],
    ["To review", v.prelabelled || 0], ["Waiting for frames/model", (v.new || 0) + (v.frames || 0)], ["Failed", v.failed || 0],
    ["MQTT", s.collector.mqtt, true], ["Clips fetched", s.collector.clips],
    ["LM Studio", s.prelabel.lmstudio, true], ["Seconds per frame", s.prelabel.seconds_per_frame ?? "–"],
    ["Empty visits filed", s.triage.on ? `${s.triage.filed} (${s.triage.per_day} a day back to review)` : "off", true],
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

// ---- header menu (phones; style.css hides the button on wider screens) ----------
{
  const header = $("body > header"), btn = header && $(".navtoggle", header);
  if (btn) {
    const setOpen = (open) => { header.classList.toggle("open", open); btn.setAttribute("aria-expanded", open); };
    btn.addEventListener("click", () => setOpen(!header.classList.contains("open")));
    document.addEventListener("click", (e) => { if (!header.contains(e.target)) setOpen(false); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && header.classList.contains("open")) { setOpen(false); btn.focus(); }
    });
  }
  // Phones: the queue hint is cut to two lines; a tap shows all of it.
  $(".qhint")?.addEventListener("click", (e) => { if (!e.target.closest("a")) e.currentTarget.classList.toggle("open"); });
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
      <td>${x.active ? "" : `<button class="btn" data-activate="${x.id}">Use</button> <button class="btn" data-del="${x.id}">Delete</button>`}</td></tr>`).join("")
    || '<tr><td colspan="8" class="msg">No models yet.</td></tr>';
  $$("[data-activate]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/models/${b.dataset.activate}/activate`, { method: "POST" }); modelPage(); }));
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Delete model v${b.dataset.del}? Its file is removed and this can't be undone.`)) return;
    try { await api(`/api/models/${b.dataset.del}`, { method: "DELETE" }); modelPage(); }
    catch (e) { alert(e.message); }
  }));

  const latest = m.models.find((x) => x.active) || m.models[0];
  if (!latest) { $("#latest").innerHTML = ""; return; }
  const mt = latest.metrics, cls = latest.classes;
  const rows = cls.map((c) => { const p = mt.per_class?.[c] || {};
    return `<tr><td>${esc(c)}</td><td class="n">${p.visits ?? "–"}</td><td class="n">${pct(p.precision)}</td><td class="n">${pct(p.recall)}</td></tr>`; }).join("");
  const cm = mt.confusion ? `<table class="cm"><thead><tr><th>true ↓ / predicted →</th>${cls.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    mt.confusion.map((r, i) => `<tr><th>${esc(cls[i])}</th>${r.map((n, j) => `<td class="${i === j ? "diag" : n ? "off" : ""}">${
      i !== j && n && mt.mistakes ? `<button class="cm-cell" data-true="${esc(cls[i])}" data-pred="${esc(cls[j])}" title="Show these visits">${n}</button>` : n || ""}</td>`).join("")}</tr>`).join("") +
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
    ${cm ? `<h3>Confusion (visits)</h3>${cm}<p class="hint">${mt.mistakes ? "Click a red number to see those visits and what the model made of each frame."
      : "Train a new model to see the visits behind each red number."}</p><div id="cm-why"></div>` : ""}
    ${sus ? `<h3>Labels to double-check</h3><p class="hint">Confirmed visits the model confidently disagrees with (out-of-fold). Usually a slip; sometimes the model is wrong.</p><ul>${sus}</ul>` : ""}`;
  const cell = (b) => `${latest.id}|${b.dataset.true}|${b.dataset.pred}`;
  $$(".cm-cell").forEach((b) => {
    if (cmPick?.key === cell(b)) { b.classList.add("on"); $("#cm-why").innerHTML = cmPick.html; }   // survive the 5 s refresh
    b.addEventListener("click", () => {
      $$(".cm-cell").forEach((x) => x.classList.toggle("on", x === b));
      confusionWhy(cell(b), mt.mistakes.filter((m) => m.label === b.dataset.true && m.predicted === b.dataset.pred));
    });
  });
}
let cmPick = null;   // the confusion cell open on the Model page, and what it shows
// Why the model got these visits wrong: each frame it saw, with its out-of-fold guess for that frame.
async function confusionWhy(key, list) {
  cmPick = { key, html: '<p class="msg">Loading…</p>' };
  $("#cm-why").innerHTML = cmPick.html;
  const visits = await Promise.all(list.map((m) => api(`/api/visits/${encodeURIComponent(m.trace_id)}`).catch(() => null)));
  if (cmPick.key !== key) return;   // another cell was picked meanwhile
  cmPick.html = list.map((m, k) => {
    const v = visits[k], byId = Object.fromEntries((v?.frames || []).map((f) => [f.id, f]));
    const wrong = m.frames.filter((f) => f.predicted !== f.label).length;
    const notes = [];
    if (!v) notes.push("This visit is gone (deleted or cleaned up).");
    else if (v.label?.species !== m.label) notes.push(`Since relabelled as <b>${esc(v.label?.species || "unlabelled")}</b>: a retrain will count it right.`);
    if ((v?.label?.also_seen || []).length) notes.push(`Also seen: ${esc(v.label.also_seen.join(", "))}.`);
    if (m.frames.length && wrong === m.frames.length) notes.push("The model disagreed on every frame: check the label.");
    else if (wrong) notes.push(`The model got ${wrong} of ${m.frames.length} frames wrong (red), and they decided the visit.`);
    return `<div class="why"><p>You said <b>${esc(m.label)}</b>, the model said <b>${esc(m.predicted)}</b> (${pct(m.confidence)};
        ${esc(m.label)} ${pct(m.label_prob)}). <a href="${BASE}/admin?visit=${encodeURIComponent(m.trace_id)}">Open visit</a></p>
      ${notes.length ? `<p class="hint">${notes.join(" ")}</p>` : ""}
      <div class="why-frames">${m.frames.map((f) => { const fr = byId[f.id];
        return `<figure class="${f.predicted === f.label ? "" : "bad"}">${fr ? `<img loading="lazy" src="${BASE}/img/${esc(fr.thumb || fr.path)}" alt="">` : '<div class="gone">no image</div>'}
          <figcaption>${esc(f.predicted)} ${pct(f.confidence)}${f.label !== m.label ? `<br><span class="msg">frame: ${esc(f.label)}</span>` : ""}</figcaption></figure>`; }).join("")}</div></div>`;
  }).join("") || '<p class="msg">No visits.</p>';
  if ($("#cm-why")) $("#cm-why").innerHTML = cmPick.html;
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

// ---- Patterns page ----------------------------------------------------------------
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
async function feederWatch() {
  const start = $("#fw-start").value;
  const r = await api(`/api/feederwatch?start=${start}`);
  const day = (d) => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const from = { you: "your count", "LM Studio": "LM Studio's count", "one bird": "one bird (no count)" };
  const eff = r.effort.map((e) => `<li><b>${esc(day(e.day))}</b>: ${e.bird_visits} bird visits${e.first ? `, ${esc(e.first)} to ${esc(e.last)}
    (${e.am} morning, ${e.pm} afternoon)` : ""}</li>`).join("");
  $("#fw-out").innerHTML = r.species.length ? `<table><thead><tr><th>Species</th><th class="n">Most at once</th>
      ${r.days.map((d) => `<th class="n">${esc(day(d))}</th>`).join("")}<th class="n">Visits</th><th>Count from</th></tr></thead><tbody>
      ${r.species.map((s) => `<tr><td>${esc(s.species)}</td><td class="n"><b>${s.max}</b></td>
        ${r.days.map((d) => `<td class="n">${s.days[d] || "–"}</td>`).join("")}<td class="n">${s.visits}</td>
        <td><a href="${BASE}/admin?visit=${encodeURIComponent(s.trace_id)}">${esc(from[s.source] || s.source)}</a></td></tr>`).join("")}
      </tbody></table><p class="hint">Effort: the camera watches all day, so pick FeederWatch's longest watching time for each
      half-day it ran. When it saw birds:</p><ul>${eff}</ul>`
    : '<p class="msg">No birds on those days.</p>';
}
// A heat table: rows are species, columns are hours or weeks; one hue, darker = more (5 steps of the max).
function heatTable(rows, counts, cols, label, title) {
  const max = Math.max(1, ...rows.flatMap((r) => counts[r]));
  const step = (n) => n ? Math.min(5, Math.ceil(5 * n / max)) : 0;
  return `<table class="heat"><thead><tr><th></th>${cols.map((c) => `<th><span>${esc(label(c))}</span></th>`).join("")}<th class="n">All</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><th>${esc(r)}</th>${cols.map((c) => { const n = counts[r][c.i];
      return `<td class="h${step(n)}" title="${esc(title(r, c, n))}"><span class="sr">${n}</span></td>`; }).join("")}
      <td class="n">${counts[r].reduce((a, b) => a + b, 0)}</td></tr>`).join("")}</tbody></table>
    <p class="heat-key" aria-hidden="true">Fewer <span class="h1"></span><span class="h2"></span><span class="h3"></span><span class="h4"></span><span class="h5"></span> More
      (strongest = ${max} visits)</p>`;
}
const hourName = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
const visitsWord = (n) => `${n} visit${n === 1 ? "" : "s"}`;
async function patterns(days) {
  const r = await api(`/api/patterns?days=${days}`);
  const f = r.feeder;
  $("#feeder").innerHTML = !f.enabled ? '<p class="msg">Feeder check is off (Settings, Patterns).</p>'
    : f.quiet ? `<p class="feeder-alert"><b>⚠ Feeder quiet:</b> no birds in the last ${f.hours} h, when these hours usually bring
        about ${f.expected}. Maybe it needs filling. Home Assistant's <b>Feeder quiet</b> sensor is on.</p>`
    : `<p class="msg">✓ Feeder busy as usual: ${visitsWord(f.recent)} in the last ${f.hours} h (usually about ${f.expected}).</p>`;
  const h = r.hours, used = h.species.flatMap((sp) => h.counts[sp].map((n, i) => n ? i : -1)).filter((i) => i >= 0);
  const lo = Math.max(0, Math.min(...used) - 1), hi = Math.min(23, Math.max(...used) + 1);
  const hours = used.length ? Array.from({ length: hi - lo + 1 }, (_, k) => ({ i: lo + k })) : [];
  $("#pat-hours").innerHTML = h.species.length ? heatTable(h.species, h.counts, hours,
    (c) => c.i % 3 === 0 ? hourName(c.i) : "", (sp, c, n) => `${sp}, ${hourName(c.i)} to ${hourName((c.i + 1) % 24)}: ${visitsWord(n)}`)
    : '<p class="msg">No visits in this period.</p>';
  const w = r.weeks, wk = (d) => new Date(d + "T12:00:00");
  $("#pat-weeks").innerHTML = w.species.length ? heatTable(w.species, w.counts, w.weeks.map((d, i) => ({ i, d })),
    // A month's name over its first week (and over the first column, unless the next month starts right after).
    (c) => (c.i === 0 ? wk(w.weeks[Math.min(2, w.weeks.length - 1)]).getMonth() === wk(c.d).getMonth()
      : wk(c.d).getMonth() !== wk(w.weeks[c.i - 1]).getMonth()) ? wk(c.d).toLocaleDateString(undefined, { month: "short" }) : "",
    (sp, c, n) => `${sp}, week of ${wk(c.d).toLocaleDateString(undefined, { month: "short", day: "numeric" })}: ${visitsWord(n)}`)
    : '<p class="msg">No visits yet.</p>';
  const t = r.temperature, ts = r.temp_sensor;
  if (!t) {
    $("#pat-temp").innerHTML = `<p class="msg">${!ts.entity ? "Name a Home Assistant temperature sensor on the Settings page (Patterns) to see this."
      : !ts.token ? "The temperature sensor needs a Home Assistant token: set UNSUB_HA_TOKEN (Docker)."
      : ts.error ? `Can't read ${esc(ts.entity)}: ${esc(ts.error)}` : `Collecting ${esc(ts.entity)} every 10 minutes; check back in a day or two.`}</p>`;
    return;
  }
  // A band is drawn once it has an hour of readings at busy times; until then it says so, so the page never sits blank.
  const ready = t.bands.filter((b) => b.per_hour !== null), top = Math.max(0.01, ...ready.map((b) => b.per_hour));
  const busy = t.busy_hours.length ? `${hourName(t.busy_hours[0])} to ${hourName((t.busy_hours.at(-1) + 1) % 24)}` : "none yet";
  const when = new Date(t.latest.ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("#pat-temp").innerHTML = `<p class="hint">Bird visits per hour at each outdoor temperature, counting only the hours birds usually
      come (${esc(busy)}), so cold nights don't count. ${t.samples} reading${t.samples === 1 ? "" : "s"} from ${esc(ts.entity)} so far;
      the latest is ${esc(t.latest.temp)} ${esc(t.unit)} at ${esc(when)}.${ready.length ? "" : " Each temperature gets its bar once it has an hour of readings."}</p>
    <table class="bars"><tbody>${t.bands.map((b) => `<tr><th>${b.from} to ${b.to} ${esc(t.unit)}</th>
      ${b.per_hour === null ? `<td><span class="msg">collecting…</span></td><td class="n msg">${b.hours} of 1 h</td>`
        : `<td><span class="bar" style="width:${(100 * b.per_hour / top).toFixed(1)}%"></span></td>
      <td class="n">${b.per_hour} / h <span class="msg">(${b.visits} in ${b.hours} h)</span></td>`}</tr>`).join("")}</tbody></table>`;
}
async function eBird() {
  const r = await api(`/api/ebird?start=${$("#eb-start").value}&end=${$("#eb-end").value}`);
  const day = (d) => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  $("#eb-out").innerHTML = r.checklists.length ? `<p class="hint">${r.checklists.length} checklist${r.checklists.length === 1 ? "" : "s"}
      at <b>${esc(r.location)}</b> (${esc(r.region)}), ${esc(r.protocol)}.</p>
    <table><thead><tr><th>Day</th><th>Start</th><th class="n">Minutes</th><th>Birds (most at once)</th></tr></thead><tbody>
    ${r.checklists.map((c) => `<tr><td>${esc(day(c.day))}</td><td>${esc(c.start)}</td><td class="n">${c.minutes}</td>
      <td>${c.species.map((s) => `${esc(s.species)} <b>${esc(s.number)}</b>`).join(", ")}</td></tr>`).join("")}</tbody></table>`
    : '<p class="msg">No birds on those days.</p>';
}
function patternsPage() {
  const y = new Date(); y.setDate(y.getDate() - 1);
  $("#fw-start").value = isoDay(y);
  $("#fw-start").max = isoDay(y);
  $("#fw-start").addEventListener("change", feederWatch);
  $("#eb-start").value = $("#eb-end").value = isoDay(y);
  $("#eb-start").max = $("#eb-end").max = isoDay(new Date());
  $("#eb-start").addEventListener("change", () => { if ($("#eb-end").value < $("#eb-start").value) $("#eb-end").value = $("#eb-start").value; eBird(); });
  $("#eb-end").addEventListener("change", eBird);
  $("#eb-csv").addEventListener("click", () => {
    location.href = `${BASE}/api/ebird?start=${$("#eb-start").value}&end=${$("#eb-end").value}&format=csv`; });
  eBird();
  const days = () => +$(".pat-range .on").dataset.days;
  $$(".pat-range [data-days]").forEach((b) => b.addEventListener("click", () => {
    $$(".pat-range [data-days]").forEach((x) => x.classList.toggle("on", x === b)); patterns(days()); }));
  patterns(days());
  $("#fw-csv").addEventListener("click", () => { location.href = `${BASE}/api/feederwatch?start=${$("#fw-start").value}&format=csv`; });
  feederWatch();
}
if (page === "patterns") patternsPage();
if (page === "status") refetchInit();
