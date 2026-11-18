# Plan: run un-subscribird on an Orange Pi 6 and use its NPU

Status: planning only, nothing built yet. Written 2026-11-18, updated the same day with James's answers.

Decided: an **Orange Pi 6 (not Plus), 16 GB**. It runs beside the current Docker host for now, as a planning
and test target, and does not replace it. The NPU is for Docker compose only; the Home Assistant add-on may come
later. Exported models live in a `models/` folder.

## Goal

Run the station on an Orange Pi 6 (or 6 Plus) and move the two heavy model calls, bird detection and the
BioCLIP 2 image embedding, onto the board's NPU. Along the way, make detection stop depending on whatever
`transformers` does next (the transformers 5 break of OWL-ViT), by running models we export and pin ourselves.

## What the station runs today

| Step | Code | Model | Runtime |
|---|---|---|---|
| Find the bird | `app/wbs/detect.py` | OWL-ViT base patch32, text queries "a photo of a bird" / "a photo of a squirrel", min score 0.12; falls back to the motion box | transformers + torch, CPU, about 1 s a frame |
| Embed the frame | `app/wbs/embed.py` | BioCLIP 2 (`hf-hub:imageomics/bioclip-2`, a ViT-L/14 CLIP) on 4 or 5 views a frame (full, left, centre, right, bird crop) | open_clip + torch, CPU |
| Zero-shot text | `app/wbs/embed.py` | BioCLIP 2 text tower, one embedding per species, cached until the list changes | open_clip + torch, CPU |
| Classify | `app/wbs/train.py`, `recognition.py` | logistic regression on the stored embeddings, temperature calibrated, per visit | scikit-learn, CPU |

Two facts make the NPU move easier than it looks:

- Only two image encoders need the NPU: OWL-ViT (or its replacement) and the BioCLIP 2 image tower. Text
  embeddings change only when the species list changes, so they can stay on the CPU.
- Embeddings are stored with an `embedder` name (`db.py`), and the classifier trains on them. An NPU embedder
  can be a new name (say `bioclip-2-cix-int8`) beside `bioclip-2`, with its own trained model. Nothing has to be
  thrown away to try it.

CI already builds and smoke-tests an arm64 image (`docker.yml` runs on `ubuntu-24.04-arm`; `edge.yml` and
`release.yml` publish `linux/arm64`), and the add-on lists `aarch64`. So the plain CPU image should already run
on the Orange Pi 6. That needs checking on the board, but it is not new work.

## Hardware facts

Confidence: **solid** = two or more independent sources agree; **check** = one source, or sources disagree.

| Fact | Value | Confidence |
|---|---|---|
| Boards | Orange Pi 6 (90x90 mm, two 2.5GbE, 8 to 32 GB LPDDR5, two M.2 2280 PCIe Gen4 x4, announced June 2026) and Orange Pi 6 Plus (two 5GbE, 16 to 64 GB, on sale since Oct 2025). Same SoC family. [1][2][3] | solid |
| SoC | CIX P1 (CD8180). 12 cores: 4x Cortex-A720 at 2.6 GHz, 4x A720 at 2.4 GHz, 4x A520 at 1.8 GHz, 12 MB L3 [1][4][6] | solid (one review says 2.8 GHz [7]; the P1 was reportedly capped at 2.6 [4]) |
| GPU | Arm Immortalis-G720 MC10, Vulkan 1.3, OpenCL 3.0; mainline Panfrost not working out of the box, vendor Mali stack needed [4][6] | check |
| NPU | Arm China Zhouyi (V3 "X2"), 3 cores, about 28.8 to 30 TOPS; "45 TOPS" is CPU+GPU+NPU combined, no official breakdown [1][2][3][4][5] | solid on name, check on exact TOPS |
| NPU data types | INT4, INT8, INT16, FP16, TF32, maybe BF16 [3][4][7] | check |
| Price | Orange Pi 6 from $239 (8 GB) to $569 (32 GB), AliExpress only, June 2026 [1]; Orange Pi 6 Plus $199 (16 GB) / $249 (32 GB) [3] | check (one source said not announced [2]) |
| Power | 6 Plus measured about 15 W idle, 20 to 30 W in use; a 100 W PSU is recommended to avoid random reboots [3][6] | check (no figures for the plain Orange Pi 6) |
| OS | Vendor Debian 12 / Ubuntu 24.04 images on vendor kernel 6.1 / 6.6.89-cix; Canonical previews Ubuntu 26.04 on Linux 7.0 [2][5][6][7] | solid |
| Mainline Linux | Boots, not all features; no source shows the NPU working on a mainline kernel [4] | check |
| Docker | Runs cleanly on the vendor kernel, `/dev/kvm` present [6] | single source |
| NPU device | `/dev/aipu`, vendor DKMS module `aipu` [5] | single source |

### The NPU software stack

Two ways to run a model on the NPU, both from CIX's "NeuralONE" AI SDK [8][9]:

1. **Compile ahead of time.** On an x86 Linux host, `cixbuild` (CixBuilder 6.1.x, Python 3.10 only) turns a
   fixed-shape ONNX model plus a `.cfg` file into a `.cix` file. The config sets INT8 calibration (a `.npy`
   calibration set), per-layer FP16/INT16 overrides, and the target (`X2_1204MP3`). On the board, the NOE
   runtime (`libnoe`, `cix-noe-umd`) loads the `.cix`; there is a Python wrapper and a C API. [9][10]
2. **ONNX Runtime with the Zhouyi execution provider.** `cix-npu-onnxruntime` / `onnxruntime-zhouyi` with
   `ZhouyiExecutionProvider`. Unsupported ops fall back to the CPU. [5]

Package versions seen: SDK `cix_noe_sdk_25_q3_release` (CixBuilder 6.1.3407, cix-noe-umd 2.0.2) on the Radxa
download site [9]; later boards have libnoe 3.1.2 and driver 6.2.0 from the 26Q2 packages [11]; the Orange Pi
image ships cix-noe-umd 2.0.4 and onnxruntime-zhouyi 1.20.0 [5]. Versions move every quarter and do not line up
between vendors. **The licence for the SDK, driver and runtime is not stated anywhere I found.** The driver is
proprietary [5].

### What is known to run on it

From a third-party model zoo on the same SoC, warm end-to-end times including pre- and post-processing [11]:

| Model | Use for us | Time |
|---|---|---|
| CLIP ViT-B/32 (image and text) | stand-in for BioCLIP 2 | 17 ms |
| SigLIP so400m-384 | upper bound for a big ViT | 1.07 s per image |
| YOLO-World (open vocabulary) | OWL-ViT replacement | 0.98 s (two passes, to work around a broken head) |
| YOLOv8-L | closed-set detector | 44 ms |

Accuracy after INT8: CLIP image embeddings had cosine 0.85 to 0.97 against FP32, SigLIP 0.82 to 0.88, and
YOLO-World's INT8 text tower was badly wrong, so that zoo keeps CLIP text embeddings in FP32 [11].

Known rough edges: the stock driver hung on the second inference until patched [5]; a second
`InferenceSession` in one process failed [5]; dynamic batch sizes fall back to CPU [5]; memory from unloaded
graphs is freed only at process exit [11]; a newer CixBuilder made YOLOv8 three times slower for one user and
the Python wrapper adds about 60 ms of copying per call [10]; header and library versions have mismatched [10].
No source shows OWL-ViT or BioCLIP 2 on this NPU.

**Estimate, not measured:** BioCLIP 2 is ViT-L/14 at 224 px, roughly 4 to 5 times the compute of ViT-B/32 and
less than SigLIP so400m at 384 px. Expect somewhere around 0.1 to 0.4 s a view on the NPU, so 0.5 to 2 s a
frame for 5 views. Batching all 5 views in one call needs a fixed batch of 5 compiled in.

## Architecture changes

### 1. A pluggable inference backend

Today `Detector` and `Embedder` import torch and their model libraries directly. Split each into an interface
and backends:

```
wbs/infer/
  base.py        Detector.find(img) -> box | None;  ImageEncoder.encode(views) -> (n, dim) float32
  torch_cpu.py   today's code, unchanged behaviour (the default)
  onnx.py        onnxruntime, CPU provider; same exported models on any machine
  cix.py         onnxruntime ZhouyiExecutionProvider, or NOE with a compiled .cix
```

- Chosen by `UNSUB_INFER_BACKEND=torch|onnx|cix` (default `torch`), with a health check that falls back to
  `torch` or `onnx` and says so on the status page if the NPU fails to load.
- Each backend reports its own embedder name, so embeddings from different backends never mix in training.
- Text embeddings stay on torch (or a pinned ONNX text tower on CPU), cached as now.
- The `/healthz?deep=1` check runs one real call on whichever backend is active, so the auto-rollback on the
  edge host covers it.

### 2. Own the models: export once, pin the files

This is the backlog item about transformers breaking OWL-ViT. An exported ONNX graph does not change when
`transformers` or `open_clip` do.

- A script (`tools/export_models.py`, run by hand or in a workflow) exports the OWL-ViT (or replacement) image
  path and the BioCLIP 2 image tower to ONNX with fixed shapes, and records the source model revision and a
  checksum of every file.
- The `onnx` backend loads those files and needs only `onnxruntime` and `numpy`. On x86 that is a smaller,
  steadier image than torch, and it is the stepping stone to the NPU: the same ONNX file is the input to
  `cixbuild`.
- OWL-ViT's text queries are fixed ("bird", "squirrel"), so the query embeddings can be computed once at export
  and baked in, leaving an image-only graph. That also removes the text tower from the detector at run time.
- Files live in a `models/` folder. Committed there: a manifest per model (source and revision, export script
  version, input shape, precision, SHA-256) and anything small. Not committed: the big exports (BioCLIP 2's
  image tower is over 1 GB in FP32, and GitHub refuses files over 100 MB), which the export script writes into
  `models/` locally or into `/data/models` on the station, checked against the manifest. A detector trained on
  one household's frames stays in `/data/models` too and never goes in the public repo: weights can carry
  traces of the images they were trained on.

### 3. A smaller or owned detector

OWL-ViT is a large ViT and it already misses small birds. Options, in order of effort:

1. Export OWL-ViT to ONNX as is (keeps today's behaviour, fixes the upgrade problem, may not suit the NPU).
2. YOLO-World with fixed "bird" / "squirrel" prompts baked in: known to compile for this NPU [11].
3. Train our own small detector (a YOLO-class model at 640 px) on the station's own boxes: every OWL-ViT
   detection and every hand-ticked training frame (#62) is a labelled box already. This is the most robust and
   the fastest on the NPU, and it learns small feeder birds that OWL-ViT misses. It needs a labelling and
   review loop and must check the licence of whichever detector family we start from (some YOLO code is AGPL).

The bake-off page (`bakeoff.py`) is the natural place to compare detectors on the station's own visits before
switching.

### 4. Images and CI

- The plain arm64 image already exists. Phase 1 just proves it on the board.
- An NPU image variant, `:edge-cix` / `:<version>-cix`, built on a Debian/Ubuntu base that matches the vendor
  packages (the vendor runtime targets Python 3.10/3.11; our image is Python 3.15, which may not have wheels).
  Alternative: keep our image unchanged and run a small local NPU inference sidecar container that the app
  calls over a Unix socket. The sidecar isolates the vendor stack and its Python version, and nothing leaves the
  machine.
- The container needs `--device /dev/aipu` and the host's driver version must match the runtime in the image.
  Document this for docker compose; the Home Assistant add-on probably cannot use the NPU (HA OS does not ship
  the vendor driver), so the add-on stays on the CPU backend.
- GitHub's arm runners have no NPU. CI can build the `-cix` image and run the `onnx` backend on CPU against the
  same exported files, plus a parity test (ONNX vs torch embeddings, cosine above a threshold). The real NPU
  test runs on the board itself, the same way the edge host proves a build today.
- `.cix` compilation needs the x86 CixBuilder. Run it in a manual workflow on an x86 runner, or by hand, and
  attach the outputs with checksums. Do not bake vendor binaries into the public image until the licence allows
  redistribution.

## Phases

| Phase | What | Done when |
|---|---|---|
| 0. Board check | On the Orange Pi 6 (16 GB), beside the current host: flash the vendor image, install Docker, run today's `:edge` arm64 image on CPU. Record idle/load power, fan noise, CPU time per frame for OWL-ViT and BioCLIP 2. | The station runs on the board on CPU, with numbers |
| 1. Backend interface | Refactor `detect.py` and `embed.py` behind `wbs/infer/`; `torch` backend is today's code. No behaviour change. | Tests pass, edge host unchanged |
| 2. ONNX backend | Export OWL-ViT (image only, queries baked in) and the BioCLIP 2 image tower; `onnx` backend on CPU; parity tests in CI. Can run on the current x86 host too. | Embedding cosine vs torch > 0.999, same detections on the bake-off set |
| 3. NPU proof | On the board: install the vendor runtime, run the ONNX files through the Zhouyi EP, then compile `.cix` with INT8 and with FP16. Measure speed and cosine vs FP32 for each. | A table of speed vs accuracy for each model and precision |
| 4. NPU backend | `cix` backend (sidecar or image variant), new embedder name, retrain the classifier on NPU embeddings, compare visit accuracy with the CPU model on the same visits. | NPU visit accuracy no more than 1 to 2 % below CPU |
| 5. Detector | Bake-off OWL-ViT ONNX vs YOLO-World vs a small trained detector. Pick one per backend. | A detector that is fast on the NPU and at least as good on small birds |
| 6. Release | Docs, compose example with `/dev/aipu`, `-cix` images on edge, then a release. | On edge for at least a week without rollbacks |

Phases 1 and 2 are useful even without the board: they fix the upgrade fragility on the current host.

## Risks

- **Vendor software maturity.** Quarterly SDK drops, versions that disagree between vendors, a driver hang
  that needed a patch, header/library mismatches, a compiler update that made a model slower. Plan for pinning
  exact versions and for falling back to CPU at any time.
- **Licence.** SDK, driver and runtime licences are unknown. If they forbid redistribution we cannot publish
  `-cix` images with them inside; users would install the runtime on the host and mount it.
- **Accuracy loss from INT8.** Training a model for the NPU does not itself cost accuracy. The model is trained
  as usual in full precision; any loss comes only from compiling it down to INT8. That loss is measurable (run the
  same frames through both) and usually small for a CNN detector like YOLO with a good calibration set, often
  under a point or two of mAP. It can be cut further by keeping sensitive layers in FP16 or by quantisation-aware
  training. ViT embedders are touchier: CLIP-style embeddings drifted to 0.85 to 0.97 cosine in one test, and
  retraining the classifier on NPU embeddings absorbs most of that. FP16 for the image tower is the fallback.
- **Transformer support.** ViTs compile on this NPU (CLIP, SigLIP), but OWL-ViT's detection heads and box
  post-processing may fall back to CPU. Keep post-processing in numpy on the CPU regardless.
- **Mainline kernel.** The NPU only works on the vendor kernel today. Moving to mainline or a newer distro may
  lose it.
- **Power and heat.** About 15 W idle is more than a typical SBC. Fine for a mains-powered station, worth
  knowing.
- **The plain Orange Pi 6 is the less-tested board.** It shares the SoC with the 6 Plus, but the NPU fixes I
  found were tested on the 6 Plus and other P1 boards only, and it is newer (June 2026). Its own power figures
  are not published yet.

## Answers so far (2026-11-18)

- Board: Orange Pi 6, not Plus, 16 GB.
- It does not replace the current host; this is planning only for now.
- Not needed in the Home Assistant add-on; maybe later.
- Exported models live in a `models/` folder (see section 2).

- Accuracy: up to 1 to 2 % below the CPU model on the same visits is acceptable for the NPU model.
- Detector: yes, train our own small detector from the station's boxes (option 3 in section 3), with the
  bake-off deciding when it replaces OWL-ViT.
- Conversion: on James's x86 desktop. It runs Windows, and CixBuilder needs x86 Linux with Python 3.10, so it
  runs in WSL2 or a Linux container there (a pinned `tools/cixbuild` container image keeps the version fixed).

No open questions left for planning. Next questions come from phase 0 on the board.

## Sources

1. CNX Software, Orange Pi 6 (CD8180), 2026-06-25:
   https://www.cnx-software.com/2026/06/25/orange-pi-6-cix-cd8180-12-core-arm-sbc-gets-2-5gbe-networking-smaller-form-factor-drops-battery-support/
2. LinuxGizmos, Orange Pi 6 debuts:
   https://linuxgizmos.com/orange-pi-6-debuts-with-cix-p1-soc-dual-2-5gbe-and-45-tops-total-ai-performance/
3. CNX Software, Orange Pi 6 Plus, 2025-10-15:
   https://www.cnx-software.com/2025/10/15/orange-pi-6-plus-cix-p1-sbc-64gb-lpddr5-45-tops-ai-performance/
4. SBCwiki, CIX CD8180 / P1: https://sbcwiki.com/docs/soc-manufacturers/cix/cd8180-p1/
5. NPU on the Orange Pi 6 Plus, driver patch and benchmarks: https://github.com/n4hy/NPU_OrangePi6Plus
6. Tao of Mac review, 2026-04-11: https://taoofmac.com/space/reviews/2026/04/11/1900
7. Boiling Steam review: https://boilingsteam.com/orange-pi-6-plus-review/
8. CIX developer site: https://developer.cixtech.com/
9. Radxa, NPU environment setup (same SoC):
   https://docs.radxa.com/en/orion/o6n/app-development/artificial-intelligence/env-setup and YOLOv8 example
   https://docs.radxa.com/en/orion/o6/app-development/artificial-intelligence/yolov8
10. Radxa forum, CIXBuilder slow inference:
    https://forum.radxa.com/t/cixbuilder-problems-compiling-onnx-model-slow-inference-times/26972
11. CIX P1 NPU model zoo (third party, MS-R1 board): https://github.com/opivankristovi/MS-R1-NPU_model_zoo
