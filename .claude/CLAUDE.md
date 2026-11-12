# CLAUDE.md

Standing rules for AI assistants working in this repository.

## Commits and pull requests
- Never credit Claude or any AI assistant: no `Co-Authored-By` or session trailers, no "Generated with" lines, no AI author or committer. Commits show only the maintainer.
- Author and committer email: `59450931+jbuck2005@users.noreply.github.com` (GitHub email privacy rejects other addresses).
- No AI provenance tags (C2PA / Content Credentials, XMP) in committed images or other files. Generate binary assets locally and strip metadata before committing.
- Stage files by name. Never `git add -A` or `git add .`.
- Never force-push `main`.
- Name branches `dev/<topic>`. Never put "claude" in a branch name: merging copies it into the history of `main`.
- Keep "claude" and "anthropic" out of commit messages and PR titles, including for changes to this file (write "project rules"). Deployment refuses commits that contain them.

## Privacy
- The repo is public, and the data it handles (feeder clips, images, labels) comes from real households and is of unknown quality. Privacy comes first in every design decision.
- `private/` holds sensitive and source material and is git-ignored. Never commit it, copy its contents into the repo, or quote it in commits, PRs or issues.
- Nothing home-specific belongs in the repo: no IPs, hostnames, paths, names or credentials. `tests/test_public_release.py` checks for common leaks.
- Pages must not call third-party services (no font or script CDNs). Self-host assets.

## Brand (un-subscribird)
- Tagline: "No Strings. Just Wings."
- Palette ("Electric Freedom"): Abyss Blue `#142132` (background, dark mode), Liberation Orange `#F36633` (primary buttons, CTAs), Tech Sky Blue `#3EA0D8` (links, accents), Cyan Highlight `#75D6F9` (hover, focus). On light backgrounds use the deeper variants `#1E6FA3` (blue) and `#C2410C` (orange) to meet WCAG AA. Tokens live at the top of `app/wbs/static/style.css` and `kids.css`.
- Fonts: Montserrat ExtraBold (headings, wordmark) and Inter (body), self-hosted in `app/wbs/static/fonts/` under the SIL Open Font License. Never load fonts from a CDN.
- Wordmark: three tones like the logo, "un-" red-orange, "subscri" amber, "bird" blue. Light-mode shades are deepened to keep 3:1 contrast for large text.
- Logo: the only source is the transparent PNG in `private/`. Generated assets live in `app/wbs/static/brand/` (`favicon-64.png`, `mark-192.png`, `logo-light.png`, `logo-dark.png`).
- Voice: clever but clear, rebellious but professional, community-driven. Bird metaphors sparingly.

## Naming
- Display name: "un-subscribird" (site name, page titles, README heading).
- Code and infrastructure keep `unsubscribird`: repo, Docker image, Home Assistant ids and entity ids (pinned with `default_entity_id`, so renaming the site never changes them). Don't rename those.
- A user's `UNSUB_SITE_NAME` always wins over the default and is shown as plain text.

## Checks
- Run `pytest -q` from the repo root before committing.
