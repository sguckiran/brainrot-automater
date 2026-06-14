#!/usr/bin/env bash
# Post-provision config for the WSL autopilot. Run as the USER (default sinan):
#   wsl -d Ubuntu -- bash -s < scripts/social_video_factory/configure_wsl.sh
# Writes the env file + a Hermes config scaffold. NEVER overwrites an existing
# config (so it can't clobber a Hermes setup you already have). Secrets are left
# blank for you to fill.
set -euo pipefail

REPO="$HOME/brainrot-automater"
ENV_FILE="$HOME/svf-autopilot.env"
HERMES="$HOME/.hermes"
mkdir -p "$HERMES"

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
SVF_REPO_DIR=__REPO__
DISPLAY=:99
# Drive real Google Chrome (installed by setup_wsl.sh) rather than a bundled
# Chromium — robust on new Ubuntu and natural for Google login.
SOCIAL_FACTORY_BROWSER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable
SOCIAL_FACTORY_BROWSER_HEADLESS=false
# MUST be 0 for unattended (else every Nth gen blocks on a y/N prompt).
SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY=0
SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR=3
SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY=72
SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS=180
SOCIAL_FACTORY_FLOW_URL=https://labs.google/fx/tools/flow
SOCIAL_FACTORY_SUPERVISED_PAUSE=true
SOCIAL_FACTORY_SUPERVISED_PAUSE_TIMEOUT=600
# WSL2 forwards localhost, so this opens in your Windows browser directly.
SOCIAL_FACTORY_NOVNC_URL=http://localhost:6080/vnc.html
# --- FILL THESE IN (create a bot via @BotFather, then message it once) ------
TELEGRAM_BOT_TOKEN=
TELEGRAM_HOME_CHANNEL=
EOF
  sed -i "s#__REPO__#$REPO#" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "wrote $ENV_FILE"
else
  echo "kept existing $ENV_FILE"
fi

if [ ! -f "$HERMES/config.yaml" ]; then
  cat > "$HERMES/config.yaml" <<'EOF'
social_video_factory:
  publishing:
    enabled: false            # flip true AFTER a verified manual run
    auto_after_generation: false
    platforms: [instagram, tiktok]
  autopilot:
    templates: [dancing_cat]
    topics: []                # add your topics; empty = the loop idles
    target_pending: 1
    per_run_limit: 1
  rendering:
    burn_text_overlays: false
EOF
  echo "wrote $HERMES/config.yaml"
else
  echo "KEPT existing $HERMES/config.yaml — add the social_video_factory block yourself"
fi

echo "CONFIGURE_DONE"
