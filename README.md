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
* Optional: [LM Studio](https://lmstudio.ai/) with a vision model on a computer with a capable GPU (or Apple Silicon),
  to suggest labels for you to confirm. Without it, you label each visit yourself. LM Studio and its models are
  separate software with their own licences and terms; this project has no connection with LM Studio

## Install

```sh
git clone https://github.com/jbuck2005/unsubscribird && cd unsubscribird
cp deploy/.env.example deploy/.env      # then fill it in: your computers, folders and password
chmod 600 deploy/.env
mkdir -p deploy/data deploy/images      # or the folders you set in .env; they must belong to UNSUB_UID:UNSUB_GID
docker build -t unsubscribird:latest app
docker compose -f deploy/docker-compose.yaml --env-file deploy/.env up -d
```

Open `http://your-server:8095/`, then log in at `/admin`. Everything specific to your home lives in `.env`:
`UNSUB_HOST` (this computer), `UNSUB_HA_HOST` (Home Assistant) and `UNSUB_AI_HOST` (LM Studio, optional), plus the folders.
With no `UNSUB_ADMIN_PASSWORD` the Settings area stays locked. Give the site your own name on the Settings page.

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

Settings were named `WBS_...` before 0.29.0 and are `UNSUB_...` now. An old `.env` keeps working, and the log lists
the names to rename (`WBS_HOST` becomes `UNSUB_HOST`, and so on).

Compare `deploy/.env` with `deploy/.env.example` for new settings. Your database and clips are in your own folders.

## Or as a Home Assistant add-on

If Home Assistant (HA OS or Supervised) runs on a 64-bit x86 or ARM computer with 8 GB of RAM or more, it can run
un-subscribird itself. Add both repositories to your Home Assistant (the camera bridge first, if you don't have it
yet), then install **ha-vicohome-bridge** and **un-subscribird** from the add-on store:

[![Add ha-vicohome-bridge to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjbuck2005%2Fha-vicohome-bridge)
ha-vicohome-bridge

[![Add un-subscribird to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjbuck2005%2Funsubscribird)
un-subscribird

Or by hand: Settings > Add-ons > Add-on store > ⋮ > Repositories, and add `https://github.com/jbuck2005/unsubscribird`
(and `https://github.com/jbuck2005/ha-vicohome-bridge`). un-subscribird opens in the sidebar with your
Home Assistant login, finds the Mosquitto broker by itself and keeps clips in `/media/unsubscribird`. Its
Documentation tab has the rest. It's quicker on an x86 mini PC than on a Raspberry Pi; on a 4 GB board such as the
Home Assistant Green, use Docker on another computer instead.

## How it works

* **Only labels a person confirms become training data.** Model suggestions never train anything by themselves.
* **Mixed visits.** A squirrel can turn up in a chickadee's clip. In Review, mark that frame with 🏷 (or `Alt`+number,
  or `t` then the number) and type what it shows. The visit keeps its main species (clip name, Last bird), each frame
  trains as what it shows, and the other species counts in Home Assistant's Today, the species gallery and the kids'
  page. A frame marked Empty just trains as Empty.
* **Clips lose their dark start.** The camera wakes dark or washed out for about 1.5 s, so each clip is cut once, in
  place, right after download: a lossless stream copy from the first keyframe at or after `UNSUB_CLIP_SKIP_SECONDS`
  (default 2; the camera's keyframes are 2 s apart). Clips with no keyframe within 0.5 s after that, or that would
  drop under 2 s, stay whole. `visits.clip_cut` records the cut.
* **Empty clips don't pile up.** Once a visit you confirmed as Empty is `UNSUB_EMPTY_CLIP_DAYS` old (default 14,
  0 = keep forever; also on the Settings page), its clip is deleted. Frames, thumbnails and the label stay, so
  training is unaffected. Excluded visits, and labels changed in the last day, are left alone.
  `visits.clip_removed` records when.
* Frames come from the full-resolution clip (2304x1296), not the 640x360 snapshot. Each clip is scored at
  2 fps for change against its median frame, motion (a frame must differ from *both* neighbours) and sharpness;
  the best few frames, at least 1.5 s apart, are kept.
* Pre-labelling uses whichever vision model LM Studio already has loaded (it never makes LM Studio load or swap
  models unless `UNSUB_LMSTUDIO_REQUIRE_LOADED=false`). About 3 s per frame on an RTX 5090.
* **Frames sent to LM Studio leave this computer.** Each visit's best frames (JPEGs, which can show people as well
  as birds) go to `UNSUB_AI_HOST` or `UNSUB_LMSTUDIO_URL` over plain HTTP. Keep LM Studio on your own network: any
  address you set there receives your frames.

## Web

**Kids' page, http://your-server:8095/ (public).** The day's bird clips, newest first (also oldest first, or by bird with the rarest first). Hover
plays a tile silently; click opens a big player that auto-plays, with ◀ ▶ (also ← → and Esc, or swipe). Day arrows
and per-bird chips. Empty visits never appear. A new visit appears by itself once it is recognised as a named species; anything else (Uncertain, Unknown bird, Other animal) waits until you confirm it, and a confirmed Unknown bird shows as "Mystery bird". Ctrl-click a clip (or 🃏 in the player) for the bird's trading card
with its stats; ⚑ Wrong bird? sends the visit to Review's Flagged queue. 📖 opens the collection book (`/collection`): a
sticker for every bird found this year, and blanks for the ones on your species list still to find.

**Settings, http://your-server:8095/admin (login; signed cookie, 30 days).**

* **Review** (`/admin`): keyboard driven: Enter confirm, `/` species, `e`/`s`/`u` quick labels, `1`-`6` toggle frames,
  `j`/`k` move, `z` zoom. ↻ swaps a blurry frame. Check labels and Exclude clean up the training data.
  Disagree lists visits to review where the trained model and LM Studio name different things. Confirm all skips
  them (it would save LM Studio's answer unseen) until you confirm each one or change its card, and it warns about
  labelled cards with unsaved changes, which only Update saves.
* **Gallery** (`/admin/gallery`), **Dataset** (`/admin/dataset`: species colour coded by season, sortable),
  **Model** (`/admin/model`: training, accuracy, LM Studio bake-off), **Patterns** (`/admin/patterns`: when
  birds come by hour, week and temperature; the quiet-feeder check; Project FeederWatch counts), **Status** (`/admin/status`).
* **Settings** (`/admin/settings`): long-term preferences: clip order and theme, the clip cut, frames per visit,
  recognition confidence, the automatic retrain (how often, at what hour), location. Saved in the database, so they
  survive redeploys and are in the nightly backup, and they apply as soon as you save. A saved value beats `.env`,
  which beats the default in `config.py`, so `.env` is the starting value and the fallback ("↺ default", or a lost
  database); the page doesn't write to it. Passwords and server addresses are only in `.env`.

Everything that changes data needs the login. Clips, frames and `/api/public/*` are public only for visits the kids' page shows; excluded and unconfirmed ones need the login. The app answers only to `UNSUB_HOST`, `UNSUB_PUBLIC_URL`'s host, localhost and `UNSUB_ALLOWED_HOSTS`. Old links redirect
(`/?visit=` to `/admin?visit=`, `/gallery` to the kids' page, `/dataset` and so on to `/admin/...`).

All pages are light from sunrise to sunset at `UNSUB_LAT`/`UNSUB_LON` (default Ottawa) and dark otherwise, worked out in
the browser. The ☀️/🌙 button cycles Auto, Light and Dark, remembered per device.

## HTTPS and running under a path

Nothing here is needed for a plain install. To serve the app at `https://example.org/birds/` from a reverse proxy,
strip the path and say what it was; the app then adds it to its links, redirects and login cookie. Reaching port 8095
directly keeps working at the same time. Add the proxy's host name to `UNSUB_ALLOWED_HOSTS`.

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

Storage: SQLite in `/data` (`UNSUB_DATA_PATH`, a local disk), images and clips in `/images` (`UNSUB_IMAGE_PATH`, a NAS
share is fine; use `UNSUB_EXTRA_GID` if the share needs a group, and `UNSUB_IMAGE_PROPAGATION=rslave` if it's automounted).

## Tests

```sh
docker run --rm -v "$PWD":/src:ro python:3.12-slim sh -c 'apt-get -qq update && apt-get -qq install -y ffmpeg >/dev/null;
  pip install -q -r /src/app/requirements.txt pytest httpx; cp -r /src /w && cd /w && python -m pytest -q tests'
```

GitHub runs the same tests, plus a lint and an amd64 and arm64 image build, on every pull request. To release,
change the version in both `app/wbs/__init__.py` and `addon/config.yaml`: once the tests pass on `main`, GitHub
publishes the images to GHCR and tags the commit (`v0.25.3`). Pushing a tag yourself publishes that version again.

## Roadmap

1. ~~Collector, frame picker, LM Studio pre-labels, review UI~~
2. ~~Trainer: BioCLIP 2 embeddings (CPU) + classifier head on confirmed labels, cross-validated by visit; nightly
   auto-retrain that activates a candidate only if it isn't worse~~
3. ~~Live recognition: classify each new visit, publish species + confidence to Home Assistant over MQTT;
   low-confidence visits go back into the review queue~~
4. ~~LM Studio bake-off against confirmed labels~~
5. ~~Kids' home page, Settings login~~
6. Coral/edge model export (later)

## Models and credits

un-subscribird stands on two open models. Both are downloaded from Hugging Face on first start, not shipped in the
image, and run entirely on your computer: nothing is sent to them over the network.

* **[BioCLIP 2](https://huggingface.co/imageomics/bioclip-2)** (MIT), by the Imageomics Institute, turns each frame
  into the features your species classifier trains on. Loaded with [OpenCLIP](https://github.com/mlfoundations/open_clip).
  Gu, J., Stevens, S., Campolongo, E., Thompson, M., Zhang, N., Wu, J., Kopanev, A., Mai, Z., White, A., Balhoff, J.,
  Dahdul, W., Rubenstein, D., Lapp, H., Berger-Wolf, T., Chao, W.-L. and Su, Y. "BioCLIP 2: Emergent Properties from
  Scaling Hierarchical Contrastive Learning." *Advances in Neural Information Processing Systems* 38 (2025).
  Model: [doi:10.57967/hf/5765](https://doi.org/10.57967/hf/5765).
* **[OWL-ViT](https://huggingface.co/google/owlvit-base-patch32)** (`google/owlvit-base-patch32`, Apache 2.0), by
  Google Research, finds the bird in each frame. Minderer, M., Gritsenko, A., Stone, A., Neumann, M., Weissenborn,
  D., Dosovitskiy, A., Mahendran, A., Arnab, A., Dehghani, M., Shen, Z., Wang, X., Zhai, X., Kipf, T. and Houlsby, N.
  "Simple Open-Vocabulary Object Detection with Vision Transformers." [arXiv:2205.06230](https://arxiv.org/abs/2205.06230) (2022).

<details><summary>BibTeX, from the model cards</summary>

```bibtex
@software{Gu_BioCLIP_2_model,
  author = {Jianyang Gu and Samuel Stevens and Elizabeth G Campolongo and Matthew J Thompson and Net Zhang and Jiaman Wu and Andrei Kopanev and Zheda Mai and Alexander E. White and James Balhoff and Wasila M Dahdul and Daniel Rubenstein and Hilmar Lapp and Tanya Berger-Wolf and Wei-Lun Chao and Yu Su},
  license = {MIT},
  title = {{BioCLIP 2}},
  url = {https://huggingface.co/imageomics/bioclip-2},
  version = {1.0.0},
  doi = {10.57967/hf/5765},
  publisher = {Hugging Face},
  year = {2025}
}

@inproceedings{NEURIPS2025_94da80cb,
  author = {Gu, Jianyang and Stevens, Sam and Campolongo, Elizabeth and Thompson, Matthew and Zhang, Net and Wu, Jiaman and Kopanev, Andrei and Mai, Zheda and White, Alexander and Balhoff, James and Dahdul, Wasila and Rubenstein, Daniel and Lapp, Hilmar and Berger-Wolf, Tanya and Chao, Wei-Lun (Harry) and Su, Yu},
  booktitle = {Advances in Neural Information Processing Systems},
  editor = {D. Belgrave and C. Zhang and H. Lin and R. Pascanu and P. Koniusz and M. Ghassemi and N. Chen},
  pages = {102778--102811},
  publisher = {Curran Associates, Inc.},
  title = {BioCLIP 2: Emergent Properties from Scaling Hierarchical Contrastive Learning},
  url = {https://proceedings.neurips.cc/paper_files/paper/2025/file/94da80cbfe870c1db958c88a8a27018c-Paper-Conference.pdf},
  volume = {38},
  year = {2025}
}

@software{ilharco_gabriel_2021_5143773,
  author = {Ilharco, Gabriel and Wortsman, Mitchell and Wightman, Ross and Gordon, Cade and Carlini, Nicholas and Taori, Rohan and Dave, Achal and Shankar, Vaishaal and Namkoong, Hongseok and Miller, John and Hajishirzi, Hannaneh and Farhadi, Ali and Schmidt, Ludwig},
  title = {OpenCLIP},
  year = {2021},
  doi = {10.5281/zenodo.5143773}
}

@article{minderer2022simple,
  title = {Simple Open-Vocabulary Object Detection with Vision Transformers},
  author = {Matthias Minderer and Alexey Gritsenko and Austin Stone and Maxim Neumann and Dirk Weissenborn and Alexey Dosovitskiy and Aravindh Mahendran and Anurag Arnab and Mostafa Dehghani and Zhuoran Shen and Xiao Wang and Xiaohua Zhai and Thomas Kipf and Neil Houlsby},
  journal = {arXiv preprint arXiv:2205.06230},
  year = {2022}
}
```
</details>

## Licence

MIT, see [LICENSE](LICENSE). The models it downloads have their own licences: BioCLIP 2 (MIT) and OWL-ViT (Apache 2.0).
