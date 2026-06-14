#!/usr/bin/env bash
# One-time provisioning for running social_video_factory autopilot, invisibly,
# on a headless Ubuntu/Debian VM. Idempotent-ish; safe to re-run.
#
# What it sets up:
#   - system deps: ffmpeg, Xvfb (virtual display), x11vnc (one-time login only)
#   - uv + the Playwright Chromium browser binary
#   - systemd units: xvfb.service + social-video-autopilot.service/.timer
#   - an env file at /etc/social-video-factory.env (you must fill in creds)
#
# Run as the unprivileged user that will OWN the browser profiles (e.g. `svf`),
# with sudo available. Usage:  SVF_REPO_DIR=/path/to/repo bash setup_vm.sh
set -euo pipefail

SVF_REPO_DIR="${SVF_REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SCRIPT_DIR="$SVF_REPO_DIR/scripts/social_video_factory"
SVF_USER="${SVF_USER:-$(id -un)}"
ENV_DEST="/etc/social-video-factory.env"

echo "==> repo:   $SVF_REPO_DIR"
echo "==> user:   $SVF_USER"

echo "==> Installing system packages (sudo)…"
sudo apt-get update -y
# x11vnc + novnc/websockify power the live "solve the CAPTCHA" web view.
sudo apt-get install -y ffmpeg xvfb x11vnc novnc websockify curl ca-certificates

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Syncing Python env + installing Playwright Chromium…"
cd "$SVF_REPO_DIR"
uv sync --extra dev
# --with-deps pulls the OS libraries Chromium needs on a headless server.
uv run python -m playwright install --with-deps chromium

echo "==> Installing the env file template (edit it next)…"
if [[ ! -f "$ENV_DEST" ]]; then
  sudo cp "$SCRIPT_DIR/social-video-factory.env.example" "$ENV_DEST"
  sudo sed -i "s#^SVF_REPO_DIR=.*#SVF_REPO_DIR=$SVF_REPO_DIR#" "$ENV_DEST"
  sudo chmod 600 "$ENV_DEST"
  sudo chown "$SVF_USER" "$ENV_DEST"
else
  echo "    $ENV_DEST already exists — leaving it untouched."
fi

echo "==> Installing systemd units…"
UNITS=(
  xvfb.service
  x11vnc.service
  novnc.service
  social-video-autopilot.service
  social-video-autopilot.timer
)
for unit in "${UNITS[@]}"; do
  # Point the service's ExecStart/User at this repo + user.
  tmp="$(mktemp)"
  sed -e "s#/home/svf/brainrot-automater#$SVF_REPO_DIR#g" \
      -e "s#^User=svf#User=$SVF_USER#g" \
      "$SCRIPT_DIR/systemd/$unit" > "$tmp"
  sudo cp "$tmp" "/etc/systemd/system/$unit"
  rm -f "$tmp"
done
sudo systemctl daemon-reload
# Display + live-view services run continuously; the autopilot timer is started
# last (after you've seeded logins).
sudo systemctl enable --now xvfb.service x11vnc.service novnc.service

cat <<EOF

==> Base setup done. REMAINING MANUAL STEPS:

1) Edit $ENV_DEST and fill in:
     TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL, SOCIAL_FACTORY_FLOW_URL

2) Configure publishing + topics in ~/.hermes/config.yaml:
     social_video_factory:
       publishing:
         enabled: true
         auto_after_generation: true
         platforms: [instagram, tiktok]
       autopilot:
         templates: [dancing_cat]
         topics: ["orange cat disco kitchen", "..."]
         target_pending: 3
         per_run_limit: 2

3) View the live browser (one-time login AND supervised CAPTCHA solving) via
   noVNC — no VNC client needed. From your laptop, open an SSH tunnel:
     ssh -L 6080:localhost:6080 $SVF_USER@<vm>
   then browse to:  http://localhost:6080/vnc.html   (this is SOCIAL_FACTORY_NOVNC_URL)

   ONE-TIME login seeding — in a VM shell run (with DISPLAY=:99), watching noVNC:
     DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target flow
     DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target instagram
     DISPLAY=:99 uv run python -m social_video_factory.cli browser-login --target tiktok
   Log in by hand in each, press Enter. Sessions now persist in the profiles.

   Later, when a run hits a CAPTCHA, you'll get a Telegram ping with that same
   noVNC link — open it, solve the challenge in the live browser, and the run
   continues on its own (supervised pause).

4) Start the loop:
     sudo systemctl enable --now social-video-autopilot.timer
     systemctl list-timers social-video-autopilot.timer     # confirm schedule
     journalctl -u social-video-autopilot.service -f        # watch a run

The pipeline now runs invisibly on a cadence and pings your Telegram when a job
needs a human (expired login, CAPTCHA, or a changed web UI).
EOF
