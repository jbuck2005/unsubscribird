# Plan: run un-subscribird on an Orange Pi 6 and use its NPU

Status: planning only, nothing built yet. Written 2026-11-18; scope narrowed the same day (see Decisions).

## Scope

un-subscribird only learns to **use** an NPU. It does not build, train or convert models for one. That work
moves to a separate, related project (see "The model tools project" below).

The person running the station picks how recognition runs, in their settings:

- **CPU** (the default, and what every station does today): torch, OWL-ViT and BioCLIP 2, exactly as now.
- **NPU**: the station loads a prebuilt model pack from a `models/` folder and runs it on the NPU.

If the NPU pack is missing, broken or the device isn't there, the station says so on the status page and keeps
running on the CPU.

## Goal

Run the station on an Orange Pi 6 and, when the person chooses, run the two heavy model calls (bird detection
and the BioCLIP 2 image embedding) on its NPU, from model packs made elsewhere.

## What the station runs today

| Step | Code | Model | Runtime |
|---|---|---|---|
| Find the bird | `app/wbs/detect.py` | OWL-ViT base patch32, text queries "a photo of a bird" / "a photo of a squirrel", min score 0.12; falls back to the motion box | transformers + torch, CPU, about 1 s a frame |
| Embed the frame | `app/wbs/embed.py` | BioCLIP 2 (`hf-hub:imageomics/bioclip-2`, a ViT-L/14 CLIP) on 4 or 5 views a frame (full, left, centre, right, bird crop) | open_clip + torch, CPU |
| Zero-shot text | `app/wbs/embed.py` | BioCLIP 2 text tower, one embedding per species, cached until the list changes | open_clip + torch, CPU |
| Classify | `app/wbs/train.py`, `recognition.py` | logistic regression on the stored embeddings, temperature calibrated, per visit | scikit-learn, CPU |

Two facts make NPU support easier than it looks:

- Only two image encoders need the NPU: OWL-ViT (or its replacement) and the BioCLIP 2 image tower. Text
  embeddings change only when the species list changes, so they can stay on the CPU.
- Embeddings are stored with an `embedder` name (`db.py`), and the classifier trains on them. An NPU embedder
  can be a new name (say `bioclip-2-npu-int8`) beside `bioclip-2`, with its own trained model. Nothing has to be
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

## Changes in un-subscribird

### 1. A pluggable inference backend

Today `Detector` and `Embedder` import torch and their model libraries directly. Split each into an interface
and two backends:

```
wbs/infer/
  base.py     Detector.find(img) -> box | None;  ImageEncoder.encode(views) -> (n, dim) float32
  torch.py    today's code, unchanged behaviour (the default)
  pack.py     loads a model pack from models/ and runs it with onnxruntime, on the NPU (Zhouyi provider)
              or on the CPU provider for testing
```

- Chosen by one setting, `UNSUB_INFER_BACKEND=cpu|npu` (default `cpu`), shown on the Settings page. Detection
  and embedding can be set separately later if that turns out useful.
- If `npu` fails to load or its health check fails, the station falls back to `cpu` and shows why.
- Each backend reports its own embedder name (from the pack's manifest), so embeddings from the CPU and the NPU
  never mix. Switching backends means the station re-embeds and retrains its classifier on the new embeddings,
  which the existing training already does; nothing has to be thrown away to try it, and switching back is
  instant because the CPU embeddings are still stored.
- Text embeddings for zero-shot stay on the CPU, cached as now.
- The `/healthz?deep=1` check runs one real call on whichever backend is active, so the auto-rollback on the
  edge host covers it.
- Box post-processing stays in numpy on the CPU, whatever model the pack holds.

### 2. The model pack: the contract between the two projects

A pack is a folder under `models/` (mounted at `/data/models` in the container):

```
models/
  bioclip-2-npu-int8/
    manifest.json   kind (embedder | detector), embedder name, file, runtime (onnxruntime-zhouyi),
                    input shape and preprocessing (size, mean, std), output (embedding dim, or box format
                    and labels), precision, source model and revision, tool versions, SHA-256 of each file
    model.onnx
```

- un-subscribird only reads packs. It checks the SHA-256 against the manifest, refuses a pack whose manifest
  version or output format it doesn't know, and never downloads anything on its own.
- The manifest format is versioned and documented in un-subscribird, because that's where it is read. The model
  tools project writes packs to match.
- Detector packs declare their box format (for example OWL-ViT style or YOLO style), and un-subscribird has a
  small post-processor for each supported format. A new format is a small change here.
- Big weights never go in the public repo (GitHub refuses files over 100 MB; BioCLIP 2's image tower is over
  1 GB). A pack made from one household's frames stays on that station.

### 3. Images and CI

- The plain arm64 image already exists, so CPU mode on the Orange Pi 6 needs no new image.
- NPU mode needs the vendor runtime (`onnxruntime-zhouyi`, `libnoe`) in the container and `--device /dev/aipu`
  in compose. Two options:
  - an image variant `:edge-npu` / `:<version>-npu` on a base that matches the vendor packages (they target
    Python 3.10/3.11; our image is Python 3.15), or
  - mount the host's vendor runtime into the normal image.
  Which one depends on the vendor licence: until it allows redistribution, don't bake their files into a public
  image.
- GitHub's runners have no NPU. CI tests the pack loader with a tiny made-up ONNX model generated in the test,
  run on the CPU provider: manifest checks, checksum refusal, fallback to CPU, and that each backend keeps its own
  embedder name. The real NPU test runs on the board, the same way the edge host proves a build today.
- Docs: a compose example for NPU mode. The Home Assistant add-on stays CPU only (maybe later).

## The model tools project (spin-off)

A separate, related repo (working name `unsubscribird-models`) that makes packs. It runs on a workstation, not
on the station. It would cover:

- **Export**: BioCLIP 2's image tower and OWL-ViT (image only, with the "bird" / "squirrel" queries baked in) to
  fixed-shape ONNX, pinned to a model revision. This also gives a way out of the transformers-upgrade problem,
  because an exported file doesn't change when the library does.
- **Conversion**: calibration and INT8 / FP16 builds for the NPU, in a pinned container with the vendor's
  CixBuilder (x86 Linux, Python 3.10), run on my x86 desktop in WSL2 or a Linux container.
- **Detector training**: a small YOLO-class detector trained on boxes exported from a station (OWL-ViT
  detections and hand-ticked training frames), with a licence check on the detector family (some YOLO code is
  AGPL).
- **Evaluation**: speed and accuracy of each pack against the CPU model on the same frames, with the acceptance
  bar of no more than 1 to 2 % lower visit accuracy.
- **Output**: packs with manifests in the format un-subscribird reads.

Privacy carries over: calibration and training frames come from real households, stay on the machine that runs
the tools, and are never committed. Packs built from public models (BioCLIP 2, OWL-ViT) could be shared; packs
trained on one household's frames are not.

## Phases (un-subscribird)

| Phase | What | Done when |
|---|---|---|
| 0. Board check | On the Orange Pi 6 (16 GB), beside the current host: flash the vendor image, install Docker, run today's `:edge` arm64 image on CPU. Record idle/load power, fan noise, CPU time per frame. | The station runs on the board on CPU, with numbers |
| 1. Backend interface | Refactor `detect.py` and `embed.py` behind `wbs/infer/`; the CPU backend is today's code. No behaviour change. | Tests pass, edge host unchanged |
| 2. Pack loader | Manifest format, `pack.py` on onnxruntime, the Settings choice, fallback to CPU, tests with a made-up model. | CPU-provider tests pass in CI |
| 3. NPU mode | Vendor runtime in the container (image variant or host mount), `/dev/aipu` in compose, first real pack from the model tools project on the board. | A visit recognised on the NPU, within 1 to 2 % of CPU accuracy |
| 4. Release | Docs and compose example, on edge for at least a week without rollbacks, then a release. | Released |

Phases 1 and 2 don't need the board or the spin-off. Phase 3 needs the board and a first pack.

## Risks

- **Vendor software maturity.** Quarterly SDK drops, versions that disagree between vendors, a driver hang
  that needed a patch, header/library mismatches, a compiler update that made a model slower. Plan for pinning
  exact versions and for falling back to CPU at any time.
- **Licence.** SDK, driver and runtime licences are unknown. If they forbid redistribution we cannot publish
  `-npu` images with them inside; users would install the runtime on the host and mount it.
- **Accuracy loss from INT8.** (Mostly the spin-off's problem; un-subscribird only enforces the 1 to 2 % bar.)
  Training a model for the NPU does not itself cost accuracy. The model is trained as usual in full precision;
  any loss comes only from compiling it down to INT8. That loss is measurable (run the
  same frames through both) and usually small for a CNN detector like YOLO with a good calibration set, often
  under a point or two of mAP. It can be cut further by keeping sensitive layers in FP16 or by quantisation-aware
  training. ViT embedders are touchier: CLIP-style embeddings drifted to 0.85 to 0.97 cosine in one test, and
  retraining the classifier on NPU embeddings absorbs most of that. FP16 for the image tower is the fallback.
- **Transformer support.** ViTs compile on this NPU (CLIP, SigLIP), but OWL-ViT's detection heads may fall back
  to CPU. That's why box post-processing stays in un-subscribird on the CPU.
- **Two projects drifting apart.** The manifest version is the guard: un-subscribird refuses a pack it doesn't
  understand, and falls back to CPU.
- **Mainline kernel.** The NPU only works on the vendor kernel today. Moving to mainline or a newer distro may
  lose it.
- **Power and heat.** About 15 W idle is more than a typical SBC. Fine for a mains-powered station, worth
  knowing.
- **The plain Orange Pi 6 is the less-tested board.** It shares the SoC with the 6 Plus, but the NPU fixes I
  found were tested on the 6 Plus and other P1 boards only, and it is newer (June 2026). Its own power figures
  are not published yet.

## Decisions (2026-11-18)

- Board: Orange Pi 6, not Plus, 16 GB. It runs beside the current host, for planning and testing; it does not
  replace it.
- Scope: un-subscribird only supports running on an NPU. Making models (export, conversion, detector training,
  evaluation) is a separate related project.
- The person picks CPU or NPU in their settings; CPU stays the default.
- NPU mode is for Docker compose; not needed in the Home Assistant add-on for now, maybe later.
- Packs live in a `models/` folder.
- Accuracy: up to 1 to 2 % below the CPU model on the same visits is acceptable.
- The spin-off trains our own small detector, and runs conversion on my x86 desktop.

Still to decide: the spin-off's repo name, and whether packs built from public models get published (as release
assets of the spin-off) or are always built locally.

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
