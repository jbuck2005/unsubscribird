# Scratchpad

My working log for un-subscribird, newest first. This branch is a scratch pad for sharing progress between my
sessions. It is never merged into `main` or `edge`.

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
