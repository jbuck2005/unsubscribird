# Release log

A narrative history of un-subscribird releases. Each release is the code tagged `v<version>` on `main`, built
into the images `ghcr.io/jbuck2005/unsubscribird:<version>` (and `:latest` for the newest). The short, bullet
form of every change is in [`addon/CHANGELOG.md`](addon/CHANGELOG.md); this file is the readable story behind
each version — what it is for and what changed in your day-to-day use.

How versions move:

- Work merges into `edge` and is published as `:edge` (shown on the pages as `v<version>-edge`) as soon as its
  tests pass. This is the newest, least-tried code.
- A release promotes `edge` into `main` with the version bumped. Tests run on `main`, the `:<version>` and
  `:latest` images are published, and the commit is tagged `v<version>`.

---

## 0.29.0 — 2026-11-14

The release that gathers up the autumn's feature work (the trading cards, the Patterns page's eBird export, the
outdoor-temperature tie-in, the clip re-fetch, and the `UNSUB_` settings rename) under one version, and adds the
pre-release **edge channel** so the newest work can be tried before it is released.

**New in this release**

- **Edge channel.** Every change merged to `edge` is published as `ghcr.io/jbuck2005/unsubscribird:edge` a few
  minutes after its tests pass, before it is released. Its pages show the version with `-edge` on the end (for
  example `v0.29.0-edge`) so a pre-release build is obvious at a glance. Point `UNSUB_IMAGE` at `:edge` in
  `deploy/.env` to follow it; releases still come only from `main`. See the README's "Published images".
- **Delete old models (Model tab).** Every trained model except the active one has a **Delete** button that removes
  it and its file; the active model is protected (switch to another first).

**Carried into the release from the preceding feature work**

- **Bird trading cards.** Ctrl-click (Cmd-click on a Mac) a clip, or press **🃏 Card** in the player, for a
  species' card: its picture, visits today/this week/this year/all time, first seen, favourite time, most at
  once, rank this year, days in a row, two or three fun facts, and links to read more. Every starting species has
  fun facts.
- **Wrong bird? flag.** **⚑ Wrong bird?** in the player, with an optional "What do you think it is?", sends the
  visit to a new **Flagged** queue on the Review page; labelling it there answers the flag.
- **eBird checklists.** The Patterns page builds one checklist a day — every bird the camera saw, with the most
  seen at once — as a file for eBird's *Import data* (eBird Record Format, Extended). Uncounted birds go in as X;
  nothing is sent from here. New eBird settings: location, province/state, country, and protocol.
- **Outdoor temperature.** The home page shows the temperature now, from the sensor named in Settings, and the
  Patterns page charts it (saying "collecting…" until it has an hour of readings).
- **Clips that grew are fetched again.** When the bridge saved a clip before the whole video was uploaded and
  replaced it later, the longer clip is picked up: the last 45 minutes are checked every 5 minutes, and **Fetch
  clips again** on the Status page does the last hours (up to 48) on demand. Unlabelled visits get new frames;
  labelled visits keep theirs.
- **`UNSUB_` settings.** The `.env` settings are now named `UNSUB_...` instead of `WBS_...`. The old names still
  work (through the app and the compose file) and the log says which to rename. Add-on users have nothing to do.
- Smaller touches: the species chip toggles its filter off on a second click; log names and the browser's saved
  choices move to `unsub.` keys on their own.

**Fixed**

- The species-card test no longer fails in the first hour after midnight (it borrowed an hour across the date
  line, which pushed a fixture three days back and broke the day-streak check). This also unblocks the `:edge`
  image build during that hour.

---

## 0.28.0 — 2026-11-12

The kids' **collection book** (a sticker for every bird found this year), the **Patterns** page with a Project
FeederWatch count and a quiet-feeder sensor, **How many?** on Review, **Also seen** for a second species sharing
a clip, and **Retrain every N days**.

## 0.27.0 — 2026-11-11

No waiting on LM Studio when the local model is already sure of the species.

## 0.26.1 — 2026-11-11

Catches still birds that barely move, and shows the running version on the home page.

## 0.26.0 — 2026-11-11

Species autocomplete and a best-guess prefill on the Review page.

## 0.25.3 — 2026-11-09

Clip downloads are retried for 15 minutes, for visits whose video the cloud finishes late.

## 0.25.2 — 2026-11-09

Warns at start-up when the machine has too little memory to run the model well.

## 0.25.1 — 2026-11-09

Gives way to Home Assistant when both share a computer.

## 0.25.0 — 2026-11-09

Add-on configuration drops the options that only repeated the defaults.

---

For releases before 0.25.0, see [`addon/CHANGELOG.md`](addon/CHANGELOG.md).
