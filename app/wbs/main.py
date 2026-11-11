"""Web UI + API, and the background collector / pre-labeller."""

from __future__ import annotations

import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import re
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from . import frames as framelib
from .collector import Collector
from .config import settings
from .db import DB
from .auth import COOKIE, MAX_AGE, Auth
from .bakeoff import Bakeoff
from .detect import Detector
from .embed import EmbedWorker, Embedder
from .prefs import Prefs
from .prelabel import Prelabeler, consensus
from .recognition import Recognizer
from .retention import Retention
from .train import Trainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("wbs")
HERE = Path(__file__).parent

db = DB(settings.db_path)
prefs = Prefs(settings, db)
collector = Collector(settings, db)
prelabeler = Prelabeler(settings, db)
embedder = Embedder(threads=settings.embed_threads)
embed_worker = EmbedWorker(settings, db, embedder, detector=Detector() if settings.detect_enabled else None)
collector.detector = embed_worker.detector
trainer = Trainer(db, embed_worker, settings.data_dir / "models")
recognizer = Recognizer(settings, db, collector.publish, canonical=lambda n: canonical(n, species_index()))
retention = Retention(settings, db)
bakeoff = Bakeoff(db, prelabeler.lm, prelabeler, settings.image_dir, lambda n: canonical(n, species_index()))
if settings.ha_publish:
    collector.on_connected = recognizer.publish_discovery
    trainer.after_predict = lambda: recognizer.refresh()
prelabeler.after_visit = recognizer.refresh   # Home Assistant may have heard before LM Studio answered


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.image_dir.mkdir(parents=True, exist_ok=True)
    collector.start()
    trim_existing_clips()
    prelabeler.start()
    retention.start()
    if settings.embed_enabled:
        embed_worker.start()
    if settings.ha_publish:
        recognizer.start()
    if settings.embed_enabled:
        trainer.start_scheduler(settings)
    LOG.info("%s %s started (images %s, db %s)", settings.site_name, __version__, settings.image_dir, settings.db_path)
    yield
    collector.stop.set()
    prelabeler.stop.set()
    embed_worker.stop.set()
    recognizer.stop.set()
    retention.stop.set()


app = FastAPI(title="un-subscribird", version=__version__, lifespan=lifespan)
auth = Auth(settings.data_dir)
PREFIX = re.compile(r"(/[A-Za-z0-9_-]+)+")


INGRESS_PEER = "172.30.32.2"   # Home Assistant's Supervisor: the only sender of Ingress requests


def from_ingress(scope) -> bool:
    """Opened from the Home Assistant sidebar, where HA has logged the person in already. The peer address is
    the TCP connection's (uvicorn only trusts X-Forwarded-For from itself), so a header can't fake it."""
    return settings.ingress and (scope.get("client") or ("",))[0] == INGRESS_PEER


def base_path(request: Request) -> str:
    """The prefix a reverse proxy serves us under (X-Forwarded-Prefix: /birds, or Ingress's X-Ingress-Path),
    or "" when reached directly. The proxy strips it, so routes never see it: only links, redirects and the
    cookie path use this."""
    header = "x-ingress-path" if from_ingress(request.scope) else "x-forwarded-prefix"
    prefix = request.headers.get(header, "").rstrip("/")
    return prefix if PREFIX.fullmatch(prefix) else ""


def logged_in(request: Request) -> bool:
    return not auth.enabled or from_ingress(request.scope) or auth.valid(request.cookies.get(COOKIE))


class HostCheck(TrustedHostMiddleware):
    """Refuses unknown Host headers, except through Ingress: those carry whatever name the person uses for
    Home Assistant, and only the Supervisor can send them."""

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and from_ingress(scope):
            return await self.app(scope, receive, send)
        await super().__call__(scope, receive, send)


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Settings (/admin) and the private API need a login; the kids' page, clips and pictures don't.
    The path comes from the scope, what routing uses: request.url is rebuilt from the client's Host header."""
    path = request.scope["path"]
    if auth.is_public(path) or logged_in(request):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "login required"}, status_code=401)
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"{base_path(request)}/login?next={quote(target)}", status_code=303)


app.add_middleware(HostCheck, allowed_hosts=settings.allowed_hosts)   # outermost: runs before the login
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates",
                            context_processors=[lambda request: {"base": base_path(request)}])
templates.env.globals["cfg"] = settings   # the same object prefs updates, so saved changes show on the next page


# ---- helpers ------------------------------------------------------------------
def species_index() -> dict[str, str]:
    return {r["name"].lower(): r["name"] for r in db.q("SELECT name FROM species")}


def canonical(name: str | None, index: dict[str, str]) -> str | None:
    if not name:
        return name
    return index.get(name.strip().lower(), name.strip())


# What anyone on the network may see (visits v LEFT JOIN labels l). Unreviewed visits only with a named species
# from the list: nothing filters people, so Uncertain, catch-alls and free text wait for a human.
PUBLIC_VISIT = """v.clip IS NOT NULL AND v.excluded=0 AND COALESCE(l.species, v.rec_species) != 'Empty'
                  AND (l.species IS NOT NULL OR (v.rec_species IN (SELECT name FROM species)
                                                 AND v.rec_species NOT IN ('Other animal', 'Unknown bird')))"""


def public_visit(trace_id: str) -> bool:
    return db.one(f"SELECT 1 FROM visits v LEFT JOIN labels l USING(trace_id) WHERE v.trace_id=? AND {PUBLIC_VISIT}",
                  trace_id) is not None


def clip_basename(v, species: str | None) -> str:
    """YYYYMMDD_HHMMSS_species-name (visit time, best known species) for naming a visit's clip."""
    import re
    from datetime import datetime
    when = datetime.fromtimestamp(v["ts"]).strftime("%Y%m%d_%H%M%S")
    sp = re.sub(r"[^a-z0-9]+", "-", (species or "unidentified").lower().replace("'", "")).strip("-") or "unidentified"
    return f"{when}_{sp}"


def disagreement(model: dict | None, cons: dict | None) -> bool:
    """The trained model and LM Studio (or the motion check) name different things for this visit."""
    return bool(model and cons and model.get("species") and cons.get("species")
                and model["species"].strip().lower() != cons["species"].strip().lower())


def visit_disagrees(trace_id: str, index: dict[str, str]) -> bool:
    """disagreement() for one visit, with one query (the Disagree queue checks every unreviewed visit)."""
    sugg = [dict(s) for s in db.q("""SELECT s.source, s.bird_present, s.species, s.confidence, s.other_animal
                                     FROM suggestions s LEFT JOIN frames f ON f.id=s.frame_id
                                     WHERE s.trace_id=? AND s.source IN ('vlm','motion','model')
                                       AND (s.frame_id IS NULL OR f.rejected=0) ORDER BY s.id""", trace_id)]
    models = [s for s in sugg if s["source"] == "model"]
    cons = consensus([s for s in sugg if s["source"] != "model"])
    if cons:
        cons["species"] = canonical(cons["species"], index)
    model = models[-1] if models else None
    return disagreement(model and {**model, "species": canonical(model["species"], index)}, cons)


def visit_json(v, index: dict[str, str]) -> dict[str, Any]:
    frames = [dict(f) for f in db.q("""SELECT f.*, d.source det_source, d.label det_label, d.score det_score,
                                              d.x1, d.y1, d.x2, d.y2 FROM frames f
                                       LEFT JOIN detections d ON d.frame_id=f.id
                                       WHERE f.trace_id=? AND f.rejected=0 ORDER BY f.kind DESC, f.t""",
                                    v["trace_id"])]
    active = {f["id"] for f in frames}
    sugg = [dict(s) for s in db.q("SELECT * FROM suggestions WHERE trace_id=? ORDER BY id", v["trace_id"])
            if s["frame_id"] is None or s["frame_id"] in active]
    for s in sugg:
        s["species"] = canonical(s["species"], index)
        s.pop("raw", None)
    label = db.one("SELECT * FROM labels WHERE trace_id=?", v["trace_id"])
    cons = consensus([s for s in sugg if s["source"] in ("vlm", "motion")])
    others = {s["source"]: s for s in sugg if s["source"] in ("bioclip", "model")}   # the latest of each
    if cons:
        cons["species"] = canonical(cons["species"], index)
        cons["known"] = cons["species"].lower() in index
    model_sugg = others.get("model")
    check = db.one("""SELECT c.*, m.id model FROM label_checks c JOIN models m ON m.id=c.model_id AND m.active=1
                      WHERE c.trace_id=?""", v["trace_id"])
    # The clip's name follows the best "detection": your label > recognised result > LM Studio's suggestion.
    named = (label["species"] if label else None) or \
        (v["rec_species"] if v["rec_species"] not in (None, "Uncertain") else None) or (cons or {}).get("species")
    clip_name = clip_basename(v, named) + ".mp4" if v["clip"] else None
    return {**dict(v), "check": dict(check) if check else None, "clip_name": clip_name,
            "clip_href": f"/clips/{v['trace_id']}/{clip_name}" if clip_name else None,
            "frames": frames, "suggestions": [s for s in sugg if s["source"] in ("vlm", "motion")],
            "consensus": cons, "bioclip": others.get("bioclip"), "model": others.get("model"),
            "disagree": disagreement(model_sugg, cons),
            "label": ({**dict(label), "frame_ids": json.loads(label["frame_ids"]),
                       "frame_species": json.loads(label["frame_species"] or "{}"),
                       "also": json.loads(label["also"] or "[]"),
                       "also_seen": json.loads(label["also_seen"] or "[]")} if label else None)}


def review_json(v, index: dict[str, str]) -> dict[str, Any]:
    """visit_json plus "best": the combined guess Home Assistant would get now (model and LM Studio together,
    see recognition.decide), worked out live for an unlabelled visit. When that is Uncertain, its likelier half."""
    out = visit_json(v, index)
    best = None
    if not out["label"]:
        d = recognizer.decide_visit(v["trace_id"])[0]
        name = canonical(d["guess"] if d["source"] == "uncertain" else d["species"], index)
        if name:
            best = {"species": name, "source": d["source"], "confidence": d["confidence"]}
    return {**out, "best": best}


# ---- pages ----------------------------------------------------------------------
def _page(request: Request, template: str, page: str):
    return templates.TemplateResponse(request, template, {"version": __version__, "page": page})


@app.get("/", response_class=HTMLResponse)
def page_home(request: Request, visit: str | None = None):
    """The kids' page: today's bird clips. Old review links (/?visit=...) go to Settings."""
    if visit:
        return RedirectResponse(f"{base_path(request)}/admin?visit={quote(visit)}", status_code=303)
    return templates.TemplateResponse(request, "home.html", {"version": __version__, "page": "home"})


@app.get("/gallery")
def old_gallery(request: Request):
    """Home Assistant's "Recently seen" photos link here: show that bird on the kids' page."""
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"{base_path(request)}/{query}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def page_review(request: Request):
    return _page(request, "review.html", "review")


@app.get("/admin/dataset", response_class=HTMLResponse)
def page_dataset(request: Request):
    return _page(request, "dataset.html", "dataset")


@app.get("/admin/model", response_class=HTMLResponse)
def page_model(request: Request):
    return _page(request, "model.html", "model")


@app.get("/admin/gallery", response_class=HTMLResponse)
def page_gallery(request: Request):
    return _page(request, "gallery.html", "gallery")


@app.get("/admin/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return _page(request, "settings.html", "settings")


@app.get("/api/settings")
def api_settings():
    return {"prefs": prefs.describe()}


@app.put("/api/settings")
def api_settings_save(changes: dict[str, Any]):
    try:
        prefs.save(changes)
    except ValueError as err:
        raise HTTPException(400, str(err))
    return {"prefs": prefs.describe()}


@app.get("/admin/status", response_class=HTMLResponse)
def page_status(request: Request):
    return _page(request, "status.html", "status")


def _to_admin(page: str):
    def go(request: Request):
        return RedirectResponse(f"{base_path(request)}/admin/{page}", status_code=303)
    return go


for _old in ("dataset", "model", "status"):
    app.add_api_route(f"/{_old}", _to_admin(_old), methods=["GET"], include_in_schema=False)


@app.get("/login", response_class=HTMLResponse)
def page_login(request: Request, next: str = "/admin"):
    return templates.TemplateResponse(request, "login.html", {"version": __version__, "page": "login",
                                                              "next": next, "error": None,
                                                              "configured": bool(auth.password)})


@app.post("/login", response_class=HTMLResponse)
def do_login(request: Request, password: str = Form(""), next: str = Form("/admin")):
    target = next if next.startswith("/") and not next.startswith("//") else "/admin"
    if auth.check_password(password):
        r = RedirectResponse(base_path(request) + target, status_code=303)
        # Secure when the browser came over HTTPS (directly or through a proxy). Plain HTTP logins still work on a LAN.
        https = "https" in (request.scope["scheme"], request.headers.get("x-forwarded-proto"))
        r.set_cookie(COOKIE, auth.make_cookie(), max_age=MAX_AGE, httponly=True, samesite="lax", secure=https,
                     path=base_path(request) or "/")
        return r
    return templates.TemplateResponse(request, "login.html", {"version": __version__, "page": "login",
                                                              "next": target, "error": "That isn't the password.",
                                                              "configured": bool(auth.password)}, status_code=401)


@app.get("/logout")
def logout(request: Request):
    base = base_path(request)
    r = RedirectResponse(f"{base}/", status_code=303)
    r.delete_cookie(COOKIE)
    if base:
        r.delete_cookie(COOKIE, path=base)
    return r


@app.get("/api/public/day")
def api_public_day(day: str | None = None, species: str | None = None):
    """The kids' page: a day's public visits (PUBLIC_VISIT), newest first."""
    from datetime import date, datetime, timedelta
    from .recognition import day_colours
    try:
        d = date.fromisoformat(day) if day else datetime.now().date()
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD")
    start = datetime(d.year, d.month, d.day).astimezone().timestamp()
    end = (datetime(d.year, d.month, d.day) + timedelta(days=1)).astimezone().timestamp()
    rows = db.q(f"""SELECT v.*, COALESCE(l.species, v.rec_species) shown, l.also FROM visits v
                    LEFT JOIN labels l USING(trace_id)
                    WHERE v.ts >= ? AND v.ts < ? AND {PUBLIC_VISIT}
                    ORDER BY v.ts""", start, end)
    also = {r["trace_id"]: [s for s in json.loads(r["also"] or "[]") if s != r["shown"]] for r in rows}
    colours = day_colours([s for r in rows for s in [r["shown"], *also[r["trace_id"]]]])
    out, counts = [], {}
    for r in rows:
        name = "Mystery bird" if r["shown"] in ("Uncertain", "Unknown bird") else r["shown"]
        for s in [name, *also[r["trace_id"]]]:   # a mixed visit counts for each species in it
            counts[s] = counts.get(s, 0) + 1
        if species and species != name and species not in also[r["trace_id"]]:
            continue
        tile = species or name   # filtered by its second species: show and picture that one
        posters = {}
        for s in [name, *also[r["trace_id"]]]:   # each species' own frame, for the chip it is found by
            f = recognizer.best_frame(r["trace_id"], s if s != "Mystery bird" else None)
            posters[s] = f"/img/{f['thumb'] or f['path']}" if f else None
        clip = clip_basename(r, None if name == "Mystery bird" else name) + ".mp4"
        out.append({"trace_id": r["trace_id"], "ts": r["ts"], "species": tile,
                    "also": [s for s in [name, *also[r["trace_id"]]] if s != tile],
                    "dot": colours.get(r["shown"] if tile == name else tile, ""),
                    "clip": f"/clips/{r['trace_id']}/{clip}", "poster": posters.get(tile), "posters": posters})
    out.reverse()   # newest first
    return {"day": d.isoformat(), "today": d == datetime.now().date(), "species": species,
            "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])), "visits": out,
            "dots": {("Mystery bird" if s in ("Uncertain", "Unknown bird") else s): c for s, c in colours.items()}}


# ---- API ------------------------------------------------------------------------
# Cross-check of confirmed labels by the active model (out-of-fold, so it never saw the visit):
# doubtful = it disagrees, or gives the user's label under 60 %. Hidden once checked after that model.
DOUBTFUL = """l.trace_id IS NOT NULL AND v.excluded=0 AND c.trace_id IS NOT NULL
              AND (c.predicted != l.species OR c.p_label < 0.6)
              AND (l.checked IS NULL OR l.checked < m.created)"""
QUEUES = {
    "review": "v.status='prelabelled' AND l.trace_id IS NULL AND v.excluded=0",
    "uncertain": "v.rec_source='uncertain' AND l.trace_id IS NULL AND v.excluded=0",
    "check": DOUBTFUL,
    # To review, narrowed in Python to visits where the model and LM Studio disagree (see visit_disagrees).
    "disagree": "v.status='prelabelled' AND l.trace_id IS NULL AND v.excluded=0",
    "waiting": "v.status IN ('new','frames') AND l.trace_id IS NULL AND v.excluded=0",
    "labelled": "l.trace_id IS NOT NULL AND v.excluded=0",
    "excluded": "v.excluded=1",
    "failed": "v.status='failed' AND v.excluded=0",
    "all": "1=1",
}
CHECK_JOIN = """LEFT JOIN models m ON m.active=1
                LEFT JOIN label_checks c ON c.model_id=m.id AND c.trace_id=v.trace_id"""


@app.get("/api/visits")
def api_visits(queue: str = "review", limit: int = 20, offset: int = 0, species: str | None = None):
    where = QUEUES.get(queue)
    if where is None:
        raise HTTPException(400, "unknown queue")
    args: list[Any] = []
    if species:
        where += " AND l.species=?"
        args.append(species)
    index = species_index()
    if queue == "disagree":   # needs the consensus, which is worked out in Python: filter, then page
        ids = [r["trace_id"] for r in db.q(f"""SELECT v.trace_id FROM visits v LEFT JOIN labels l USING(trace_id)
                                               WHERE {where} ORDER BY v.ts DESC""", *args)
               if visit_disagrees(r["trace_id"], index)]
        page = ids[offset:offset + min(limit, 100)]
        rows = [db.one("SELECT * FROM visits WHERE trace_id=?", t) for t in page]
        return {"total": len(ids), "visits": [review_json(v, index) for v in rows if v]}
    total = db.one(f"SELECT COUNT(*) n FROM visits v LEFT JOIN labels l USING(trace_id) {CHECK_JOIN} WHERE {where}",
                   *args)["n"]
    order = "c.p_label ASC, v.ts DESC" if queue == "check" else "(v.rec_source='uncertain') DESC, v.ts DESC"
    rows = db.q(f"""SELECT v.* FROM visits v LEFT JOIN labels l USING(trace_id) {CHECK_JOIN} WHERE {where}
                    ORDER BY {order} LIMIT ? OFFSET ?""", *args, min(limit, 100), offset)
    return {"total": total, "visits": [review_json(v, index) for v in rows]}


@app.get("/api/visits/{trace_id}")
def api_visit(trace_id: str):
    v = db.one("SELECT * FROM visits WHERE trace_id=?", trace_id)
    if not v:
        raise HTTPException(404)
    return review_json(v, species_index())


class LabelIn(BaseModel):
    species: str
    frame_ids: list[int]
    count: int | None = None
    # Mixed visits: frames (from frame_ids) showing something other than `species`, e.g. {123: "Squirrel"}.
    frame_species: dict[int, str] = {}
    # Other species in the visit without a frame of their own (two birds in one frame). Not training data.
    also_seen: list[str] = []


def save_label(trace_id: str, body: LabelIn, index: dict[str, str]) -> dict[str, Any]:
    """Validate and store one confirmed label. Raises HTTPException on bad input."""
    v = db.one("SELECT * FROM visits WHERE trace_id=?", trace_id)
    if not v:
        raise HTTPException(404, "visit not found")
    name = canonical(body.species, index)
    if not name or name.lower() not in index:
        raise HTTPException(400, f"'{body.species}' is not in the species list (add it on the Dataset page first)")
    valid = {r["id"] for r in db.q("SELECT id FROM frames WHERE trace_id=? AND rejected=0", trace_id)}
    frame_ids = [i for i in body.frame_ids if i in valid]
    if not frame_ids:
        raise HTTPException(400, "pick at least one frame")
    per_frame = {}
    for fid, sp in body.frame_species.items():
        if fid not in frame_ids:
            continue                      # an unticked frame isn't training data, so its species doesn't matter
        other = canonical(sp, index)
        if not other or other.lower() not in index:
            raise HTTPException(400, f"frame {fid}: '{sp}' is not in the species list")
        if other != name:
            per_frame[fid] = other
    if per_frame and len(per_frame) == len(frame_ids):
        raise HTTPException(400, f"every frame is set to another species: none shows {name}")
    seen = set()
    for sp in body.also_seen:
        other = canonical(sp, index)
        if not other or other.lower() not in index:
            raise HTTPException(400, f"also seen: '{sp}' is not in the species list")
        if other not in (name, "Empty"):
            seen.add(other)
    cons = visit_json(v, index)["consensus"]
    source = "confirmed" if cons and cons["species"] == name else "corrected"
    db.set_label(trace_id, name, frame_ids, body.count, source, per_frame, sorted(seen))
    also = sorted({s for s in per_frame.values() if s != "Empty"} | seen)
    return {"ok": True, "species": name, "source": source, "frame_species": per_frame, "also": also,
            "also_seen": sorted(seen)}


def ha_refresh(trace_id: str) -> None:
    if settings.ha_publish:
        try:
            recognizer.refresh(trace_id)
        except Exception as err:  # never fail a label save because of MQTT
            LOG.warning("HA refresh after label change failed: %s", err)


@app.post("/api/visits/{trace_id}/label")
def api_label(trace_id: str, body: LabelIn):
    out = save_label(trace_id, body, species_index())
    ha_refresh(trace_id)
    return out


class BatchItem(LabelIn):
    trace_id: str


@app.post("/api/labels/batch")
def api_label_batch(items: list[BatchItem]):
    """Confirm many visits at once; each item is validated on its own (one bad item doesn't stop the rest)."""
    if len(items) > 500:
        raise HTTPException(400, "at most 500 visits per batch")
    index = species_index()
    results = []
    for it in items:
        try:
            results.append({"trace_id": it.trace_id, **save_label(it.trace_id, it, index)})
            ha_refresh(it.trace_id)
        except HTTPException as err:
            results.append({"trace_id": it.trace_id, "ok": False, "error": err.detail})
    return {"saved": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results), "results": results}


class ExcludeIn(BaseModel):
    excluded: bool = True


@app.post("/api/visits/{trace_id}/exclude")
def api_exclude(trace_id: str, body: ExcludeIn):
    """Keep a visit (and its label) out of training and out of the review queues; reversible."""
    if not db.one("SELECT 1 FROM visits WHERE trace_id=?", trace_id):
        raise HTTPException(404)
    db.set_visit(trace_id, excluded=int(body.excluded))
    return {"ok": True, "excluded": body.excluded}


@app.post("/api/visits/{trace_id}/keep")
def api_keep(trace_id: str):
    """The person looked at a doubtful label and it is right: hide it from Check labels until the next model."""
    with db.tx() as c:
        n = c.execute("UPDATE labels SET checked=? WHERE trace_id=?", (time.time(), trace_id)).rowcount
    if not n:
        raise HTTPException(404, "visit has no label")
    return {"ok": True}


@app.post("/api/frames/{frame_id}/replace")
def api_replace_frame(frame_id: int):
    """Reject a frame (e.g. blurry) and grab a different moment from the same clip, then ask the model about it."""
    f = db.one("SELECT * FROM frames WHERE id=? AND rejected=0", frame_id)
    if not f:
        raise HTTPException(404, "frame not found")
    v = db.one("SELECT * FROM visits WHERE trace_id=?", f["trace_id"])
    if not v["clip"] or not (settings.image_dir / v["clip"]).exists():
        raise HTTPException(409, "this visit has no clip to take another frame from")
    clip = settings.image_dir / v["clip"]
    used = [r["t"] for r in db.q("SELECT t FROM frames WHERE trace_id=? AND kind='clip' AND t IS NOT NULL",
                                 v["trace_id"])]
    t = framelib.replacement_time(clip, used)
    if t is None:
        raise HTTPException(409, "no other usable frame in this clip")
    out_dir = clip.parent
    name = f"f{int(round(t * 10)):04d}"
    full, thumb = out_dir / f"{name}.jpg", out_dir / f"{name}_thumb.jpg"
    framelib.cut(clip, t, full)
    framelib.cut(clip, t, thumb, width=480)
    rel = lambda p: str(p.relative_to(settings.image_dir))  # noqa: E731
    new_id = db.add_frame(v["trace_id"], "clip", rel(full), rel(thumb), t, None, f["width"], f["height"])
    with db.tx() as c:
        c.execute("UPDATE frames SET rejected=1 WHERE id=?", (frame_id,))
    label = db.one("SELECT * FROM labels WHERE trace_id=?", v["trace_id"])
    if label:
        ids = json.loads(label["frame_ids"])
        if frame_id in ids:
            ids = [new_id if i == frame_id else i for i in ids]
            fs = json.loads(label["frame_species"] or "{}")
            if str(frame_id) in fs:       # the new frame is from the same moment's neighbourhood: same species
                fs[str(new_id)] = fs.pop(str(frame_id))
            db.set_label_frames(v["trace_id"], ids, fs)
    new = db.one("SELECT * FROM frames WHERE id=?", new_id)
    try:
        suggestion = prelabeler.label_frame(v["trace_id"], new)
    except Exception as err:  # the frame is still useful without a suggestion
        LOG.warning("Suggestion for replacement frame failed: %s", err)
        suggestion = None
    LOG.info("Visit %s: frame %s rejected, replaced by t=%.1fs (frame %s)", v["trace_id"], frame_id, t, new_id)
    return {"ok": True, "frame": dict(new), "suggestion": suggestion}


@app.delete("/api/visits/{trace_id}/label")
def api_unlabel(trace_id: str):
    db.delete_label(trace_id)
    ha_refresh(trace_id)
    return {"ok": True}


@app.get("/api/species")
def api_species():
    rows = db.q("""SELECT s.*, COUNT(v.trace_id) visits FROM species s LEFT JOIN labels l ON l.species=s.name
                   LEFT JOIN visits v ON v.trace_id=l.trace_id AND v.excluded=0
                   GROUP BY s.name ORDER BY s.kind DESC, s.name""")
    from datetime import datetime
    from .species import FAMILY, FAMILY_NAMES, SEASON_WORDS, season_level
    month = datetime.now().month
    out = []
    for r in rows:
        lvl = season_level(r["name"], month)
        fam = FAMILY.get(r["name"])
        out.append({**dict(r), "season": lvl, "season_text": SEASON_WORDS.get(lvl) if lvl is not None else None,
                    "family": fam, "family_name": FAMILY_NAMES.get(fam) if fam else None})
    return out


class SpeciesIn(BaseModel):
    name: str
    scientific: str = ""
    kind: str = "bird"


@app.post("/api/species")
def api_add_species(body: SpeciesIn):
    name = body.name.strip()
    if not name or body.kind not in ("bird", "other"):
        raise HTTPException(400, "name and kind (bird/other) required")
    if name.lower() in species_index():
        raise HTTPException(409, "already in the list")
    with db.tx() as c:
        c.execute("INSERT INTO species(name, scientific, kind) VALUES (?,?,?)", (name, body.scientific.strip(), body.kind))
    return {"ok": True}


@app.get("/api/model")
def api_model():
    frames = db.one("SELECT COUNT(*) n FROM frames f JOIN visits v USING(trace_id) "
                    "WHERE f.rejected=0 AND v.status IN ('frames','prelabelled')")["n"]
    embedded = db.one("SELECT COUNT(*) n FROM embeddings e JOIN frames f ON f.id=e.frame_id WHERE f.rejected=0")["n"]
    labelled = db.q("SELECT frame_ids FROM labels JOIN visits USING(trace_id) WHERE excluded=0")
    lab_frames = {i for r in labelled for i in json.loads(r["frame_ids"])}
    lab_embedded = db.one(f"SELECT COUNT(*) n FROM embeddings WHERE frame_id IN ({','.join(map(str, lab_frames)) or '0'})")["n"]
    models = [{**dict(m), "classes": json.loads(m["classes"]), "metrics": json.loads(m["metrics"])}
              for m in db.q("SELECT * FROM models ORDER BY id DESC LIMIT 20")]
    vcount = {r["species"]: r["n"] for r in db.q("""SELECT species, COUNT(*) n FROM labels JOIN visits USING(trace_id)
                                                      WHERE excluded=0 GROUP BY species""")}
    return {"frames": frames, "embedded": embedded, "labelled_frames": len(lab_frames),
            "labelled_embedded": lab_embedded, "embed": embed_worker.stats, "trainer": trainer.status,
            "min_visits": 3, "visits_per_species": vcount, "models": models,
            "auto_train": {"enabled": settings.auto_train, "hour": settings.auto_train_hour,
                           "min_new": settings.auto_train_min_new}}


@app.post("/api/model/train")
def api_train():
    if not trainer.start():
        raise HTTPException(409, "training is already running")
    return {"ok": True}


@app.get("/api/bakeoff")
def api_bakeoff():
    return {"status": bakeoff.status, "models": bakeoff.models(), "results": bakeoff.results(),
            "labelled_visits": db.one("SELECT COUNT(*) n FROM labels")["n"]}


class BakeoffIn(BaseModel):
    models: list[str]
    per_species: int = 6
    total: int = 40


@app.post("/api/bakeoff")
def api_bakeoff_run(body: BakeoffIn):
    if not body.models:
        raise HTTPException(400, "pick at least one model")
    if not bakeoff.start(body.models, max(1, min(body.per_species, 20)), max(1, min(body.total, 200))):
        raise HTTPException(409, "a comparison is already running")
    return {"ok": True}


@app.post("/api/models/{model_id}/activate")
def api_activate(model_id: int):
    if not db.one("SELECT 1 FROM models WHERE id=?", model_id):
        raise HTTPException(404)
    with db.tx() as c:
        c.execute("UPDATE models SET active=(id=?)", (model_id,))
    n = trainer.predict_all()
    if settings.ha_publish:
        recognizer.refresh()
    return {"ok": True, "predicted": n}


@app.get("/img/{path:path}")
def get_image(request: Request, path: str):
    """A picture under the image folder. Without a login: only a kept frame of a public visit."""
    if not logged_in(request):
        f = db.one("SELECT trace_id FROM frames WHERE (path=? OR thumb=?) AND rejected=0", path, path)
        if not f or not public_visit(f["trace_id"]):
            raise HTTPException(404)
    root = settings.image_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or not file.is_file():
        raise HTTPException(404)
    return FileResponse(file)


@app.get("/clips/{trace_id}/{name}")
def get_clip(request: Request, trace_id: str, name: str):
    """A visit's clip served under a readable name (YYYYMMDD_HHMMSS_species.mp4): plays in the browser and
    'Save as' / downloads keep that name. The name in the URL is cosmetic; the trace id picks the file.
    Without a login: public visits only."""
    v = db.one("SELECT clip FROM visits WHERE trace_id=?", trace_id)
    if not v or not v["clip"] or not (settings.image_dir / v["clip"]).exists():
        raise HTTPException(404)
    if not logged_in(request) and not public_visit(trace_id):
        raise HTTPException(404)
    safe = name if name.endswith(".mp4") and "/" not in name else f"{trace_id}.mp4"
    return FileResponse(settings.image_dir / v["clip"], media_type="video/mp4", filename=safe,
                        content_disposition_type="inline")


def trim_existing_clips() -> None:
    """Once: cut the dark start off clips collected before 0.15.1, shift their frames' clip times to match,
    and remove the old second copies (clip_view.mp4)."""
    import threading

    def run():
        done = 0
        for r in db.q("SELECT trace_id, clip FROM visits WHERE clip IS NOT NULL AND clip_cut IS NULL ORDER BY ts DESC"):
            if collector.stop.is_set():
                return
            p = settings.image_dir / r["clip"]
            try:
                cut = framelib.trim_start(p, settings.clip_skip_s) if p.exists() else 0.0
            except Exception as err:
                LOG.warning("Visit %s: clip cut failed, left as is: %s", r["trace_id"], err)
                continue
            with db.tx() as c:
                c.execute("UPDATE frames SET t = MAX(0, t - ?) WHERE trace_id=? AND kind='clip'", (cut, r["trace_id"]))
                c.execute("UPDATE visits SET clip_cut=? WHERE trace_id=?", (cut, r["trace_id"]))
            p.with_name(framelib.OLD_VIEW_NAME).unlink(missing_ok=True)
            done += 1
        if done:
            LOG.info("Existing clips: cut the first %.1f s from %d", settings.clip_skip_s, done)
    threading.Thread(target=run, name="clip-cut", daemon=True).start()


@app.get("/api/gallery")
def api_gallery(day: str | None = None, species: str | None = None):
    """A day's visits of one species (confirmed label first, else the recognised result), newest first."""
    from datetime import date, datetime, timedelta
    try:
        d = date.fromisoformat(day) if day else datetime.now().date()
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD")
    start = datetime(d.year, d.month, d.day).astimezone().timestamp()
    end = (datetime(d.year, d.month, d.day) + timedelta(days=1)).astimezone().timestamp()
    rows = db.q("""SELECT v.*, COALESCE(l.species, v.rec_species) shown, l.species confirmed, l.also
                   FROM visits v LEFT JOIN labels l USING(trace_id)
                   WHERE v.ts >= ? AND v.ts < ? AND COALESCE(l.species, v.rec_species) IS NOT NULL
                   ORDER BY v.ts DESC""", start, end)
    also = {r["trace_id"]: [s for s in json.loads(r["also"] or "[]") if s != r["shown"]] for r in rows}
    counts: dict[str, int] = {}
    for r in rows:
        for s in [r["shown"], *also[r["trace_id"]]]:
            if s != "Empty":
                counts[s] = counts.get(s, 0) + 1
    chosen = [r for r in rows if r["shown"] == species or species in also[r["trace_id"]]] if species else \
        [r for r in rows if r["shown"] not in ("Empty",) or also[r["trace_id"]]]
    index = species_index()
    visits = []
    for r in chosen:
        vj = visit_json(r, index)
        visits.append({k: vj[k] for k in ("trace_id", "time", "ts", "frames", "clip", "clip_url", "rec_species",
                                          "rec_source", "rec_conf", "rec_guess", "clip_name", "clip_href")} |
                      {"species": r["shown"], "also": also[r["trace_id"]], "confirmed": r["confirmed"] is not None,
                       "frame_species": (vj["label"] or {}).get("frame_species", {})})
    return {"day": d.isoformat(), "species": species, "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "visits": visits}


@app.get("/api/stats")
def api_stats():
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM visits GROUP BY status")}
    LIVE = "FROM labels JOIN visits USING(trace_id) WHERE excluded=0"
    labelled = db.one(f"SELECT COUNT(*) n {LIVE}")["n"]
    frames = db.one(f"SELECT COALESCE(SUM(json_array_length(frame_ids)),0) n {LIVE}")["n"]
    by_species = [dict(r) for r in db.q(f"""SELECT species, COUNT(*) visits,
                  SUM(json_array_length(frame_ids)) frames,
                  SUM(source='corrected') corrected {LIVE} GROUP BY species ORDER BY visits DESC""")]
    agree = db.one(f"SELECT COUNT(*) n, SUM(source='confirmed') ok {LIVE}")
    excluded = db.one("SELECT COUNT(*) n FROM visits WHERE excluded=1")["n"]
    try:
        usage = shutil.disk_usage(settings.image_dir)
        disk = {"free_gb": round(usage.free / 1024 ** 3, 1), "total_gb": round(usage.total / 1024 ** 3, 1)}
    except OSError:
        disk = None
    return {"version": __version__, "visits": counts, "labelled_visits": labelled, "labelled_frames": frames,
            "excluded_visits": excluded,
            "by_species": by_species,
            "vlm_agreement": (round(agree["ok"] / agree["n"], 3) if agree["n"] else None),
            "collector": collector.stats, "prelabel": {**prelabeler.stats, "lmstudio": prelabeler.lm.status},
            "recognition": recognizer.stats if settings.ha_publish else "disabled",
            "retention": retention.stats(), "disk": disk}
