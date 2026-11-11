# Mockup generation brief (Muse) — hermes-wow-plugin

You are generating 4 UI concept mockup images for owner art-direction approval.
Success is measured ONLY by these files existing on disk with plausible sizes:

- `/Users/auston/Development Projects/hermes-wow-plugin/docs/mockups/01-guildhall-classic.png`
- `/Users/auston/Development Projects/hermes-wow-plugin/docs/mockups/02-guildhall-modern.png`
- `/Users/auston/Development Projects/hermes-wow-plugin/docs/mockups/03-guildhall-nous.png`
- `/Users/auston/Development Projects/hermes-wow-plugin/docs/mockups/04-forge-desktop-pane.png`

## Rules

- Use your image generation capability (Muse Image, `muse-image-1.0`). One image
  per file, 16:9 landscape, about 1600 px wide (or the model's native landscape
  size). If the model returns WebP, convert to PNG before saving.
- If you have no built-in image tool in this session: call
  `POST https://api.meta.ai/v1/responses` with body
  `{"model":"muse-image-1.0","input":"<prompt>","tools":[{"type":"image_generation"}]}`
  and the bearer key from `$MODEL_API_KEY` or `$META_API_KEY` in your
  environment. Never print or log the key. The image is base64 WebP in the
  `image_generation_call` output item's `result` field.
- After EACH image, append one line to
  `docs/mockups/PROGRESS.log`: `<file> <bytes> <ok | failed: reason>`.
- Do not create or modify any file outside `docs/mockups/`. Do not run git. Do
  not write any code except what is needed to request and save the images.
- When all four are done, write `docs/mockups/DONE.txt` listing the files and
  their sizes. If one fails twice, record the failure in PROGRESS.log and move
  on to the next image rather than stopping.

## Shared layout for images 01, 02, 03 (same layout, three art styles)

A World of Warcraft addon window shown as a straight-on UI screenshot mockup
(flat, no perspective, not a photograph), centered over a softly blurred fantasy
forest landscape at dusk. The window is wide and occupies most of the frame.

- Title bar text: `Guildhall — <Nous Research>`
- Left vertical tab rail with a small icon and label per tab, in this order:
  `Board`, `Events`, `Marks`, `Work Orders`, `Roster`, `Chronicle`, `Quests`.
  The `Board` tab is selected.
- Main area (the Board):
  - A pinned announcement card: `Raid night moved to Friday 8 PM` with a small
    byline `posted by Officer Witcheer`.
  - An upcoming-event card: `Deadmines guild run · Sat 7:00 PM` with three role
    chips `Tank 1/1`, `Healer 0/1`, `DPS 2/3` and a large `Sign up` button.
- Right column titled `Guild Marks`: a large balance `340 Marks` and three
  recent lines: `+15 Deadmines guild run`, `+5 Battleground with 3 guildmates`,
  `+10 Crafted work order`.
- Bottom status bar: `Synced with 12 guildmates · Discord bridge online`.

Keep text large, crisp and legible. Use few words. No watermarks, no logos of
real companies.

### 01-guildhall-classic.png — Style A, "Classic"

Authentic classic World of Warcraft default-interface look: dark stone and
bronze-gold beveled window border, parchment-textured content panels, gold serif
headings in a Friz-Quadrata-like typeface, red-and-gold fantasy buttons, a round
portrait-style emblem at the top-left corner of the window.

### 02-guildhall-modern.png — Style B, "Modern"

Modern minimalist dark addon interface in the spirit of ElvUI: near-black
translucent panels, 1-pixel borders, clean sans-serif type, a single teal accent
colour, class-coloured player names, compact rows, small rounded chips for the
role counts.

### 03-guildhall-nous.png — Style C, "Nous"

Deep midnight-blue and ivory palette, a subtle dithered retro-computing texture,
monospace headings, a thin gold caduceus (the staff of Hermes) emblem in the
title bar, crisp pixel-style icons. An elegant blend of retro terminal and
fantasy game interface.

## 04-forge-desktop-pane.png — the Hermes Desktop pane

A dark, modern desktop AI chat application window (flat design, soft purple-blue
accent). Left two-thirds: a chat conversation. The user message reads
`Build me a guild event board addon`. The assistant reply shows a short
checklist with green ticks: `API calls verified`, `Headless load test passed`,
`Installed to WoW: Forever`.

Right third: a docked side pane titled `Addon Forge` with these stacked
sections:

- `Game`: `World of Warcraft: Forever 1.60.1 · Interface 16001 · detected`
- `Addons`: rows `Guildhall — verified`, `ForgeCatcher — verified`
- `Check results`: three stat tiles `212 API calls verified`, `0 unknown`,
  `3 restricted (guarded)`, and a line `Headless load test: passed`
- `In-game errors: 0`
- `Discord bridge: online`
- A button row: `Check`, `Install`, `Sync`

Straight-on UI screenshot mockup, crisp legible text, no watermarks.
