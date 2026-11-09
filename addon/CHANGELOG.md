# Changelog

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
