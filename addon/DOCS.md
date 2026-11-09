# un-subscribird

Your own bird identification for a Vicohome-based feeder camera, trained on your birds and run on your Home
Assistant computer, instead of a monthly subscription for AI bird ID.

## Before you install

* **Hardware.** Runs on 64-bit x86 or ARM (aarch64) with 8 GB of RAM or more. Recognition and the nightly
  retrain run on the CPU, so they're quicker on an x86 mini PC (Intel N100 or better) than on a Raspberry Pi.
  A 4 GB board such as the Home Assistant Green is likely too small. If your Home Assistant computer is, run
  un-subscribird with Docker on another computer instead (see the [README](https://github.com/jbuck2005/unsubscribird)).
* **Disk.** The image is about 2.5 GB (it includes PyTorch), and the first start downloads BioCLIP 2 and
  OWL-ViT on top of that. Clips come after.
* **[ha-vicohome-bridge](https://github.com/jbuck2005/ha-vicohome-bridge)** brings the camera's visits and clips
  into Home Assistant.
* **An MQTT broker.** The Mosquitto add-on is found by itself. Any other broker goes in the MQTT options.

## Using it

Open **un-subscribird** in the sidebar. Your Home Assistant login opens every page, Settings included, so you
don't need a password. The entities appear by themselves over MQTT discovery. For the dashboard and phone
notifications, see `deploy/ha/` in the repository.

Set your region and location on the Settings page: they tune the species list and the pre-labeller.

## The kids' page

The sidebar needs a Home Assistant login. To show the kids' page on a tablet without one, give the add-on a port
under **Network** (8095 is the usual one), set **This computer's address**, and set a **Settings password** for
Settings on that port. Port 8095 is plain HTTP: keep it on your own network and don't forward it to the internet.

## Where your data lives

* The database, the trained model and the downloaded models are in the add-on's own folder, in Home Assistant
  backups of the add-on.
* Clips and frames are in `/media/unsubscribird`, so they can grow without making every add-on backup bigger.

Nothing leaves your network except what the camera already sends to the Vicohome cloud, and the model downloads.

## AI label suggestions (optional)

Point **LM Studio address** at [LM Studio](https://lmstudio.ai/) with a vision model on any computer. Its
suggestions are only suggestions: only labels a person confirms become training data.
