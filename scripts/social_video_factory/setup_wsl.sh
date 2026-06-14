#!/usr/bin/env bash
# Provision social_video_factory autopilot inside an existing WSL2 Ubuntu distro.
# Run as ROOT (WSL gives passwordless root, no sudo needed):
#   wsl -d Ubuntu -u root -- bash /mnt/c/.../scripts/social_video_factory/setup_wsl.sh
#
# Additive + idempotent. Installs a MINIMAL venv (just what the autopilot CLI
# needs) rather than the whole Hermes tree, so it's fast and robust. Chromium
# goes to a shared /opt path both root (installer) and the user (runtime) share.
set -euo pipefail

SVF_USER="${SVF_USER:-sinan}"
SRC="${SVF_SRC:-/mnt/c/Users/sinan/IdeaProjects/coursework/brainrot-automater}"
DEST="/home/$SVF_USER/brainrot-automater"
UVBIN="/home/$SVF_USER/.local/bin/uv"
export DEBIAN_FRONTEND=noninteractive

echo "== [1/6] apt packages =="
apt-get update -y
apt-get install -y --no-install-recommends \
  ffmpeg xvfb x11vnc novnc websockify git curl ca-certificates fonts-liberation

echo "== [2/6] uv (as $SVF_USER) =="
su - "$SVF_USER" -c 'command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "== [3/6] clone repo -> $DEST =="
su - "$SVF_USER" -c "rm -rf '$DEST' && git clone -q '$SRC' '$DEST'"

echo "== [4/6] minimal venv (playwright + the CLI's deps) =="
su - "$SVF_USER" -c "cd '$DEST' && '$UVBIN' venv --python 3.12 .venv && '$UVBIN' pip install --python .venv 'playwright==1.60.0' python-dotenv pyyaml fire httpx"

echo "== [5/6] Google Chrome (driven via executable_path) =="
# We drive REAL Google Chrome via executable_path rather than Playwright's
# bundled Chromium: the .deb carries its own OS deps and it works on brand-new
# Ubuntu releases that Playwright's bundled-browser installer doesn't yet know
# (e.g. 26.04). It's also the most natural browser for a Google login.
if ! command -v google-chrome-stable >/dev/null 2>&1; then
  curl -fsSL -o /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
fi
google-chrome-stable --version

echo "== [6/6] runtime dir =="
su - "$SVF_USER" -c "mkdir -p '$DEST/.social_video_factory'"

echo "PROVISION_DONE"
