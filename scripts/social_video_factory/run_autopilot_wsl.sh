#!/usr/bin/env bash
# One autopilot pass inside WSL2. Windows Task Scheduler runs this hourly as the
# unprivileged user. The invisible display + live-view are owned by systemd
# (see setup_display_wsl.sh), so this just waits for the display to be ready and
# runs a single pass.
set -uo pipefail

ENV_FILE="${SVF_ENV_FILE:-$HOME/svf-autopilot.env}"
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
: "${SVF_REPO_DIR:=$HOME/brainrot-automater}"
export DISPLAY="${DISPLAY:-:99}"
unset WAYLAND_DISPLAY || true

# Never overlap two browser/publisher runs if one takes longer than 20 minutes.
mkdir -p "$SVF_REPO_DIR/.social_video_factory/state"
exec 9>"$SVF_REPO_DIR/.social_video_factory/state/autopilot.lock"
if ! flock -n 9; then
  echo "autopilot already running; skipping this wake"
  exit 0
fi

# Wait up to ~20s for systemd to bring the virtual display up (WSL cold start).
for _ in $(seq 1 40); do
  [ -S /tmp/.X11-unix/X99 ] && break
  sleep 0.5
done

cd "$SVF_REPO_DIR"
exec ./.venv/bin/python -m social_video_factory.cli autopilot
