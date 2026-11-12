# Changelog

## Unreleased

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
