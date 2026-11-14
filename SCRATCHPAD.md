# Scratchpad

My working log for un-subscribird, newest first. This branch is a scratch pad for sharing progress between my
sessions. It is never merged into `main` or `edge`.

---

## 2026-11-14: Deep health check

**What I changed (PR #57 into `edge`, not merged)**
- `GET /healthz` answers 200 when the app is up. `GET /healthz?deep=1` also runs one real OWL-ViT detection and
  one BioCLIP 2 embedding on a built-in made-up frame, and answers 503 if either fails.
- The result is cached for 60 s, and only one check runs at a time. No login is needed. Failures report only the
  error type.
- New tests in `tests/test_health.py`; the full suite passes (225).

**Why:** my updater's 200 check passed while every OWL-ViT detection failed after #45.

**Status:** waiting for CI and my OK. #56 (the OWL-ViT fix) is ready too and isn't merged yet.

**Next**
- Merge #56 and #57, then switch the updater to `/healthz?deep=1` with a timeout of a minute or two, and roll back
  on anything but 200.

---

## 2026-11-14: OWL-ViT broke on transformers 5

**What happened:** `ff20b55` (#45, the library updates) broke OWL-ViT on my station, so I rolled the app back by
hand to `219a762`. `edge` still points at `ff20b55`.

**Cause:** transformers 5 removed `OwlViTProcessor.post_process_object_detection` (renamed
`post_process_grounded_object_detection`), and `detect.py` still called the old name, so every check raised
`AttributeError`.

**Fix (PR #56 into `edge`, not merged):** call `processor.image_processor.post_process_object_detection`, which
exists in both 4 and 5 with the same output. I chose that over pinning transformers below 5, because open_clip 4
came in with #45 and a pin would give an untested combination. New unit test with a processor shaped like
transformers 5's: it fails on `edge` and passes with the fix. The Docker build now also runs the real OWL-ViT and
BioCLIP 2 calls inside the image (`tests/smoke_models.py`).

**Status:** waiting for #56's CI (image builds plus the model smoke run), then for my OK to merge.

**Next**
- Keep the updater from redeploying `ff20b55` until #56 is merged.
- Merge #56, then let the station deploy it and check that OWL-ViT detections and BioCLIP suggestions are back.

---

## 2026-11-14: Docker container renamed to `unsubscribird`

**What changed.** The app's container on my Docker host now has the name everyone expects, `unsubscribird`. It's set
by `UNSUB_CONTAINER` in the stack `.env`, which is already the public default in `deploy/.env.example` and the compose
file, so nothing in this repo changed. On the host I also updated the container name in the updater script (its
health check, DB backup and rollback use it) and in the nightly backup's list of containers to stop. I backed up every
edited file beside the original first.

**Unchanged on purpose:** the Portainer stack name and id, the stack folder, the data and image paths, the HA ID, topic
and MQTT user (changing those would make new HA entities), and the reverse proxy (it goes by port).

**Status.** Done. It was down for about 8 seconds. Port 8095 answers 200, version 0.29.0, and the updater ran clean
by hand. The updater's next real deploy will be the first to exercise its health check under the new name.

**Next.** The updater's word check flags this branch, so every scratchpad push sends a "don't merge" alert. Skipping
`dev/scratchpad` in that check would stop the noise.

---

## 2026-11-14: Count only, so I can count a bird without training on it (PR #55)

**Why.** Some visits show a bird I can identify but that's too hidden (behind the feeder ball) or blurry to teach
the model anything. Until now a label always made the frames training data (Confirm needed a ticked frame), and
Exclude was the only way out of training. But Exclude also drops the visit from counts, FeederWatch and eBird.

**What I changed** (PR #55 into edge, `dev/count-only`):
- A **Count only** checkbox next to Confirm on Review (key `o`). The species, Also seen and How many still go
  into the counts, FeederWatch, eBird, the home page and HA. The frames never train the model. No frame needs to be
  ticked. A saved one shows a "count only" chip.
- Stored as `labels.train` (default 1, so existing labels are unchanged). Training, auto-retrain, the bake-off,
  the Model tab's counts, the Check labels queue and the Dataset page's training frames skip `train=0`.
- Exclude still means "not a real visit": it drops the visit from everything. Its wording now says so.
- 224 tests pass, including the new `tests/test_count_only.py`.

**Status.** PR open, waiting for my review and merge into edge.

**Next.** Once it's on edge, tick Count only on the hidden-bird visits from today's quiet-clip pairs.

---

## 2026-11-14: "Nothing moved" was hiding small birds (PR #54)

**What I saw.** In Review, pairs of visits a minute or two apart (1:39/1:40, 1:42/1:44) were all "nothing moved",
Empty 90%, with LM Studio skipped. One pair had a bird moving inside the feeder ball; the other had a bird sitting
behind it. I worried the bridge's SD path was double counting.

**What I found.**
- Not double counting. None of November's 731 clips share a sha256, and the frame times differ between each pair,
  so they're separate recordings. The camera just fired twice for a bird that stayed.
- The quiet test only looked at the share of changed pixels (`quiet_activity` 0.025). A small bird inside the ball
  changes far less than that, so it read as empty and LM Studio never saw it.

**What I changed** (PR #54, `dev/quiet-small-birds`):
- `frames.largest_blob()` finds the biggest connected changed region. A clip is quiet only if activity is low and
  no region is bird-sized (`QUIET_BLOB` 0.15% of the picture).
- At start-up, unlabelled quiet visits from the last 7 days are checked again. The ones with movement lose the
  Empty suggestion and go to LM Studio.
- `pytest -q`: 225 passed.

**Next.** Merge, then watch `:edge`: the recheck line in the log, and how many empty clips with wind now reach LM
Studio. To try real clips first, there's a probe script, `quiet_check.py`, in the project files. Run it with
`docker exec -i <container> python - 2026/11/14 < quiet_check.py`.

---

## 2026-11-14: Library updates and README notes merged into edge

**What I changed**
- Fixed the updater on my Docker host. It now accepts Dependabot's noreply address as author and ignores
  `Co-authored-by: dependabot[bot]`. The station deployed `219a762` (#44).
- #45 (16 library updates): added a Dockerfile change so the CPU-only torch 2.15.0 / torchvision 0.29.2 match
  `requirements-ml.txt` and the amd64 image doesn't pull CUDA torch. Both image builds and the import check passed,
  and I squash-merged it into `edge` as `ff20b55`.
- #50 (README: keep `edge`, squash bot PRs, and which authors a deploy host should accept): squash-merged as
  `3f4a886`.

**Watch on `:edge`**
- transformers 4 to 5 and open_clip_torch 2 to 4 are major jumps, and the tests use a fake embedder. Check that
  BioCLIP loads, frames get embeddings, and suggestions and training still work. If the model download or the
  first embedding fails, roll back by reverting `ff20b55` on `edge`.
- The amd64 image size should stay about the same. A big jump would mean CUDA torch slipped in.

**Still open:** #43 (Python 3.15), no-go. Old `RELEASE_TZ` item, and the bridge's #20 date check, are in their
own threads.

---

## 2026-11-14: Dependabot squash merges

**What I changed**
- Squash-merged #44 (docker/login-action 3 to 4) into `edge` as `219a762`.

**Problem:** a squash merge on github.com keeps the bot as the **author**:
`219a762` is authored by `dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>` and committed by
`GitHub <noreply@github.com>`. If the updater wants my address as author, it will skip this commit. `edge` can't be
rewritten (and the ruleset blocks force pushes), so the fix belongs in the updater: accept `dependabot[bot]` as
author when GitHub is the committer.

**Held**
- #45 (the python group, 16 updates): CI is green, but the Dockerfile still installs `torch==2.5.1` from the CPU
  index, and then `requirements-ml.txt` asks for `torch==2.15.0` from PyPI. On amd64 that pulls the CUDA build
  (several GB of nvidia packages). The Dockerfile pins need to move to torch 2.15.0 / torchvision 0.29.2 together
  with it. It also jumps transformers 4 to 5 and open_clip 2 to 4, and the tests use a fake embedder, so BioCLIP
  only gets proven on the `:edge` host.
- #43 (Python 3.15): no-go, see below.

**Next**
- Decide on the updater rule, then #45 with the Dockerfile fix.

---

## 2026-11-14: Python 3.15 base image (Dependabot #43): no-go

**What I checked**
- CI on #43: pytest and lint are green, but they run on Python 3.12, not on the image. The Docker build fails
  (arm64 failed, amd64 was cancelled) at `pip install`: numpy 2.2.1 has no 3.15 wheel, pip tries to build it from
  source, and the slim image has no compiler.
- Wheels for 3.15 with today's pins: none for numpy 2.2.1, scipy 1.14.1, scikit-learn 1.6.0, pillow 11.0.0,
  torch 2.5.1, torchvision 0.20.1 or pydantic-core 2.27.2 (pulled in by pydantic 2.10.4). PyYAML (from
  `uvicorn[standard]`) has no 3.15 wheel at all; it builds from source in its pure-Python form.
- With newer pins (numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1, pillow 13.0.0, pydantic 2.14.3) the full suite
  passes on 3.15 (220 passed; tested on 3.15.0b4). The only warnings come from libraries (joblib, starlette,
  fastapi), none from our code.
- Not tested: the torch/BioCLIP stack on 3.15 (torch 2.5.1 must move to a release with 3.15 wheels, and the
  PyTorch CPU index isn't reachable from the cloud session), and building the image (no Docker there).

**Status:** No-go as it stands. I haven't merged it.

**Next**
- Either close #43 and stay on 3.12 (torch 2.5.1 supports up to 3.13), or do a proper upgrade PR: base image plus
  numpy, scipy, scikit-learn, pillow, pydantic, torch and torchvision, built and smoke-tested on my Docker host
  before merging.

---

## 2026-11-14: Squash-merge bot PRs

**What I changed**
- PR #50 now also says to merge Dependabot and other bot PRs into `edge` with **Squash and merge**, never with a
  merge commit. My updater only deploys commits that I authored and committed.

**Status:** PR #50 is open and its checks are re-running. Dependabot PRs #43 to #45 are on `edge` and aren't
merged yet; they wait for my OK.

**Watch out:** a squash merge done on github.com is committed by "GitHub <noreply@github.com>", and on a bot PR
the author stays the bot. The squash commit from #46 shows that. If the updater checks the committer as well as
the author, a web squash merge won't pass it. In that case either squash the bot PR locally under my name and push
it to `edge`, or let the updater accept GitHub as committer when I'm the one who merged.

**Next**
- Decide how the updater should handle web merges, then merge #43 to #45.

---

## 2026-11-14: edge restored, Dependabot PRs back on edge

**What I changed**
- `origin/edge` exists again at `6156d72`, the same commit as `main`, with 0.29.0 staged and untagged. The update
  job on my Docker host can fetch it again, so the station should move off `0309900` on its next run.
- Moved Dependabot PRs #43, #44 and #45 back to `edge`. They had been switched to `main` when `edge` was deleted.

**Status:** Done, apart from the old `scratchpad` branch. The cloud session gets a 403 when it tries to delete
branches, so I'm deleting it myself on the branches page.

**Next**
- Delete `scratchpad` on GitHub.
- Check that the host's update job is green on its next run.

---

## 2026-11-14: Rulesets for main and edge

**What I changed**
- I added a "Protect main and edge" ruleset (Restrict deletions, Block force pushes) to both repos.

**Status**
- un-subscribird: GitHub now reports `main` and `edge` as protected. Done.
- ha-vicohome-bridge: GitHub still reports `main` and `edge` as unprotected, so that ruleset probably isn't
  Active yet, or its targets don't match. I need to check it.

**Next**
- Fix the ha-vicohome-bridge ruleset (Enforcement status Active, targets `main` and `edge`).
- Merge PR #50 (README note; checks are green).
- Still to do: delete the old `scratchpad` branch, and set `RELEASE_TZ`.

---

## 2026-11-14: Keep edge from being deleted

**What I changed**
- `edge` was deleted when the release PR (edge into main) merged, because "Automatically delete head branches" is
  on. I recreated `edge` from `main`. They were the same commit, so nothing was lost.
- The stray `claude/project-thread-*` branch is already gone from GitHub.
- PR #50 into `edge` adds a note to the README's Releasing steps: protect `main` and `edge` with a ruleset, and
  recreate `edge` with `git push origin main:edge` if it ever goes missing.

**Status:** Waiting on me. The cloud session can't create rulesets, so I'm adding one in both repos (this one and
ha-vicohome-bridge): Settings → Rules → Rulesets → New branch ruleset, targets `main` and `edge`, with Restrict
deletions and Block force pushes. Auto-delete stays on for topic branches.

**Next**
- Add the rulesets, then merge PR #50.
- Still to do: delete the old `scratchpad` branch, and set `RELEASE_TZ`.

---

## 2026-11-14: Local checkout on my PC checked

**What I found**
- My local clone is on `main`, level with `origin/main` (0.29.0 notes, #48). Tracked files look untouched since my pull.
- `edge` no longer exists on GitHub. It looks like it was deleted when #49 merged. Rules and `edge.yml` still need it.
- There is a stray `claude/project-thread-z2w4r3` branch on GitHub that breaks the branch-name rule.
- Old local worktree `.claude/worktrees/edge-channel` (branch `dev/edge-channel`) is already in `main`.

**Status:** Waiting on me to OK recreating `edge` from `main`.

**Next**
- Recreate `edge` at `main`, then track it locally. Delete the stray branch and the old `scratchpad` branch.

---

## 2026-11-14: Release day follows my time zone

**What I changed**
- Decided that `RELEASE_TZ` will be `America/Toronto`, so the one-release-a-day guard counts my local day, not UTC.

**Status:** Waiting on me. The cloud session can't set repository variables, so I'm setting it on GitHub:
Settings → Secrets and variables → Actions → Variables → New repository variable, name `RELEASE_TZ`, value
`America/Toronto` (or `gh variable set RELEASE_TZ --body America/Toronto -R jbuck2005/unsubscribird`).

**Next**
- Once it's set, the next tag's "One release a day" step should log `(America/Toronto)`.
- Still to do: delete the old `scratchpad` branch.

---

## 2026-11-14: Phone layout promoted to main (0.29.0 staged)

**What I changed**
- I tested the phone layout on the `:edge` image. It looks much better, so I promoted it.
- PR #48 (into `edge`) adds the phone layout (#47) and the release guard rails (#46) to the 0.29.0 notes in
  `addon/CHANGELOG.md` and `RELEASES.md`. 0.29.0 was never tagged, so both ship with it and the version stays 0.29.0.
- PR #49 moves `edge` into `main`. `main` was fast-forwarded to `edge` (same commits, no merge commit), and the
  checks were green.

**Status:** `main` and `edge` point at the same commit. 0.29.0 is staged on `main` and still untagged. Nothing has
been published.

**Next**
- When I'm ready, push the `v0.29.0` tag (one release a day). The workflow builds the images and drafts the GitHub
  Release, and I publish it by hand.

---

## 2026-11-14: Release guard rails merged into edge

**What I changed**
- Merged PR #46 into `edge` after its checks went green. It didn't touch the same files as the phone-layout PR
  (#47), so no rebase was needed. From now on, `release.yml` refuses a second tag on the same day and only drafts
  the GitHub Release.
- Moved this scratch pad to `dev/scratchpad` to follow the `dev/<topic>` naming.

**Status:** Done on `edge`. The `:edge` image rebuilds from this push. No tag and no release.

**Next**
- Delete the old `scratchpad` branch on GitHub (the cloud session couldn't).
- Decide whether to set `RELEASE_TZ` to my local time zone.
- The guard first runs for real on the next tag, once `edge` is promoted to `main`.

---

## 2026-11-14: Phone layout for the admin pages

**What I changed**
- The admin pages were very cluttered on my phone, so I opened PR #47 into `edge` (branch `dev/mobile-admin`).
  It only changes screens up to 640px wide:
  - The header shows the logo, a menu button that names the current page, and the theme toggle. The nine page
    links and the version moved into the menu.
  - The review queues are one row of chips that scrolls sideways. The keyboard help is hidden on phones, and the
    queue hint is cut to two lines (tap to read all of it).
  - Visit cards show the frames first, two to a row, then the lead guess. The other guesses sit behind a `+N`
    button.
  - Wider screens keep their layout.
- Tests pass (213), including the new `tests/test_mobile_nav.py`.

**Status:** I merged #47 into `edge` on 2026-11-14. That push rebuilds the `:edge` images. No tag and no release.

**Next**
- Pull the new `:edge` image on my Docker host and check the admin pages on my phone.

---

## 2026-11-14: Release guard rails

**What I changed**
- I checked the setup. `main` and `edge` both exist, every push to `edge` that passes the tests already publishes
  the `:edge` images, and releases only run when I push a `v*` tag by hand.
- I opened PR #46 into `edge` (branch `dev/release-guard`):
  - **One release a day.** `.github/scripts/release_guard.py` runs before any image is built. A second `v*` tag on
    the same day fails the release and publishes nothing. The day is counted in the `RELEASE_TZ` repo variable,
    or UTC if that isn't set.
  - **Draft only.** After the images are up, the workflow drafts a GitHub Release with the changelog section as
    its notes. Publishing it is up to me.
  - Took out the old `workflow_run` and tag-job code in `release.yml`, which never ran.
  - Added a "Releasing" section to the README covering edge, testing on my Docker host, staging into `main`,
    tagging, and publishing. Updated `RELEASES.md` and the project rules to match.
  - New tests in `tests/test_release_guard.py`. The full suite passes (218), and CI on the PR is green.

**Status:** PR #46 is open and waiting on my review.

**Next**
- Review and merge PR #46 into `edge`.
- Decide whether to set `RELEASE_TZ` to my local time zone.
- `v0.29.0` is staged on `main` but not tagged yet. Tag it when I'm ready (one release that day).
