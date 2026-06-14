---
title: Autonomous social_video_factory on a headless VM
description: Run the browser_flow → render → caption → publish loop fully unattended and invisible on a local Linux VM, with Telegram/Discord alerts when it needs a human.
sidebar_label: Autonomous VM autopilot
sidebar_position: 9
---

# Autonomous `social_video_factory` on a headless VM

This guide makes the whole pipeline run **by itself, invisibly**, on a Linux VM on
your own machine: it generates videos via your logged-in Flow profile, renders
9:16, writes captions, **auto-publishes to Instagram + TikTok**, and **pings you
on Telegram/Discord** the moment it gets stuck.

## The one honest limitation

By design this tool is conservative — it **stops for a human** on any login wall,
CAPTCHA, verification screen, or when a web UI changes (it never bypasses these).
So the realistic outcome is **autonomous until challenged, then it waits and
alerts you**. Sessions expire and UIs drift; those are your ~2-minute assist
moments. It is *not* "set and forget forever."

**CAPTCHAs are never auto-solved.** When one appears, the system pings you and
shows you the *live* browser (via a noVNC link in the alert) so **you** solve it
in seconds; the run then continues on its own (a "supervised pause"). We do not
integrate CAPTCHA-solving services, stealth, or proxy rotation — solving a
CAPTCHA programmatically is circumventing the platform's bot detection, which
violates their terms and is the fast road to an account ban. The real defence
against frequent CAPTCHAs is low volume + your real logged-in profile.

## How it stays invisible

It runs **headed Chromium on a virtual display (Xvfb)** inside a **headless VM**.
"Headed" (a real rendered browser) avoids the heavier bot-detection that true
headless attracts; "virtual display" means nothing ever appears on a physical
screen. The only time you need a screen is the **one-time login seeding**, done
over a temporary VNC connection — after that the persistent profiles keep you
signed in.

## Architecture

```
systemd .timer (every N min)
   └─ social-video-autopilot.service (oneshot)
        └─ run_autopilot.sh  → uv run python -m social_video_factory.cli autopilot
             ├─ top up the queue from your configured topic rotation
             ├─ run the conservative browser queue (generate → import → review
             │    → render 9:16 → captions → auto-publish)   [on Xvfb :99]
             └─ Telegram/Discord alert if any job needs a human
```

- **Scheduler:** a `systemd` timer (survives reboots, zero LLM cost).
- **Invisible browser:** `xvfb.service` owns display `:99`.
- **Notifications:** reuse your existing Hermes bot via `TELEGRAM_BOT_TOKEN` +
  `TELEGRAM_HOME_CHANNEL` (or a Discord webhook) — a plain API POST, no gateway
  process required.

## Setup

Everything is scripted under `scripts/social_video_factory/`.

```bash
# On the VM, as the unprivileged user that will own the browser profiles:
SVF_REPO_DIR=/path/to/brainrot-automater bash scripts/social_video_factory/setup_vm.sh
```

That installs `ffmpeg`, `Xvfb`, `x11vnc`, `noVNC`/`websockify`, `uv`, the
Playwright Chromium binary, the systemd units (display + live-view + autopilot),
and an env file at `/etc/social-video-factory.env`. Then finish the manual steps
it prints:

1. **Fill in `/etc/social-video-factory.env`** — `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_HOME_CHANNEL`, `SOCIAL_FACTORY_FLOW_URL`. It already sets the flags
   that matter for unattended runs:
   `SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY=0` (otherwise every Nth
   generation blocks on a `y/N` prompt no one can answer),
   `SOCIAL_FACTORY_BROWSER_HEADLESS=false` (headed under Xvfb), and the
   supervised-CAPTCHA settings `SOCIAL_FACTORY_SUPERVISED_PAUSE=true` +
   `SOCIAL_FACTORY_NOVNC_URL=http://localhost:6080/vnc.html` (the live-view link
   put into your alerts).

2. **Configure publishing + topics** in `~/.hermes/config.yaml`:
   ```yaml
   social_video_factory:
     publishing:
       enabled: true
       auto_after_generation: true       # post without you
       platforms: [instagram, tiktok]
     autopilot:
       templates: [dancing_cat]
       topics: ["orange cat disco kitchen", "skater dog city night"]
       target_pending: 3                 # keep this many jobs queued
       per_run_limit: 2                  # generate at most N per pass
   ```
   With no `topics`, the loop never posts — a safe default.

3. **Seed the logins once** via the live noVNC view (no VNC client needed).
   Tunnel from your laptop: `ssh -L 6080:localhost:6080 user@vm`, then open
   `http://localhost:6080/vnc.html`. In a VM shell:
   ```bash
   DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target flow
   DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target instagram
   DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target tiktok
   ```
   Sign in by hand in each window (you'll see it in the noVNC tab), press Enter.
   The same noVNC link is what your CAPTCHA alerts will point you to later.

4. **Start the loop:**
   ```bash
   sudo systemctl enable --now social-video-autopilot.timer
   journalctl -u social-video-autopilot.service -f   # watch a pass
   ```

## Operating it

- **A run does nothing harmful when idle:** no topics or no pending work → it logs
  "nothing to do" and exits 0.
- **When a job hits a CAPTCHA/verification,** you get a Telegram/Discord message
  with the reason and the noVNC link. Open it, solve the challenge in the live
  browser, and the **same run continues automatically** (supervised pause). If
  you don't get to it within `SOCIAL_FACTORY_SUPERVISED_PAUSE_TIMEOUT` (default
  10 min), the run stops and the next pass retries.
- **Account health:** unattended posting carries flag risk. Keep the rate limits
  low (defaults: 3/hour, 20/day, 180s gap). TikTok's AI-content disclosure is
  toggled on automatically.

## Manual trigger / testing

```bash
# One pass on demand (same thing the timer runs):
uv run python -m social_video_factory.cli autopilot
# Dry, no posting: leave publishing.enabled=false in config.
```

## What it will NOT do

No stealth / anti-detection / fingerprint spoofing, no CAPTCHA solving, no
proxy/account rotation, no bypass of login/limits/safety, no feed scraping, no
likes/comments/follows. Credentials and tokens are never logged. Publishing only
happens when you explicitly enable it in config.

## Alternative scheduler (Hermes cron)

If you already run the Hermes gateway, you can skip systemd and register a
`no_agent` cron job that runs the same command with `deliver=telegram` for native
delivery. The systemd timer above is recommended for a dedicated VM because it
needs no long-running gateway process.
