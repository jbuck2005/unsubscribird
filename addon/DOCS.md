# un-subscribird

Your own bird identification for a Vicohome-based feeder camera, trained on your birds and run on your Home
Assistant computer, instead of a monthly subscription for AI bird ID.

## Before you install

* **Hardware.** Runs on 64-bit x86 or ARM (aarch64) with 8 GB of RAM or more. Recognition and the nightly
  retrain run on the CPU, so they're quicker on an x86 mini PC (Intel N100 or better) than on a Raspberry Pi.
  A 4 GB board is too small: on a 4 GB Raspberry Pi 4 the models pushed Home Assistant into swap until the computer
  ran out of memory, and the add-on's log warns at start when there's less than 8 GB. If your Home Assistant
  computer is that small, run un-subscribird with Docker on another computer instead (see the
  [README](https://github.com/jbuck2005/unsubscribird)).
* **Sharing the computer.** The add-on runs at low CPU priority, so Home Assistant comes first. After you install
  it, or bring in old clips, it works through every visit's frames, which can take hours on a Raspberry Pi; after
  that it's a few visits a day. If Home Assistant still feels slow, set **CPU threads** to 1 and turn off
  **Find the bird with OWL-ViT** (frames are then not cropped to the bird, so recognition is less accurate,
  mostly for small birds).
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

Nothing leaves your network except what the camera already sends to the Vicohome cloud, the model downloads, and
frames sent to LM Studio if you point it outside your network (see below).

## The models

Recognition uses two open models, downloaded from Hugging Face on first start and run entirely on this computer:

* [BioCLIP 2](https://huggingface.co/imageomics/bioclip-2) (MIT) by the Imageomics Institute: Gu et al., "BioCLIP 2:
  Emergent Properties from Scaling Hierarchical Contrastive Learning", NeurIPS 2025.
* [OWL-ViT](https://huggingface.co/google/owlvit-base-patch32) (Apache 2.0) by Google Research: Minderer et al.,
  "Simple Open-Vocabulary Object Detection with Vision Transformers", arXiv:2205.06230, 2022.

Full citations and BibTeX are in the [README](https://github.com/jbuck2005/unsubscribird#models-and-credits).

## AI label suggestions (optional)

Point **LM Studio address** at [LM Studio](https://lmstudio.ai/) with a vision model, to have it suggest labels
for you to confirm. Without it everything still works: you label each visit yourself. Its suggestions are only
suggestions: only labels a person confirms become training data.

* **Your frames go to that address.** Each visit's best frames (JPEG images, which can show people as well as
  birds) are sent to it over plain HTTP. Run LM Studio on a computer on your own network. If you enter an address
  anywhere else, your frames go there too.
* **It runs on another computer**, not in this add-on. A vision model needs a capable GPU or Apple Silicon.
* **It's separate software.** LM Studio and the models you load in it have their own licences and terms. This
  project has no connection with LM Studio.
