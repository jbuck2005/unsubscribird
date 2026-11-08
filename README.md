# un-subscribird

<p align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="app/wbs/static/brand/logo-dark.png">
  <img src="app/wbs/static/brand/logo-light.png" alt="un-subscribird: No Strings. Just Wings. A bird breaking free of a rope tether and a broken credit card." width="600">
</picture></p>

Your own bird identification for a Vicohome-based feeder camera, trained on your birds and run on your own computers,
instead of a monthly subscription for AI bird ID.

**What this replaces and what it doesn't.** Recognition, labelling, training and your clip library all run at home.
The camera itself still reports through the Vicohome cloud, which [ha-vicohome-bridge](https://github.com/jbuck2005/ha-vicohome-bridge)
brings into Home Assistant. This project has no connection with Vicohome.

```
Vicohome cloud ──> ha-vicohome-bridge (HA add-on) ──MQTT + MP4 clips──> un-subscribird
                                                                         ├─ collector: snapshot, clip, best frames
                                                                         ├─ pre-labeller: LM Studio vision model (suggestions)
                                                                         ├─ review web UI: you confirm/correct -> labels
                                                                         ├─ trainer: BioCLIP 2 features + classifier, nightly retrain
                                                                         ├─ live recognition -> Home Assistant over MQTT
                                                                         └─ web: kids' clip gallery (public), Settings (login)
```

## What you need

* A Vicohome-based bird feeder camera, and Home Assistant with ha-vicohome-bridge and an MQTT broker
* A computer running Docker. Everything runs on its CPU; the first start downloads the models
* Optional: [LM Studio](https://lmstudio.ai/) with a vision model on any computer, to suggest labels for you to confirm

## Install

```sh
git clone https://github.com/jbuck2005/unsubscribird && cd unsubscribird
cp deploy/.env.example deploy/.env      # then fill it in: your computers, folders and password
chmod 600 deploy/.env
mkdir -p deploy/data deploy/images      # or the folders you set in .env; they must belong to WBS_UID:WBS_GID
docker build -t unsubscribird:latest app
docker compose -f deploy/docker-compose.yaml --env-file deploy/.env up -d
```

Open `http://your-server:8095/`, then log in at `/admin`. Everything specific to your home lives in `.env`:
`WBS_HOST` (this computer), `WBS_HA_HOST` (Home Assistant) and `WBS_AI_HOST` (LM Studio, optional), plus the folders.
With no `WBS_ADMIN_PASSWORD` the Settings area stays locked. Give the site your own name on the Settings page.

For Home Assistant, copy `deploy/ha/unsubscribird.yaml` to `/config/packages/` and put your phone in it. The entities
appear by themselves over MQTT discovery. The species list is tuned to eastern Canada: edit it under Dataset, and set
your region and location in Settings.

**Keep it on your own network.** Port 8095 is plain HTTP and the kids' page has no login. Don't forward it to the
internet. For HTTPS, see below; the login cookie is marked `Secure` there.

## Updating

```sh
git pull
docker build -t unsubscribird:latest app
docker compose -f deploy/docker-compose.yaml --env-file deploy/.env up -d
```

Compare `deploy/.env` with `deploy/.env.example` for new settings. Your database and clips are in your own folders.

## How it works

* **Only labels a person confirms become training data.** Model suggestions never train anything by themselves.
* **Clips lose their dark start.** The camera wakes dark or washed out for about 1.5 s, so each clip is cut once, in
  place, right after download: a lossless stream copy from the first keyframe at or after `WBS_CLIP_SKIP_SECONDS`
  (default 2; the camera's keyframes are 2 s apart). Clips with no keyframe within 0.5 s after that, or that would
  drop under 2 s, stay whole. `visits.clip_cut` records the cut.
* **Empty clips don't pile up.** Once a visit you confirmed as Empty is `WBS_EMPTY_CLIP_DAYS` old (default 14,
  0 = keep forever; also on the Settings page), its clip is deleted. Frames, thumbnails and the label stay, so
  training is unaffected. Excluded visits, and labels changed in the last day, are left alone.
  `visits.clip_removed` records when.
* Frames come from the full-resolution clip (2304x1296), not the 640x360 snapshot. Each clip is scored at
  2 fps for change against its median frame, motion (a frame must differ from *both* neighbours) and sharpness;
  the best few frames, at least 1.5 s apart, are kept.
* Pre-labelling uses whichever vision model LM Studio already has loaded (it never makes LM Studio load or swap
  models unless `WBS_LMSTUDIO_REQUIRE_LOADED=false`). About 3 s per frame on an RTX 5090.

## Web

**Kids' page, http://your-server:8095/ (public).** The day's bird clips, newest first (also oldest first, or by bird). Hover
plays a tile silently; click opens a big player that auto-plays, with ◀ ▶ (also ← → and Esc, or swipe). Day arrows
and per-bird chips. Empty visits never appear. A new visit appears by itself once it is recognised as a named species; anything else (Uncertain, Unknown bird, Other animal) waits until you confirm it, and a confirmed Unknown bird shows as "Mystery bird".

**Settings, http://your-server:8095/admin (login; signed cookie, 30 days).**

* **Review** (`/admin`): keyboard driven: Enter confirm, `/` species, `e`/`s`/`u` quick labels, `1`-`6` toggle frames,
  `j`/`k` move, `z` zoom. ↻ swaps a blurry frame. Check labels and Exclude clean up the training data.
  Disagree lists visits to review where the trained model and LM Studio name different things (check those
  before Confirm all, which takes LM Studio's answer).
* **Gallery** (`/admin/gallery`), **Dataset** (`/admin/dataset`: species colour coded by season, sortable),
  **Model** (`/admin/model`: training, accuracy, LM Studio bake-off), **Status** (`/admin/status`).
* **Settings** (`/admin/settings`): long-term preferences: clip order and theme, the clip cut, frames per visit,
  recognition confidence, the nightly retrain, location. Saved in the database, so they survive redeploys and are in
  the nightly backup, and they apply as soon as you save. A saved value beats `.env`, which beats the default in
  `config.py`, so `.env` is the starting value and the fallback ("↺ default", or a lost database); the page doesn't
  write to it. Passwords and server addresses are only in `.env`.

Everything that changes data needs the login. Clips, frames and `/api/public/*` are public only for visits the kids' page shows; excluded and unconfirmed ones need the login. The app answers only to `WBS_HOST`, `WBS_PUBLIC_URL`'s host, localhost and `WBS_ALLOWED_HOSTS`. Old links redirect
(`/?visit=` to `/admin?visit=`, `/gallery` to the kids' page, `/dataset` and so on to `/admin/...`).

All pages are light from sunrise to sunset at `WBS_LAT`/`WBS_LON` (default Ottawa) and dark otherwise, worked out in
the browser. The ☀️/🌙 button cycles Auto, Light and Dark, remembered per device.

## HTTPS and running under a path

Nothing here is needed for a plain install. To serve the app at `https://example.org/birds/` from a reverse proxy,
strip the path and say what it was; the app then adds it to its links, redirects and login cookie. Reaching port 8095
directly keeps working at the same time. Add the proxy's host name to `WBS_ALLOWED_HOSTS`.

```nginx
location = /birds { return 301 /birds/; }
location /birds/ {
    proxy_pass http://192.168.1.10:8095/;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Prefix /birds;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300;
}
```

## Seed and storage

Seed visits from clips already on Home Assistant:

```sh
ssh root@homeassistant.local 'ls /config/www/vicohome' | docker exec -i unsubscribird python -m wbs.backfill
```

Storage: SQLite in `/data` (`WBS_DATA_PATH`, a local disk), images and clips in `/images` (`WBS_IMAGE_PATH`, a NAS
share is fine; use `WBS_EXTRA_GID` if the share needs a group, and `WBS_IMAGE_PROPAGATION=rslave` if it's automounted).

## Tests

```sh
docker run --rm -v "$PWD":/src:ro python:3.12-slim sh -c 'apt-get -qq update && apt-get -qq install -y ffmpeg >/dev/null;
  pip install -q -r /src/app/requirements.txt pytest httpx; cp -r /src /w && cd /w && python -m pytest -q tests'
```

## Roadmap

1. ~~Collector, frame picker, LM Studio pre-labels, review UI~~
2. ~~Trainer: BioCLIP 2 embeddings (CPU) + classifier head on confirmed labels, cross-validated by visit; nightly
   auto-retrain that activates a candidate only if it isn't worse~~
3. ~~Live recognition: classify each new visit, publish species + confidence to Home Assistant over MQTT;
   low-confidence visits go back into the review queue~~
4. ~~LM Studio bake-off against confirmed labels~~
5. ~~Kids' home page, Settings login~~
6. Coral/edge model export (later)

## Licence

MIT, see [LICENSE](LICENSE). The models it downloads have their own licences: BioCLIP 2 (MIT) and OWL-ViT (Apache 2.0).
