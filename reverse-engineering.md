# Reverse engineering the Vicohome camera and cloud

What we have learned about the Vicohome bird-feeder camera (tested with the CG625) and the Vicohome cloud,
how we learned it, and what un-subscribird and [ha-vicohome-bridge](https://github.com/jbuck2005/ha-vicohome-bridge)
do about it. This project has no connection with Vicohome; everything here comes from public open-source work,
our own camera and account, and the behaviour of the official app.

Ground rules we kept throughout:
- **No Vicohome code.** Nothing is copied from the app. Protocol details are reimplemented from observed
  behaviour and from MIT-licensed projects, which are credited below.
- **No personal data in the repos.** Serial numbers, account details, trace and clip ids, signed URLs and network
  addresses never go into code, tests, docs or commits. Tests use made-up data.
- **Read-only by default.** We only read the cloud API (login, device list, visit list, media), except where the
  camera's own local path needs a command to serve its microSD card (see [The camera's local path](#the-cameras-local-path-webrtc-and-the-microsd-card)).

```
camera ──upload──> Vicohome cloud ──REST + HLS──> ha-vicohome-bridge (HA add-on) ──MQTT + MP4──> un-subscribird
   └────────── local WebRTC data channel (microSD recordings) ──────────┘
```

## Methods

| Method | What it gave us |
|---|---|
| **Open-source clients**: [dydx/vico-cli](https://github.com/dydx/vico-cli) (MIT) | The cloud's REST endpoints, login and region hosts. ha-vicohome-bridge is a ground-up Python rewrite of these calls. |
| **Prior art, ideas only**: [KIWIDUDE564/vicohome-bridge-addon](https://github.com/KIWIDUDE564/vicohome-bridge-addon) | That a Home Assistant bridge over MQTT is workable. It has no licence, so none of its code is used. |
| **Open-source WebRTC client**: [averagenative/vicolocal](https://github.com/averagenative/vicolocal) (MIT) | Signalling for the camera's local WebRTC session, and the aiortc work-arounds. Its compact-SDP codec is vendored in the bridge as `vico_sdp.py`. |
| **Live capture of the official app** | The compact ("KISS") SDP format: reference offer/answer pairs from the app's `SdpTransform.compressOfferToJson` / `decompressAnswerToSdp`, which the codec's unit tests check against. The captures stay local, because they contain account and device data. |
| **Black-box polling and logs** | How the cloud lists visits (late, in overlapping windows), when clips are ready, and the 12 November 2026 change (below). Read from the bridge's own logs and Home Assistant's state, with credentials filtered out. |
| **Measuring the camera's clips** with ffprobe and the frame picker | Clip lengths, keyframe spacing, the dark wake-up at the start, and motion thresholds (below). Done on real feeder clips, recorded as dated comments in the code. |
| **A fake cloud** (`tests/e2e_fake_cloud.py` in the bridge) | End-to-end tests of login, device list, visit list and HLS playlists that grow after they look finished, without touching the real cloud. It checks our work-arounds; it is not evidence of how the real cloud behaves. |
| **Comparing with the app** | The app showing 20-second videos when we had 2-second clips is what proved the short clips were our timing, not the camera. |

## The cloud REST API

All calls are JSON `POST`s to a regional host: `https://api-us.vicohome.io` (US) or `https://api-eu.vicoo.tech` (EU).
The country code sent in requests follows the host (`US` or `EU`).

- **Login**: `POST /account/login` with `email`, `password`, `loginType: 0`. Success is `result: 0`; the token is at
  `data.token.token`. It goes, as is (no scheme), in the `Authorization` header of later calls. The bridge caches it
  for 20 hours and logs in again when a call is refused. After a failed login it waits at least 15 minutes, so it
  never hammers the login endpoint.
- **Errors**: `code` (or `result`) other than 0. Codes -1024 to -1027, or a message mentioning token, login or
  auth, mean the session is no longer valid.
- **Connections**: the API closes idle keep-alive connections after less than a minute, about as often as the
  bridge polls. A request that meets a closing connection is sent once more on a fresh one (bridge 0.3.1);
  timeouts are not retried.
- **Devices**: `POST /device/listuserdevices` (`language`, `countryNo`) returns `data.list`, with `serialNumber`,
  `deviceName`, `modelNo`, `ip`, `batteryLevel`, `signalStrength`, `isCharging`, `wifiChannel`, `locationName`,
  `networkName`, `macAddress`.
- **Visits**: `POST /library/newselectlibrary` with `startTimestamp` and `endTimestamp` (unix seconds, as
  strings), `language`, `countryNo`. It returns `data.list`, newest first. Each visit has:
  - `traceId`, `serialNumber`, `deviceName`, `timestamp` (seconds; milliseconds are accepted too);
  - `period`, the video length in seconds;
  - `receivedAllSlice`: false while the cloud has only part of the video;
  - `imageUrl`, `keyshots[].imageUrl`, and `videoUrl` (an HLS playlist);
  - `subcategoryInfoList[]`: in the entry with `objectType: "bird"`, `objectName` is the bird, `birdStdName` its
    Latin name, and `confidence` either 0 to 1 or 0 to 100.
- **Visits arrive late.** The cloud sometimes lists a visit minutes after it happened, so each poll's window
  overlaps the previous one by 30 minutes (at most 24 hours back), and duplicates are dropped by trace id. Visits
  typically reach the bridge 20 to 65 seconds after they happen.
- **Media**: URLs on `vicohome.io` or `vicoo.tech` take the token; signed image and segment URLs need no auth and
  expire.
- **Other calls** used by the microSD-card path: `/device/getWebrtcTicket` (the signalling ticket; the request
  identifies itself as the Android app) and `/library/showLocalTab` (whether the camera has a card).
- **The cloud's own bird ID**: on our account, which has no subscription, every visit comes back "Unidentified"
  (0 identified of 135 visits on 12 November 2026, for example). That is the gap un-subscribird fills.

## Cloud clips (HLS) and the 12 November 2026 change

A visit's video is an HLS playlist (`.m3u8`) of signed `.ts` segments, about 2 seconds each. The bridge turns it
into an MP4 without re-encoding (ffmpeg `-c copy`, `aac_adtstoasc`, `+faststart`), saves it under
`/config/www/vicohome/<trace id>.mp4`, and publishes its `/local/...` URL over MQTT. un-subscribird downloads it
from there.

Until 12 November 2026 the bridge treated a playlist as complete once it had a segment and `#EXT-X-ENDLIST`.
**From 08:00 local time that day**, most saved clips were exactly 2.0 seconds (about 480 kB), while the app showed
the same videos as 20 seconds:

- the last full clip that morning was at 07:58:17 (20.0 s); from 08:00:31, most were 2.008 s;
- the cloud's own `period`, read at the same moment, also said 2 s, so it misled us at first;
- the bridge's code hadn't changed since 9 November, so the change was on Vicohome's side;
- some longer clips (9 to 18 s) still got through, which fits a race with the upload rather than a fixed limit.

Our reading, which fits all of the above but was never watched live: the cloud now lists a visit, with a playlist
that already ends, when only the first segment has been uploaded, and adds the rest later. We could not inspect a
live playlist, because the bridge's container isn't reachable from Home Assistant's SSH add-on, and we don't run
the cloud client outside it with the account's credentials.

What we built:
- **Bridge 0.3.5**: wait until a new visit's playlist is the same on two polls in a row, and about as long as
  `period`, for at most 5 minutes. Then check again 2, 5, 15 and 30 minutes after saving, and re-make the MP4
  under the same name if it grew. `period` now follows the cloud's newer value.
- **Bridge 0.3.6**: an hourly repair re-lists the last two days of visits and re-makes any kept clip the cloud now
  has more of.
- **Bridge 0.4.1**: a **Re-fetch clips** button (1 to 24 hours) does the same on demand.
- **un-subscribird**: records each clip's downloaded size, checks Home Assistant's copy again for 45 minutes, and
  re-downloads it when it grew (**Fetch clips again** on the Status page covers the last 48 hours). Unlabelled
  visits get new frames; labelled ones keep theirs.

The first visit after bridge 0.3.5 was installed came through as a full 20.0-second clip.

## The camera's local path: WebRTC and the microSD card

Battery and solar Vicohome cameras upload a short cloud clip when the link is poor, but keep the whole recording on
the microSD card. The app plays those over a WebRTC data channel on the local network. Bridge 0.4.0 uses the same
path to backfill clips the cloud only has part of (`receivedAllSlice` false).

- **Signalling**: `/device/getWebrtcTicket` returns a signalling server, port and websocket path. Messages carry a
  `messagePayload` that is either a JSON object or base64-encoded JSON.
- **Compact SDP**: the camera only starts its sender when the offer arrives on the compressed path (signalling
  `"version": "0.0.2"`), whose `sdp` is a compact JSON form, not plain SDP. `vico_sdp.py` converts a full offer to
  that form and the camera's compact answer back to full SDP for aiortc. The keys are `t`, `sid`, `sv`,
  `ice=[ufrag, pwd]`, `fp` (base64 fingerprint), `a` and `acp` (audio), `v` and `vcp` (video, with RTX folded in),
  and `dc` (data channel). Direction codes: 1 sendrecv, 2 recvonly, 3 sendonly, 0 inactive.
- **HTTP over the data channel ("SafeRtc")**: each request is wrapped as `{"action": "httpToDevice", ...}`, with
  headers `safe-rtc-root-url` and `safe-rtc-version: 1`. Commands and requests go out in frames that start
  `AB CD 18`. The camera answers in frames that start `AB CD <type>`: 0x12 a JSON status, 0x16 a body chunk,
  0x1a the end.
- **The card**: it is served only after a `stopLive` command and opening `/dc/rtcconnection/open`.
  - The list of recordings comes from `/library/newselectlibrary` sent over the tunnel with `fromSDCard: true`.
  - Recordings are plain MP4s at `/dc/video/mp4/<local start time>.mp4?sn=<serial>`, named by local start time
    with `:` replaced by `-`, plus the UTC offset.
- **Costs**:
  - The camera allows one live session at a time, so a card fetch briefly signs the phone app out.
  - A fetch also wakes the battery camera.
  - So the bridge fetches only genuinely incomplete clips: a few per repair, at most twice per visit, and at most
    once every `sd_fetch_hours`. `clip_source: cloud_only` turns this off entirely.
- **aiortc work-arounds**, following vicolocal:
  - the camera answers DTLS `setup:active`, so the bridge must be the SCTP server, or both sides send INIT and the
    channel never opens;
  - SRTP needs a bigger buffer than aiortc's default;
  - the ICE socket needs a larger receive buffer.
- **Networking**: the add-on runs on the host network for the peer-to-peer link, on a glibc base image so the
  WebRTC libraries install from wheels.

## What the camera's clips look like

Measured on real feeder clips; the dates are in the code comments where each number is used.

- **Length**: a full clip is about 20 seconds, ending sooner if the bird leaves (10 to 15 s is common).
- **Keyframes**: every 2.007 s. A few clips have no keyframe until about 4 s.
- **Dark wake-up**: the first ~1.5 s are dark or washed out while the camera wakes (settled by 1.5 s, measured
  5 November 2026). un-subscribird cuts the clip at the first keyframe at or after 2 s, with no re-encode, and
  leaves clips with a late keyframe whole.
- **Motion**: un-subscribird's frame picker scores movement. On 55 clips (5 November 2026), every clip with a bird
  scored at least 0.061, while 18 of 24 empty ones scored under 0.03, hence the 0.025 "nothing moved" threshold.
  A bird that sits still can score low, so a quiet clip's best frame goes to OWL-ViT first: it found the bird in
  every quiet clip that had one (scores 0.36 to 0.76) and nothing in the empty ones.

## Open questions

- Does the real playlist grow after `#EXT-X-ENDLIST`, and how long until it is complete? (Inferred, never watched.)
- How long does the cloud keep serving the full video behind a visit's signed URLs?
- Does the cloud name birds later, or never on an account without a subscription?
- The `receivedAllSlice` flag and the 2-second playlists both describe partial uploads: does the flag reliably
  turn true once the playlist is whole?

## Timeline

| Date | What |
|---|---|
| 2026-11-05 | Clip measurements: dark wake-up, keyframes, motion thresholds |
| 2026-11-06 | ha-vicohome-bridge 0.3.0 |
| 2026-11-08 | Retry when the cloud drops idle connections (0.3.1) |
| 2026-11-12 | From 08:00, the cloud lists visits before their video is uploaded; diagnosed the same day; bridge 0.3.5 waits for whole clips; un-subscribird re-fetches clips that grew |
| 2026-11-13 | Bridge 0.3.6 hourly repair; 0.4.0 microSD backfill over the camera's WebRTC data channel |
| 2026-11-14 | Bridge 0.4.1: Re-fetch clips button, `sd_only` clip source |

## Where it lives

- ha-vicohome-bridge: `vicohome_mqtt/app/vicohome.py` (cloud API), `clips.py` (HLS to MP4, re-checks),
  `sdfetch.py` (microSD over WebRTC), `vico_sdp.py` (compact SDP), `tests/e2e_fake_cloud.py` (fake cloud), and
  `vicohome_mqtt/CHANGELOG.md`.
- un-subscribird: `app/wbs/collector.py` (MQTT topics, clip download and re-fetch), `app/wbs/frames.py` (keyframes,
  the wake-up cut, motion scores), `app/wbs/config.py` (the measured thresholds).
