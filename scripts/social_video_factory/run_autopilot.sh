#!/usr/bin/env bash
# Wrapper the systemd service calls for one unattended autopilot pass.
# Sources the env file (creds + DISPLAY + unattended flags), then runs the CLI
# from the repo via uv. Kept tiny on purpose — all timing lives in the .timer.
set -euo pipefail

ENV_FILE="${SVF_ENV_FILE:-/etc/social-video-factory.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

: "${SVF_REPO_DIR:?Set SVF_REPO_DIR in $ENV_FILE to the repo path}"
: "${DISPLAY:?Set DISPLAY (e.g. :99) in $ENV_FILE}"

cd "$SVF_REPO_DIR"

# uv resolves the project Python + deps; ffmpeg/ffprobe + the Playwright
# Chromium are expected on PATH / installed (see setup_vm.sh).
exec uv run python -m social_video_factory.cli autopilot
