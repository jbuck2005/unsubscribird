# Changelog

## Unreleased

* **Home page: "Wrong bird?" names the bird.** The box under a clip now offers the same species autocomplete as
  Review: type "chick" or "bcc" and pick Black-capped Chickadee from the list (the day's other birds are offered
  while it's empty). Anything else typed is still sent as a note. On Review, a flagged visit offers the kid's pick
  first in the species box. The list comes from a new public `/api/public/species`, which holds names and seasons
  only, no counts or labels.
* **Review: pick the exact frame.** Each frame has ◀ and ▶ beside ↻: they swap it for the frame 1 s earlier or
  later in the clip (Shift+click: 0.2 s), and the label follows like ↻. **🎞 Pick a frame from the clip** opens
  the clip in the card, with ±1 s and ±0.1 s steps; **Select this frame** adds the frame on screen to the visit,
  ticked (Confirm or Update saves it). Made for very short visits where the bird is only in the clip for a moment.
* **Fewer Empty visits to review.** Visits that every signal calls Empty (nothing moved or LM Studio saw nothing,
  no detector box, the trained model agrees at 90 % or more, not flagged) skip To review and go to a new
  **Filed Empty** queue. They count as Empty but don't train unless you confirm them, and their clips are deleted
  after `UNSUB_EMPTY_CLIP_DAYS` like confirmed Empty ones. Each morning 2 of the previous day's (Settings: *Empty
  visits to review per day*) come back to To review as training negatives, from the times of day with the fewest
  confirmed Empty visits. Doubtful empties always stay in To review. **Back to review** returns one; Settings:
  *File sure Empty visits* turns it off.
* **Home shows every visit of the day.** The kids' page only listed visits that had a clip, so on a day when the
  camera bridge fetched few clips it said "2 visits so far today" while the gallery had 24. Visits without a clip
  now show too, with their best frame as a still picture (in the tile and the big viewer), and count on the chips,
  the bird's card and the collection book.
* **Safer login.** After logging in you only go to a page on this site. A crafted link such as `next=/\host`
  used to send the browser to another site. Wrong passwords are limited to 10 per address in 5 minutes.
* The public "Wrong bird?" button is limited to 30 flags per address an hour, so nobody can flood the Flagged
  queue.
* **Pin the models** (optional): `UNSUB_OWL_REVISION` and `UNSUB_BIOCLIP_REVISION` take a commit of each model's
  Hugging Face repo, so a change upstream can't change detection or recognition without you knowing. The log
  shows the revision in use. Left empty, the newest files are used, as before.
* `python -m wbs.backfill <folder>` takes the bridge's `clip_folder` (default `vicohome`).
* CI installs only the packages the unit tests need. The real models still run in the Docker build check.
* Releases: the drafted GitHub Release takes its notes from the version's story in `RELEASES.md`, joined into one
  line per item so GitHub shows it without stray line breaks. The changelog section is used if there is no story.

## 0.30.0

* **Phones get fresh pages after an update.** Scripts, styles and icons are versioned by a short hash of their
  content instead of the version number, so any change to them gives new URLs and phones stop using stale cached
  copies.
* **Kids' page: round colour dots.** Species dots are drawn in CSS in a fixed colour instead of emoji circles,
  which looked different on every platform (on Android one species showed as a circle on its chip and a square on
  its card). Mystery birds get a dashed ring. The API and Home Assistant keep the emoji.
* **Review: only bird frames start ticked.** On an unconfirmed visit labelled as a bird, only the frames where the
  detector boxed a bird (the yellow box) are ticked for training. Frames with only a moving region (dashed blue) or
  no box start unticked; click one to add it. If the detector found no bird anywhere in the visit (detector off,
  frames not scanned yet, or a miss), LM Studio's per-frame answers decide as before. Saved labels keep their frames.

## 0.29.0

* "Nothing moved" no longer hides small birds. A bird moving inside or behind the feeder changes only a few hundred
  pixels, too few for the quiet-clip threshold, so those visits were suggested as Empty and skipped LM Studio. A
  clip is now quiet only if no single changed region is big enough to be a bird. At start-up, unlabelled
  "nothing moved" visits of the last 7 days are looked at again, and the ones with something moving go on to
  LM Studio.
* **Review: Count only.** A new checkbox next to Confirm (key `o`) saves the species and how many for the counts,
  FeederWatch and eBird, but keeps the visit's frames out of training. Use it when a bird is too hidden or blurry
  to learn from. Count-only visits show a "count only" chip, aren't cross-checked on Check labels, and don't count
  towards the Model tab's training frames. **Exclude** is unchanged: it still drops a visit from everything, and its
  wording now says so.
* eBird checklists: a bird nobody counted goes in as 1 (every visit shows at least one) instead of X. The number of
  visits stays in each bird's comment; it isn't a count of birds, since the same ones keep coming back.
* **Health check for deploys.** `/healthz` answers 200 when the app is up, and `/healthz?deep=1` also runs
  OWL-ViT and BioCLIP 2 once on a built-in frame and answers 503 if either fails, so an updater can roll back a
  broken image. Cached for a minute; no login; errors are reported by type only.
* Libraries updated: torch 2.15 (CPU build), transformers 5, open_clip 4, numpy 2.5, scipy 1.18, scikit-learn 1.9,
  pillow 13, pydantic 2.14, fastapi 0.162. OWL-ViT works with transformers 5, and the image build now runs both
  models once, so a library change that breaks them fails before it is published.
* The image runs on Python 3.15 (was 3.12).
* Edge builds show the commit in the version label.
* A pre-release **`:edge`** image is now published on every change merged to the `edge` branch, a few minutes
  after its tests pass, so the newest work can be tried before it is released. Its pages show the version with
  `-edge` on the end (for example `v0.29.0-edge`). Releases still come only from `main`; see the README for how
  to follow the edge channel.
* **Model tab:** delete old models. Each trained model that isn't the active one gets a **Delete** button that
  removes it and its file; the active model is protected (switch to another first). Past suggestions that named
  a deleted model keep their text.
* **Admin pages on a phone.** On narrow screens the page links and version fold into a **☰** menu, the Review
  queues sit in one row that scrolls sideways, the keyboard help is hidden, and each visit shows its frames
  first (two to a row) with the lead guess under them and the other guesses behind **+N**. Wider screens are
  unchanged.
* Releases: a second `v*` tag on a day that already had a release is refused before anything is built, and the
  release workflow only drafts the GitHub Release; publishing it is a manual step.

* Clips that grew after they were downloaded are fetched again: the Vicohome bridge may save a clip before the
  whole video is uploaded and replace it later (bridge 0.3.5 re-checks for 30 minutes). Clips from the last 45
  minutes are checked every 5 minutes, and **Fetch clips again** on the Status page does the last hours (up to
  48) on demand. Visits nobody has labelled get new frames from the longer clip; labelled visits keep theirs.
* **eBird checklists** (Patterns page): one checklist a day, every bird the camera saw with the most seen at once,
  as a file for eBird's **Import data** (format *eBird Record Format (Extended)*). Uncounted birds go in as X.
  Nothing is sent from here. New settings under **eBird**: location name, province or state, country, and protocol
  (Stationary or Incidental).
* Home page: clicking the species chip that is already on turns the filter off again.
* Log names start with `unsub.` (were `wbs.`), and the browser's saved choices (theme, clip order, Dataset sort)
  move to `unsub.` keys by themselves.
* Home page: the **outdoor temperature now** next to Today, from the temperature sensor named in Settings
  (Patterns). Hidden when the sensor hasn't reported for half an hour.
* Patterns: while temperatures are still coming in, the chart says how many readings it has and the latest one,
  and each temperature shows "collecting…" until it has an hour of readings, instead of an empty space.
* Home page: **Ctrl-click** a clip (Cmd-click on a Mac), or press **🃏 Card** in the player, for the bird's trading
  card: its picture, visits today, this week, this year and all time, first seen, favourite time, most at once,
  rank this year, days in a row, two or three **fun facts**, and links to read about it. Counted from the clips
  the home page shows.
* Home page: **⚑ Wrong bird?** in the player, with an optional "What do you think it is?". The visit goes to a new
  **Flagged** queue on the Review page; saving its label there answers the flag.
* Settings in `.env` are now named `UNSUB_...` instead of `WBS_...`. The old names still work, through the app and
  the compose file, and the log says which ones to rename. Add-on users have nothing to do.

## 0.28.0

* **Also seen** on the Review page: when a second species shares the clip (a nuthatch beside a chickadee) but has
  no frame of its own, add it there. The visit then shows under both species on the home page.
* New setting under Training: **Retrain every** (1 to 60 days; default 1). **Retrain every night** is now
  **Retrain automatically**.
* Correcting a species renames the clip to match, and links made with the old name lead to the new one.
* Home page: each tile has the visit time on its own line under the species.
* Home page: **By bird** lists the day's rarest visitor first.
* Home page: picking a species shows links to read about it, on Wikipedia and (for birds) All About Birds.
  These are plain links: nothing loads from those sites until you click.
* Kids' **collection book** (📖 on the home page): a sticker for every bird found this year, cropped from your
  own feeder's frames, with the day it first came. Dashed blanks are the birds on your species list still to find.
* New **Patterns** page, starting with a **Project FeederWatch count**: pick two days and get the most birds of
  each species seen at once, ready to copy into FeederWatch (or download as CSV). Nothing is sent anywhere.
* Patterns also shows **when birds come** (by hour of the day and by week through the season) and, with a
  Home Assistant temperature sensor named in Settings, **bird visits per hour at each outdoor temperature**. With
  Docker the sensor needs a long-lived token in `WBS_HA_TOKEN`; the add-on now asks Home Assistant for API access
  to read it.
* New Home Assistant sensor **Feeder quiet** (a problem sensor): on when no birds came for 3 hours (Settings,
  Patterns) at a time of day that usually brings them. Maybe the feeder is empty.
* Review page: a **How many?** box for the most birds of the species at once. FeederWatch counts use it first,
  then LM Studio's count.
* Model page: click a red number in the confusion table to see those visits and what the model made of each
  frame, to see why it got them wrong. Needs a model trained on this version.

## 0.27.0

* Home Assistant hears about a visit at once when the trained model is very sure, instead of waiting up to
  10 minutes for LM Studio. New setting under Recognition: **Don't wait when the model is** (default 98%;
  1 = always wait).
* A late LM Studio answer now updates the visit, so a species the model hasn't learned yet still reaches
  Home Assistant.

## 0.26.1

* A bird that sits still no longer gets marked "nothing moved": before calling a clip empty, OWL-ViT checks
  its best frame, and a bird or squirrel sends the visit to LM Studio as usual. Needs **Find the bird with
  OWL-ViT** on.
* The home page shows the version at the bottom.

## 0.26.0

* Faster labelling on the Review page: the species box autocompletes. Type part of a name (`chick`), the
  initials (`bcc`) or the scientific name, then Enter or Tab takes the highlighted match. Frame tags (🏷) too.
* The species box starts with the best guess: the trained model and LM Studio combined, as Home Assistant
  gets it, with a "Best guess" chip saying where it came from. Waiting visits get one too.
* The "changed" badge only shows on visits you have changed.

## 0.25.3

* Rides out a Home Assistant restart: a clip that can't be downloaded is tried again with growing gaps for
  15 minutes (was about 80 seconds), so a visit during a restart or reboot keeps its clip.

## 0.25.2

* Warns in the log at start when the computer has less than 8 GB of memory. On a 4 GB Raspberry Pi 4 running
  Home Assistant, the add-on ran out of memory.

## 0.25.1

* Easier on a shared computer: runs at low CPU priority, so Home Assistant always comes first.
* New installs use 2 CPU threads instead of 4. Already installed? Set **CPU threads** to 2 (or 1 on a
  Raspberry Pi) in Configuration.
* New option **Find the bird with OWL-ViT**: turn it off on a Raspberry Pi to save memory and CPU, at some cost
  in accuracy for small birds.

## 0.25.0

* First release as a Home Assistant add-on: opens in the sidebar with your Home Assistant login, finds the
  Mosquitto broker by itself, and keeps clips in `/media/unsubscribird`.
