---
title: Browser-assisted Gemini/Flow mode
description: Generate short videos by driving your OWN logged-in Chromium profile against your existing Gemini/Flow/Omni subscription — no Gemini/Veo API billing. Conservative by design; stops for a human on any login, CAPTCHA, limit, or refusal.
sidebar_label: Browser-assisted Gemini/Flow
sidebar_position: 8
---

# Browser-assisted Gemini/Flow mode

The `social_video_factory` package can generate short ("brainrot") videos by
driving **your own logged-in local Chromium profile** against your existing
**Gemini / Flow / Omni** subscription. This is the `browser_flow` generation
mode.

Because the browser is the real generation engine, this mode:

- **Uses YOUR logged-in Chromium profile** — a persistent profile directory
  (`SOCIAL_FACTORY_BROWSER_PROFILE_DIR`, default
  `.social_video_factory/chromium_profile`). You log in once, manually, and the
  session persists.
- **Avoids Gemini API calls** — there is no Veo / Gemini API usage and **no API
  billing**. It clicks the web UI you already pay for.
- **Is LESS STABLE than API mode** — web UIs change without notice, so a
  selector that worked yesterday may miss today. See
  [When the web UI changes](#when-the-web-ui-changes) for how to fix that
  yourself.

:::warning Conservative by design
This mode will **never** bypass CAPTCHA, login, rate limits, or safety
refusals. On any such screen it stops, saves a screenshot, and marks the job
`needs_human` — it never tries to work around the block. See
[What it will NOT do](#what-it-will-not-do).
:::

## Requirements

- **Playwright** is required. It is **lazy-installed on first browser use** via
  `tools/lazy_deps.py`, so you do not add it to your dependencies manually.
- The **Chromium binary** is not fetched by pip — install it once with:

  ```bash
  python -m playwright install chromium
  ```

## Setup and usage

### 1. Log in (one time, manual)

Opens the persistent Chromium profile at your Flow/Gemini URL so you can log in
by hand. The session is saved into the profile dir for later runs.

```bash
python -m social_video_factory.cli browser-login
```

Login is **always manual** — the tool only opens the window; it never types
credentials or attempts to bypass a login screen.

### 2. Generate a single video

Create a job in `browser_flow` mode (this runs the creative stages and saves the
prompt, then stops), then run the browser worker for that job:

```bash
python -m social_video_factory.cli generate-one \
  --template dancing_cat \
  --topic "orange cat disco kitchen" \
  --generation-mode browser_flow

python -m social_video_factory.cli browser-generate --job-id <job_id>
```

On success the job continues through import → review → render (9:16) → captions
and reaches `awaiting_approval`. Publishing always stays manual.

### 3. Run a queue

Process pending `browser_flow` jobs one at a time, pausing between them and
stopping on the first hard stop, rate-limit, or error:

```bash
python -m social_video_factory.cli browser-run-queue --limit 5
```

### Manual recovery

If you completed a generation by hand in the open window (after a manual pause),
import the newest downloaded clip and continue the pipeline:

```bash
python -m social_video_factory.cli import-latest-browser-download --job-id <job_id>
```

## Local rate limits (always enforced)

Conservative **local** limits are enforced on every generation **even if the
website would allow more**. They are a good-citizen control, not a website
limit, and cannot be bypassed by the worker.

| Environment variable | Default | Meaning |
|---|---|---|
| `SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR` | `3` | Max generations in any rolling hour (`0` disables). |
| `SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY` | `20` | Max generations in any rolling day (`0` disables). |
| `SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS` | `180` | Minimum gap between generations (`0` disables). |
| `SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY` | `10` | Prompt for human confirmation before the (N+1)th, (2N+1)th, … generation (never before the first; `0` disables). |

When a cap is hit the worker stops cleanly as "rate limited" (not
`needs_human`) — just try again later.

## Other configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `SOCIAL_FACTORY_BROWSER_PROFILE_DIR` | `.social_video_factory/chromium_profile` | Persistent Chromium profile (your logged-in session). |
| `SOCIAL_FACTORY_BROWSER_EXECUTABLE_PATH` | _(empty)_ | Explicit Chromium path; empty uses Playwright's bundled build. |
| `SOCIAL_FACTORY_BROWSER_HEADLESS` | `false` | Headed by default — the real generation engine wants a visible browser. |
| `SOCIAL_FACTORY_FLOW_URL` | _(empty)_ | The Flow URL to open for `--target flow`. |
| `SOCIAL_FACTORY_GEMINI_URL` | _(empty)_ | The Gemini URL to open for `--target gemini`. |
| `SOCIAL_FACTORY_BROWSER_DOWNLOAD_DIR` | `.social_video_factory/media/browser_downloads` | Where generated clips are downloaded. |
| `SOCIAL_FACTORY_SELECTORS_FILE` | _(empty)_ | Path to your own selector overrides; empty uses the bundled example. |
| `SOCIAL_FACTORY_AUTO_PUBLISH` | `false` | Publishing always stays manual + approved; never bypassed. |

## When the web UI changes

Because web UIs drift, selector resolution is **layered** and tried in order for
each action:

1. **Configured** CSS / text selectors from the YAML.
2. **Accessible** role / label queries (`get_by_role` / `get_by_label`).
3. **Visible text** (e.g. a button labelled "Generate").
4. **Manual pause** — the worker saves a screenshot, prints exactly what you
   need to do (and where downloads land), and waits while you finish that step
   in the open window.

To adapt to a UI change, edit the bundled
`social_video_factory/browser_selectors.example.yaml`, **or** point
`SOCIAL_FACTORY_SELECTORS_FILE` at your own copy. Keys cover both `flow` and
`gemini` targets (`prompt_box`, `submit`, `generating_indicator`, `download`,
`export_mp4`, `result_video`) plus the `hard_stops` text patterns.

## Hermes tools

Four tools are registered under the `social_video_factory` toolset:

| Tool | What it does |
|---|---|
| `social_video_factory_browser_login` | Returns login **guidance** (the command + resolved URL); login itself is manual — it never opens a browser or bypasses login. |
| `social_video_factory_browser_generate_job` | Runs the browser worker for one existing job, then continues the pipeline. |
| `social_video_factory_browser_run_queue` | Processes pending `browser_flow` jobs one at a time, stopping on any hard stop. |
| `social_video_factory_import_latest_browser_download` | Imports the newest downloaded clip for a job (manual-recovery path). |

## What it will NOT do

This mode is deliberately conservative and includes **no** bypass logic of any
kind:

- **No stealth / anti-detection / fingerprint spoofing** — it launches a normal
  persistent Chromium with no automation-evasion flags.
- **No CAPTCHA solving.**
- **No proxy or account rotation.**
- **No usage-limit bypass** — local limits are always enforced, and on a website
  limit it stops and asks for a human.
- **No scraping or engagement automation** (no liking / commenting / following).
- **No auto-publish** — finished videos stop at `awaiting_approval`.
- **Secrets are never logged** — cookies, tokens, and other secrets are redacted
  from all screenshots, HTML snapshots, and stage logs.

On any login, CAPTCHA, suspicious-activity, rate/usage-limit, upgrade, payment,
safety/content-policy refusal, verification, recovery, or consent screen, the
worker screenshots the page, marks the job `needs_human` with a reason, closes
the browser, and exits cleanly.
