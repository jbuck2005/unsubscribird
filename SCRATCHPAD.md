# Scratchpad

My working log for un-subscribird, newest first. This branch is a scratch pad for sharing progress between my
sessions. It is never merged into `main` or `edge`.

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
