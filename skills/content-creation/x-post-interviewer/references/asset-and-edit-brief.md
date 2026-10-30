# Asset Director + Edit Brief Protocol

Run this AFTER the post text is approved. The post decides which assets are needed, not the other way round.
Never ask for an asset that does not prove a specific claim in the post.

## Step 1: Asset list (one block per asset)

For every asset output exactly this block:

```
ASSET A1  [screenshot | photo | screen-recording | camera-video | audio]
Proves:      the exact claim in the post this backs up (quote the line)
Capture:     step-by-step, literal (what to open, what to click, what to have on screen)
Frame:       orientation, aspect ratio, device, zoom level, theme (dark/light)
Duration:    (video only) target seconds, and what happens second by second
Must show:   the 1-3 details the viewer must be able to read
Must hide:   secrets and noise to remove BEFORE capturing
Filename:    dayNN_A1_short-name.ext
Fallback:    what to capture instead if this is impossible today
```

### Mandatory safety sweep (include in every asset list)
Before any capture, close or hide: .env files, API keys, tokens, webhook URLs, private repo URLs if the repo is
private, email addresses, browser tabs, notifications, bookmarks bar, other people's names or faces. If a minor
(a "kid", a student, a tester) appears in any photo, video, name, or screenshot, STOP and ask the user whether
they have explicit guardian consent and whether the post should show them at all. Default recommendation: do
not show faces or full names of minors; show the product, the numbers, or the user's own hands/screen instead.

### Capture defaults (adjust to the platform skill)
- Screenshots: capture at the largest sensible window, crop tight on what matters, one idea per image.
  Terminals and editors: dark theme, font size 16pt+, so text is readable on a phone.
- Screen recordings: 1080p or higher, 10-30 s, no cursor wandering, pause 1 s on the key result.
- Camera video (phone): vertical 9:16 unless the platform skill says otherwise, window light in front of you,
  phone at eye level, one take, say the hook line in the first 2 seconds.
- Photos: real over staged. Whiteboard, notebook, desk setup with the timeline visible beat stock-looking shots.
- Always capture 20-30% more than needed (extra 5 s head and tail on video).

### Asset recipes for a build-in-public day-N post (offer only those that match what the interview surfaced)
1. The proof screenshot: the single number or output that shows progress (test result, first generated output,
   dashboard count).
2. The timeline/plan screenshot: the doc showing done / not done, with the not-done items visible. Honesty about
   the gap is what makes day-1 posts credible.
3. The repo tree screenshot: folder structure with the docs files visible (no secrets).
4. The 15-second screen recording: the thing doing its job once, start to finish.
5. The face-or-hands clip: you saying the hook line, or your hands on the keyboard with the result on screen.
6. The decision card: a simple text-on-background graphic with the one decision and its tradeoff.

## Step 2: Edit brief

Output two things, filled in from the real assets and real post text (no placeholders left):

### 2a. Universal prompt for any AI editing platform (paste-ready)

```
Create a [duration]-second [aspect ratio] [platform] video/image from the attached files.

GOAL: [one sentence: what the viewer should feel or do]
HOOK (first 2 s): [exact on-screen text + what is visible]
STRUCTURE:
  0:00-0:02  [asset ID] [what shows] [caption text]
  0:02-0:08  [asset ID] ...
  ...
  END        [asset ID or end card] [final caption / CTA text]
CAPTIONS: burned-in, [font style], high contrast, max 6 words per line, matching this transcript: "[...]"
PACING: cut every 1.5-3 s; trim silence; keep the key result on screen at least 1.5 s
ZOOM/CROP: punch in on [region] at [time] so text is readable on a phone
AUDIO: [keep original | add subtle background music, low | none]; normalise loudness
STYLE: [dark/clean/minimal]; one accent colour [hex]; no stock footage; no emojis; no logos except [x]
DO NOT: add effects not listed, change my words, show any content outside the crop, speed up screen text
EXPORT: [resolution], [aspect ratio], H.264 MP4, under [size] MB; also export a [1:1 or 16:9] version and a
        1280x720 thumbnail/poster frame from [timestamp]
```

### 2b. Same plan as MCP tool steps (for FFmpeg-style local MCP servers)

Express the edit as an ordered list of atomic operations, one tool call each, so a small local model can follow it:
`1 trim clip -> 2 crop/scale -> 3 concat -> 4 burn subtitles from .srt -> 5 normalise audio -> 6 export -> 7 extract poster frame`.
Also output the .srt text (timed captions) so the user does not depend on auto-transcription.
Give absolute-path placeholders only for folders the user must fill in (e.g. FREE_VIDEO_EDIT_ROOT).

## Step 3: Verify before posting
Checklist the user must tick: readable on a phone at arm's length; no secrets visible on any frame (scrub the
timeline frame by frame at key moments); captions match speech; first 2 s makes sense with sound off; file plays
in the platform's composer before scheduling.

## Editing tool notes (verify current status before installing; third-party, unaudited)
Read tools.md in this folder for the options and honest tradeoffs.
