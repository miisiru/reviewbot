# reviewbot

**English** | [한국어](README.ko.md)

A helper for moderating records on [theherta.com](https://theherta.com). It downloads a submitted Honkai: Star Rail clear
video and reads the following from the video:
- the team
- Eidolons
- Light Cone Superimposition
- the battle result
- Global Passive (account-wide effect) triggers

It then compares them with the submission and outputs **APPROVE / CHECK / REJECT** with a confidence score (%). No AI
(language model) is used for judging. It uses only video processing (OpenCV) and OCR (PaddleOCR PP-OCRv5).

A human presses Approve / Reject on the site. The tool only produces a verdict and its evidence. There is a command
that sends a decision through the API, but it does nothing unless you add `--yes`.

---

## 0. Read first

### 0-1. Running without Chrome DevTools

At first, an AI agent drove Chrome DevTools (browser automation) to open the moderation page, read the queue and expand
cards. The same work can now be done by calling the site's moderation API directly.

1. Log in to theherta.com in a browser (Discord). Copy that session's token **once** into `config.json`
   (see "2-5. Getting the token").
2. `python tools/mod_api.py queue` downloads the queue to `work/queue.json`.
3. `python tools/run_queue.py --limit 5` judges five items in turn (download → find character screens → judge).
   With `--fetch`, steps 1–2 are done in the same call.
4. Results go to `runs/<rev>/auto.json` and `work/results.jsonl`. With `--webhook question|review` they are also
   posted to Discord.

The access token expires after about an hour. If `config.json` also holds the refresh token, the Supabase URL and the
anon key, `mod_api.py` fetches a new token by itself and writes it back to `config.json`. The browser is needed only to
copy the token the first time.

> `mod_api.py` reproduces the requests the moderation page makes. It has not yet been tested against the live server.
> Check the output of `queue` first when you use it.

### 0-2. To the site operator: APIs that would help

Right now the tool has to borrow a login session token, which is awkward and fragile. With the following, automated
review could be attached safely and cleanly. Most important first.

1. **API keys for bots.** A long-lived key tied to a moderator account: expirable and revocable, with permissions limited
   to reading the queue, marking "in review" and leaving notes. This would remove the need to copy a Supabase session
   token out of the browser.
2. **A place to leave a "note" instead of a decision.** The bot attaches its verdict, confidence and evidence (video
   timestamp links, frame images) to the card, and a human looks at it and presses the button. For example
   `POST /api/mod/reviews/<id>/notes` with
   `{"verdict":"reject","confidence":92,"reasons":[...],"evidence":[{"t":229,"image_url":...}]}`.
3. **Game IDs in the submission data.** Characters and Light Cones as game IDs (AvatarID, EquipmentID) as well as English
   names. Today names are matched through the TextMap in 13 languages. Names written with different punctuation
   ("Dance Dance Dance" vs "Dance! Dance! Dance!") cause confusion.
4. **Priority and status on queue items.** Whether the item is in the supporter lane, how many times it has been
   re-reviewed, and whether the same video or the same UID is already on the site. Today a human has to find "video
   already on the site" rejections. For example `GET /api/mod/reviews/<id>/duplicates`.
5. **New-submission notifications.** A webhook or SSE for new items, so the queue does not have to be polled.
6. **An "in review" mark for bots.** It currently lasts one minute, shorter than a judgement (1–2 minutes). Allow a chosen
   duration (`{"ttl": 300}`) and show "bot" in the display name.
7. **A rejection-reason template API.** Accept reasons as template id + values + language instead of free text
   (`{"template":"superimp_mismatch","char":...,"submitted":5,"video":1,"lang":"zh"}`), and let the site write the
   text in that language.
8. **Documented rate limits.** How many calls per second are allowed.

---

## 1. How judging works now (the adopted method)

Each item goes through these steps:

```
prep.py      download (H.264 720p; every part of a multi-part Bilibili video; retry 480p → 1080p if the file is broken)
tabs.py      find where character screens (left menu) are shown, keep the Light Cone / Eidolon frames per character
auto_judge.py
  ├ judge.py  whose screen it is · Light Cone name · Superimposition · Eidolons (number of locks)
  ├ hud.py    HUD values at the moment the battle ends (Cycles Used / Remaining Action Value / Plight ⧗N | x)
  ├ gp.py     Global Passive trigger banners (Castorice "Sanctuary of Mooncocoon", Silver Wolf LV.999 "McAwolfee 999")
  └ UID · start time · confidence · verdict
```

### 1-1. Principles
- **The result screen is not used as evidence.** It can show the best record, which may differ from this run.
  Only the in-battle HUD values at the "Battle Over" moment are used.
- **OCR reads only small regions at known positions**, and the text is not interpreted. The closest of the submitted
  candidate names (TextMap in 13 languages) is chosen. Reading free text and guessing its meaning was too error-prone.
- **The OCR language model is chosen per video.** Two Light Cone screens are read with the Chinese, Korean, Latin,
  Russian and Thai models. The model whose output best matches the submitted names is used.
- **Unreadable is not "missing".** Anything that could not be read lowers the confidence and sends the item to CHECK.
  A "not shown" rejection is made only when the screen really could not be found.

### 1-2. Finding character screens (tabs.py)
- **Menu layout.** The six left-menu icons are searched at several sizes: Details, Light Cone, Traces, Relics,
  Eidolons, Info (language-independent).
  - No fixed aspect ratio is assumed. PC 16:9, wide phones, 4:3 tablets and pillarboxed videos all work.
  - The 5-row menu of Apocalyptic Shadow's "Checking Mode" is found too.
- **Active tab.** Decided by the share of pale-gold pixels in the icon. Even 0.3-second quick clicks are caught.
- **Scan.** The video is scanned at one frame per second to find menu sections, split over up to 6 processes. Only
  those sections are then examined closely.
- **Character changes.** A change in the shape of the header text (path / name) means a different character.
  - Characters switched while staying on the Eidolon tab are still separated.
  - Uploader watermarks are found as text that is always on screen, and left out of the comparison.

### 1-3. Whose screen is it (judge.py)
Tried in order; the first confident match wins.
1. The header-name OCR matches a submitted character (≥ 0.7, or ≥ 0.6 with a 0.3 lead over the next candidate).
2. On Eidolon screens, the **six Eidolon names** match one character: at least 2 lines, with the runner-up at most
   1/3 of the top.
   - The names differ per character and are listed in 13 languages in `tools/eidolon_names.json`.
   - This works even when a watermark covers the header.
3. The Light Cone title clearly matches only one character's submitted Light Cone (≥ 0.9, 0.25 ahead of the next).
4. The big name on the Details screen just before (taken from the last frame of that section).
   - A name line that matches no submitted character is the player's name, i.e. the Trailblazer.
   - Button text printed on every screen ("Character Guide" etc.) is not counted as a name.
5. If only one character is left, that one.

When two independent signals point to the same character, the identification is treated as certain and costs no
confidence.

### 1-4. Light Cone and Superimposition
- **Light Cone.** The panel title is compared with the submitted Light Cone's names in every language.
  - Below 0.7 is "Light Cone mismatch". 0.7–0.9 only lowers the confidence.
  - The path-name line (e.g. "记忆") is excluded from the title score, because it partly matches Light Cone names that
    contain that word.
- **Superimposition** is the number on the "Superimposition N / 중첩 N단계 / 叠影N阶 / 重畳ランクN …" line (a line
  similar to the wording in 12 languages).

### 1-5. Eidolons
- **Finding the nodes.** The six Eidolon nodes are found with circle detection and fitted to the matching node-layout
  reference: 16:9, left character column, or 4:3 tablet.
- **Locks.** Each node is scored against a lock-glyph template, and the maximum over the section is used. ≥ 0.6 is
  locked. 0.5–0.65 is "uncertain" and lowers the confidence.
- **Frame rate.** The Eidolon section is read at the video's native frame rate (up to 30 fps), because some videos
  open the Eidolon tab for only 0.3 seconds.
- **Frames used.**
  - Only frames where **the active menu tab is Eidolons** are used. The node ring of the Traces screen can fit the
    Eidolon layout.
  - The first 0.1 s after the character name changes is skipped. The header changes first and the node images follow
    later.
- **What counts as unlocked.**
  - A red "!" on the Eidolons menu row (can be activated) is not counted as unlocked.
  - Zero locks (E6) is trusted only with at least two Eidolon-tab frames, or when at least five Eidolon names were read.

### 1-6. Battle result (hud.py)
The 40 s before the final showcase (200 s if that is not enough) are read at one frame per second. The values from the
last moment the HUD was visible are used.

| Mode | Value read | Check |
|---|---|---|
| Anomaly Arbitration | "Cycles Used" badge number, top right (3 preprocessings × majority of the last 10 frames) | 0 for 0-Cycle, otherwise equal to the submitted count. The subcategory (0-Cycle / full stars / Clear) is checked too |
| Anomaly Arbitration, Plight | the "⧗N \| x" cell in the action order on the left | Action Value used = 500 − (N × 100 + x) must equal the submitted value |
| Apocalyptic Shadow | "Remaining Action Value", top right | score = 2000 + Remaining Action Value (boss assumed killed). 0 AV ↔ 2000 |

In the Plight cell, OCR reads the hourglass as "2" and the separator as "1", so the text alone cannot be split
("20116" = ⧗0 \| 16). The white glyphs are therefore laid out and matched against the pattern "hourglass · one digit ·
thin vertical bar · 1–3 digits". N and x are then cropped and read separately. Action-value numbers in character cells
have no separator, so they never match.

### 1-7. Global Passive (gp.py)
- **Banners.**
  - The whole battle is scanned at four frames per second, because a banner can last only 0.5 s.
  - Only frames with "a row of three or more large white glyphs" in the right-middle band are OCR'd, and the text is
    matched against the banner names in 12 languages.
  - For Silver Wolf LV.999, the "…hacked into the game…" notice at the top is also checked once per second.
- **Flags.**
  - It is a problem if a flag is in the submission but nothing triggered, or something triggered that is not in the
    flags.
  - The effect can trigger even when the character is not in the team (account-wide effect).
  - Castorice (revive) is the exception. If it is in the submission but no banner is found, the item goes to **CHECK**,
    whether it really was not used or the tool missed it (CHECK even with other problems; they are still listed).

### 1-8. Other checks
- **UID:** OCR of the bottom-left field on character screens. Unreadable lowers the confidence.
- **Start time:** the battle HUD must appear within 62 s (1 minute) of the playback start (the link's `t=`), for single-run
  submissions.
- **Multi-part Bilibili videos:** for videos split into parts (P1 run + P2 settings, etc.), character screens are
  searched in every part.

### 1-9. Confidence and verdict
Confidence = 100 − deductions (`CONF` in `tools/auto_judge.py`). The same video always gives the same value.

| Deduction | Reason |
|---|---|
| −100 | the video file does not decode to the end |
| −30 | HUD value at the end of the battle not read |
| −20 | Superimposition not read / Eidolons not read |
| −15 | HUD read agreement below 50% / "not shown" while other characters' screens were also missed |
| −10 | UID not read / battle not seen within 1 minute of the playback start |
| −5 | Eidolons read from a single frame (or two blurry ones) / each uncertain node / an activatable node / HUD agreement 50–80% |
| −4 | identified by inference (elimination, previous screen) |
| −3 | Light Cone name match 0.7–0.9 |
| −2 | identified weakly by a single signal |

- **REJECT:** anything differs from the submission (all reasons are listed)
- **CHECK:** confidence 80 or below, or something could not be read; a human should look
- **APPROVE:** otherwise

### 1-10. Validation
Tested on 24 items that I had judged by eye (20 approved, 4 rejected):
- **Approved 20:** APPROVE 20 (confidence 81–100%).
- **Rejected 4:** REJECT 4, with the same reasons. Light Cone not shown · wrong Light Cone · Superimposition mismatch ·
  Action Value mismatch.
- **Time per item:** 35–160 s to judge (median about 1 minute), plus about 20 s to find character screens, plus the
  download.

### 1-11. Not done yet
- Pure Fiction score and cycles
- Combined runs (several sides):
  - The builds of all sides are checked, but HUD values and the start time only for the first side.
  - Whether each side's boss matches is not checked.
- The rule that each run needs its own `t=` when one video contains several runs
- Apocalyptic Shadow runs where the boss was not killed (score from boss HP ratio)
- Checking whether the same video is already on the site
- Telling apart "Light Cone / Eidolons shown only as an external build card"

---

## 2. Setup

### 2-1. Requirements
- Python 3.11 or newer (used with 3.14)
- Node.js (yt-dlp uses it for YouTube; also for `build_eidolon_names.mjs`)
- Disk: 100–300 MB per video

```bash
pip install -r requirements.txt
# to use the GPU on Windows: pip uninstall onnxruntime && pip install onnxruntime-directml
python tools/get_models.py          # OCR models (about 125 MB) → auto/models/
```

ffmpeg comes from `imageio-ffmpeg`. To use another one, set the environment variable `FFMPEG`. For yt-dlp, set `YTDLP`
(`tools/paths.py`).

### 2-2. Game data
Matching character, Light Cone and Eidolon names in 13 languages needs the TextMap from
[Dimbreath TurnBasedGameData](https://github.com/DimbreathBot/TurnBasedGameData). It is large, so fetch only the folders
you need.

```bash
git clone --filter=blob:none --sparse https://github.com/DimbreathBot/TurnBasedGameData data/TurnBasedGameData
cd data/TurnBasedGameData && git sparse-checkout set TextMap ExcelOutput && cd ../..
# the tools look at data/TextMap and data/ExcelOutput. If you put them elsewhere, use environment variables:
#   HSR_TEXTMAP=data/TurnBasedGameData/TextMap  HSR_EXCEL=data/TurnBasedGameData/ExcelOutput
```

When new characters are released, rebuild the Eidolon name table:
```bash
node tools/build_eidolon_names.mjs   # → tools/eidolon_names.json
```

### 2-3. config.json
Copy `config.example.json` to `config.json` and fill it in. **This file is never committed** (.gitignore).

| Key | Used by |
|---|---|
| `discord_webhook` | review reports (`tools/notify.py`, `run_queue.py --webhook review`) |
| `question_webhook` | questions and test results (`tools/ask.py`, `run_queue.py --webhook question`) |
| `mod_token` · `mod_refresh_token` · `supabase_url` · `supabase_anon_key` | site API (`tools/mod_api.py`) |

### 2-4. Folders
```
tools/        the tools (see "4. Files")
auto/         OCR wrapper (ocr.py) · name lookup (names.py) · models/ (downloaded OCR models)
data/         game data (not committed)
runs/<rev>/   per item: video · intermediate results · verdict (not committed)
work/         queue · collected results (not committed)
```

### 2-5. Getting the token (without DevTools automation)
The site uses a Supabase session after Discord login. Copy it from the browser once:
1. Log in to theherta.com with a moderator account in a browser.
2. Open the value named `sb-<project>-auth-token`:
   - Press F12 → Application → Local Storage (or Cookies) → `https://theherta.com`.
   - Put its `access_token` into `mod_token` and its `refresh_token` into `mod_refresh_token`.
3. From `<project>`, make `supabase_url` = `https://<project>.supabase.co`.
4. Press F12 → Network and open any request to `supabase.co`. Put the value of its `apikey` request header into
   `supabase_anon_key` (it is a public key).

From then on, `mod_api.py` uses the refresh token to get a new token whenever the old one expires, and writes it to
`config.json`. For one-off use you can put just the access token into the environment variable `THEHERTA_TOKEN` (no
refresh).

---

## 3. Running

### 3-1. Through the queue
```bash
python tools/run_queue.py --fetch --limit 5                 # fetch the queue, judge 5 items nobody has claimed
python tools/run_queue.py --fetch --limit 5 --claim         # mark "in review" before judging
python tools/run_queue.py rev_abc123 --webhook question     # one item, post the result to the question webhook
```
The Discord report is an embed laid out like the Discord bot's submission embed (color = verdict: green APPROVE,
red REJECT, amber CHECK; the title links to the review page). Example terminal output:
```
REJECT · 100% confidence
**Author:** …
**Season:** 3.6
**Status:** Not decided (human)
[❌ Problems]
• Cerydra Light Cone mismatch (submitted 'Dance! Dance! Dance!', video '… 황금 피가 새긴 시대 …')
• Cerydra Superimposition mismatch (submitted S5, video S1)
[MOC | Gepard | 0-Cycle | 0 Cycles | 5L / 1S]
✅ **Firefly** (E2S1) — *Whereabouts Should Dreams Rest*
└ LC [3:50](https://youtu.be/…?t=230) · E [4:01](https://youtu.be/…?t=241)
❌ **Cerydra** (E0S5) — *Dance! Dance! Dance!*
└ LC [4:10](https://youtu.be/…?t=250) · E [4:20](https://youtu.be/…?t=260) · **video LC '… 황금 피가 새긴 시대 …'** · **video S1**
[Battle (HUD)]
• Cycles (HUD): 0 at Battle Over
[Links]
[Video](https://youtu.be/…) · [Showcase 3:49](https://youtu.be/…&t=229) · [Review](https://theherta.com/mod?review=rev_…)
ID: run_1nl1xos  •  Review ID: rev_…
```

### 3-2. Step by step
```bash
python tools/mod_api.py queue                 # → work/queue.json
HQ_QUEUE=work/queue.json python tools/prep.py rev_abc123
python tools/tabs.py rev_abc123 0             # once per part (0, 1, …)
python tools/auto_judge.py rev_abc123         # → runs/rev_abc123/auto.json
python tools/auto_judge.py rev_abc123 --reuse # re-run only the build reading (reuses HUD / Global Passive results from auto_cache.json)
```

### 3-3. Sending a decision to the site
```bash
python tools/mod_api.py decide rev_abc123 approve            # only shows what would be sent
python tools/mod_api.py decide rev_abc123 approve --yes      # actually sends it
python tools/mod_api.py decide rev_abc123 reject "Hyacine Light Cone Superimposition not shown" --yes
```
Rejection reasons follow the forms in `reject_templates.md`.
- Write them in the game language of the video: Korean, English, Chinese or Japanese, otherwise English.
- Keep them on one line. Join several problems with " / ".

### 3-4. Working with an AI agent (the earlier method)
In this method:
- An agent such as Claude Code opened the moderation page through Chrome DevTools.
- It looked at the sheets made by `tools/run_item.py` the way a person would, and judged:
  - Light Cone / Eidolon frames `tabs<i>/sheet.jpg`
  - 4 fps Global Passive sheets `gpf<i>_*/`
  - a whole-video overview `ov<i>.jpg`

`auto_judge.py` now gives the same verdicts without AI. The sheet tools are for a human checking the evidence scenes
directly: `scan_sheet.sh`, `gp_fast.sh`, `overview.sh`, `hdr_strip.sh`, `top_sheet.sh`, `frames.py` and others.

---

## 4. Files

| File | What it does |
|---|---|
| `tools/paths.py` | paths · finds ffmpeg and yt-dlp (overridable by environment variables) |
| `tools/mod_api.py` | site moderation API (queue · in-review mark · decision) |
| `tools/run_queue.py` | several queue items: download → find screens → judge |
| `tools/prep.py` | download videos (parts · retry other qualities) |
| `tools/tabs.py` | character-screen sections · Light Cone / Eidolon frames |
| `tools/judge.py` | whose screen · Light Cone · Superimposition · Eidolons |
| `tools/hud.py` | HUD values at the end of the battle |
| `tools/gp.py` | Global Passive banners |
| `tools/auto_judge.py` | combines everything into a verdict and confidence |
| `tools/build_eidolon_names.mjs` | builds the Eidolon name table |
| `tools/get_models.py` | downloads the OCR models |
| `tools/ask.py` · `tools/notify.py` · `tools/webhook.py` | Discord webhooks |
| `tools/run_item.py` · `confidence.py` · `*.sh` · `frames.py` … | sheets for a human (or AI) to look at |
| `auto/ocr.py` | RapidOCR + per-language PP-OCRv5 recognition models. GPU (DirectML) only for build reading, CPU for the rest |
| `auto/names.py` | English game name → TextMap names in each language |
| `reject_templates.md` | rejection-reason templates per language (written in Korean) |

## 5. Sources and licences
- OCR models: ONNX conversion [monkt/paddleocr-onnx](https://huggingface.co/monkt/paddleocr-onnx) of
  [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-OCRv5 (Apache-2.0)
- Game text: Honkai: Star Rail © HoYoverse, from the [Dimbreath](https://github.com/DimbreathBot/TurnBasedGameData) dump
