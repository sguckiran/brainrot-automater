# social_video_factory

A self-contained short-video ("brainrot") factory. It turns a topic into a
finished 9:16 video and — optionally — posts it to Instagram and TikTok, fully
unattended, by driving **your own logged-in browser** against your existing
Google Flow subscription. No generation-API billing; the browser is the engine.

It is **conservative by design**: it never bypasses logins, CAPTCHAs, rate
limits, or safety screens. When it hits one, it stops and asks for a human.

---

## What it does

```
topic ─▶ idea ─▶ script ─▶ Flow prompt
                              │
                  (browser_flow) drives your logged-in Chrome on Google Flow
                              ▼
        generate ─▶ download ─▶ import ─▶ probe(ffprobe) ─▶ review
                              ▼
              render 9:16 (ffmpeg) ─▶ captions ─▶ awaiting_approval
                              ▼
                 [opt-in] publish ─▶ Instagram + TikTok
```

Each job is a JSON record under `.social_video_factory/jobs/` that advances
through these stages (`created → idea → … → published`), so a crash leaves a
resumable, auditable trail.

### Generation modes (`--generation-mode`)
| Mode | Status |
|---|---|
| `browser_flow` | **Primary.** Drives your logged-in Chrome on Google Flow. |
| `mock` | Fully working; fabricates a clip for end-to-end testing without a browser. |
| `flow_import` / `assisted_flow` | Light stubs. |
| `api_veo` | Disabled in this build (raises a clear error). |

---

## Safety posture (non-negotiable)

This tool **does not** and **will not**:
- solve CAPTCHAs, use stealth/anti-detection, spoof fingerprints, or rotate
  proxies/accounts;
- bypass login, usage limits, subscription/payment, or safety/content refusals;
- scrape feeds or automate likes/comments/follows.

Instead it drives **your own** authenticated session, enforces **local
conservative rate limits**, and stops on any blocking screen (a "hard stop") to
hand control to a human. Credentials and tokens are never logged. Publishing is
**off by default** and only happens when you explicitly enable it. TikTok's
AI-generated-content disclosure is toggled on automatically.

---

## Requirements

- Python 3.12 (managed via `uv`), `ffmpeg` + `ffprobe`
- A Chromium-family browser. On modern Linux the project drives **Google Chrome**
  via `SOCIAL_FACTORY_BROWSER_EXECUTABLE_PATH`; Playwright is used as the driver
  (`pip install playwright`). Playwright's bundled Chromium also works where
  supported.
- For publishing/alerts: a Telegram bot (optional).

## Quick start (local)

```bash
# 1. one-time: log into Google Flow in your persistent profile
python -m social_video_factory.cli browser-login --target flow

# 2. generate a video end-to-end via the browser
python -m social_video_factory.cli generate-one \
  --template dancing_cat --topic "orange cat disco kitchen" \
  --generation-mode browser_flow
python -m social_video_factory.cli browser-generate --job-id <job_id>

# 3. (optional) publish a finished job
python -m social_video_factory.cli publish-job --job-id <job_id> --platforms instagram,tiktok

# preflight check of everything that must be configured
python -m social_video_factory.cli doctor
```

`mock` mode needs no browser and is great for testing the pipeline:
```bash
python -m social_video_factory.cli generate-one --template dancing_cat --topic "test" --generation-mode mock
```

---

## CLI reference

`python -m social_video_factory.cli <command>` (or `svf <command>` after the WSL
setup installs the `svf` launcher).

| Command | Purpose |
|---|---|
| `generate-one --template T --topic S [--generation-mode M]` | Create + run a job. `mock` runs to `awaiting_approval`; browser modes stop after saving the prompt. |
| `browser-login --target flow\|gemini\|instagram\|tiktok` | Open a **normal** (non-automated) Chrome on the persistent profile so you log in by hand once; the session is reused later. |
| `browser-generate --job-id ID` | Run the conservative browser worker for a prepared job, then continue the pipeline. |
| `browser-run-queue [--limit N]` | Process pending `browser_flow` jobs one by one; stops on any hard stop. |
| `import-latest-browser-download --job-id ID` | Manual recovery: import the newest downloaded clip and finish the pipeline. |
| `publish-job --job-id ID [--platforms ...]` | Publish a rendered job to Instagram/TikTok. |
| `autopilot [--target-pending N] [--per-run-limit N]` | One unattended pass: top up the queue from topics → generate → render → caption → (auto-)publish → alert on stalls. The scheduler calls this. |
| `doctor` | Preflight report: deps, logged-in profiles, creds, config, unattended flags. |
| `notify-test` | Send a test Telegram/Discord alert. |
| `list-jobs` / `show-job --job-id ID` | Inspect jobs. |

A matching set of Hermes agent tools is registered in
`tools/social_video_factory_tool.py` (browser login guidance, generate-job,
run-queue, import-latest), so the agent can drive the same flow non-interactively.

---

## Configuration

### Publishing + autopilot — `~/.hermes/config.yaml`
```yaml
social_video_factory:
  publishing:
    enabled: false              # master switch; off by default
    auto_after_generation: false # generate AND auto-publish unattended
    platforms: [instagram, tiktok]
  autopilot:
    templates: [dancing_cat]
    topics: ["orange cat disco kitchen", "skater dog city night"]  # empty = idle
    target_pending: 3           # how many jobs to keep queued
    per_run_limit: 1            # jobs generated per autopilot pass
  rendering:
    burn_text_overlays: false   # burn hook/subtitles/watermark into the render
```

### Runtime — environment variables
All optional; sensible defaults shown.

| Variable | Default | Meaning |
|---|---|---|
| `SOCIAL_FACTORY_DATA_DIR` | `.social_video_factory` | Runtime data root (jobs, profiles, media, state, logs). |
| `SOCIAL_FACTORY_FLOW_URL` / `_GEMINI_URL` | — | Target URL(s). |
| `SOCIAL_FACTORY_BROWSER_EXECUTABLE_PATH` | bundled | e.g. `/usr/bin/google-chrome-stable`. |
| `SOCIAL_FACTORY_BROWSER_HEADLESS` | `false` | Headed (use Xvfb to keep it invisible). |
| `SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR` | `3` | Local hourly cap. |
| `SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY` | `20` | Local daily cap. |
| `SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS` | `180` | Min gap between generations. |
| `SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY` | `10` | Periodic human confirm; **set `0` for unattended**. |
| `SOCIAL_FACTORY_SUPERVISED_PAUSE` | `false` | Hold the browser open on a human-solvable challenge and wait for you to clear it. |
| `SOCIAL_FACTORY_SUPERVISED_PAUSE_TIMEOUT` | `600` | How long to hold (seconds). |
| `SOCIAL_FACTORY_NOVNC_URL` | — | Live-view link included in alerts. |
| `SOCIAL_FACTORY_SELECTORS_FILE` | bundled example | Override the Flow/Gemini selector map. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_HOME_CHANNEL` | — | Alert channel (same as the Hermes gateway). |
| `SOCIAL_FACTORY_DISCORD_WEBHOOK` | — | Optional Discord alert webhook. |

### Selectors
The web UI changes often. `browser_selectors.example.yaml` is an editable,
layered selector map (configured CSS → accessible role/label → visible text →
manual pause) plus the `hard_stops` text patterns. Flow specifically is handled
by the more robust `browser/flow_ui.py` adapter.

---

## Autonomous mode (headless VM / WSL2)

The factory can run **fully unattended and invisible** on a Linux VM — including
WSL2 on Windows — driving a real **headed** Chrome on a virtual display (Xvfb),
so nothing appears on your physical screen. When it hits a CAPTCHA/verification
it pings you and shows you the **live browser via a noVNC link** to solve it; the
run then continues.

Scripts live in `scripts/social_video_factory/`:

| Script / unit | Purpose |
|---|---|
| `setup_wsl.sh` | Provision a WSL2 Ubuntu (apt deps, `uv`, minimal venv, Google Chrome). |
| `setup_vm.sh` | Equivalent for a generic Ubuntu VM (systemd units + Xvfb + noVNC). |
| `setup_display_wsl.sh` | systemd units for the invisible display: `svf-xvfb`, `svf-x11vnc`, `svf-novnc`. |
| `configure_wsl.sh` | Write the env file + a Hermes config scaffold (never clobbers an existing config). |
| `run_autopilot_wsl.sh` | One pass; waits for the virtual display, then runs `autopilot`. Triggered hourly/20-min by Windows Task Scheduler. |
| `social-video-factory.env.example` | Env-file template (with the unattended flags pre-set). |
| `svf` | Convenience launcher installed to `/usr/local/bin/svf`. |

**Setup outline (WSL2):**
```bash
SVF_REPO_DIR=/path/to/repo bash scripts/social_video_factory/setup_wsl.sh
wsl -d Ubuntu -u root -- bash -s < scripts/social_video_factory/setup_display_wsl.sh
wsl -d Ubuntu -- bash -s < scripts/social_video_factory/configure_wsl.sh
# edit ~/svf-autopilot.env (Telegram token, FLOW_URL) and ~/.hermes/config.yaml (topics + publishing)
# seed logins once via the noVNC link:  svf browser-login --target flow|instagram|tiktok
svf doctor          # confirm green
```
Then a Windows Task Scheduler task (`social_video_factory_autopilot`) runs
`run_autopilot_wsl.sh` every 20 minutes (3×/hour). WSLg is disabled
(`%USERPROFILE%\.wslconfig` → `guiApplications=false`) so Xvfb can own the
display.

> **Note (WSL):** WSL needs no terminal kept open — each scheduled wake
> cold-starts the distro. The task runs while the PC is on and you're logged
> into Windows (locked screen is fine); it survives reboots and resumes
> automatically. Sessions on the platforms eventually expire and need a quick
> re-login via noVNC.

---

## Project layout

```
social_video_factory/
  cli.py            fire CLI (entry: python -m social_video_factory.cli)
  config.py         env + Hermes-config accessors, path helpers
  models.py         GenerationMode, JobStatus, Job
  store.py          atomic JSON job store
  ideas/script/prompt_build.py   creative stages
  concepts.py       deterministic topic→concept expansion
  topics.py         autopilot topic rotation (persisted cursor)
  media.py          import + ffprobe + sidecar
  render.py         ffmpeg 9:16 render
  captions.py       TikTok/Instagram caption text
  review.py         VLM/mock review
  rate_limit.py     local per-hour/day/min-gap/human-confirm limiter
  notify.py         Telegram/Discord alerts
  autopilot.py      one unattended pass (top-up → queue → alert)
  manual_login.py   non-automated Chrome login (so platforms accept sign-in)
  doctor.py         preflight checks
  publish.py        Instagram + TikTok browser publishing
  browser/
    controller.py   BrowserController ABC + PlaywrightController + NullController
    worker.py       the conservative browser_flow worker
    flow_ui.py      Google Flow UI adapter (project → composer → result → download)
    selectors.py    layered selector resolution
    hard_stops.py   blocking-screen detection
    artifacts.py    screenshots/HTML/state logging with secret redaction
    queue.py        sequential browser_flow queue runner
  browser_selectors.example.yaml
```

## Testing

```bash
uv run pytest tests/social_video_factory/ -q
uv run ruff check social_video_factory/ tests/social_video_factory/
```
Tests use fakes — no real browser, network, or ffmpeg required.
