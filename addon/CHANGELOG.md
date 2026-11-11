# Changelog

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
