# Scratchpad

My working log for un-subscribird, newest first. This branch is a scratch pad for sharing progress between my
sessions. It is never merged into `main` or `edge`.

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
