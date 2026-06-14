#!/usr/bin/env bash
# Install the invisible-display stack as systemd services inside WSL2 Ubuntu.
# Run as ROOT:  wsl -d Ubuntu -u root -- bash -s < setup_display_wsl.sh
#
# Why systemd (not the run wrapper): WSL cold-starts the distro per scheduled
# run; systemd brings these up at boot and keeps them alive (Restart=always),
# so the live-view is ready independent of the autopilot process. systemd units
# run with a clean env (no WSLg WAYLAND_DISPLAY), which also unblocks x11vnc.
set -euo pipefail

install -d /etc/systemd/system

cat > /etc/systemd/system/svf-x11unix.service <<'UNIT'
[Unit]
Description=svf: writable /tmp/.X11-unix (WSLg mounts it read-only)
DefaultDependencies=no
After=local-fs.target
Before=svf-xvfb.service
[Service]
Type=oneshot
RemainAfterExit=yes
# With WSLg disabled (guiApplications=false in .wslconfig), /tmp/.X11-unix is a
# normal writable dir — just ensure it exists 1777 and clear any stale lock so
# Xvfb can claim :99 cleanly. (If WSLg is left on it remounts this ro and Xvfb
# cannot bind — see the autonomous-vm docs.)
ExecStart=/bin/sh -c 'mkdir -p /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix; rm -f /tmp/.X99-lock /tmp/.X11-unix/X99'
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/svf-xvfb.service <<'UNIT'
[Unit]
Description=svf: Xvfb virtual display :99 (invisible)
Requires=svf-x11unix.service
After=svf-x11unix.service
[Service]
ExecStartPre=/bin/sh -c 'rm -f /tmp/.X99-lock /tmp/.X11-unix/X99'
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x2280x24 -ac -nolisten tcp
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/svf-x11vnc.service <<'UNIT'
[Unit]
Description=svf: x11vnc sharing :99 on localhost
Requires=svf-xvfb.service
After=svf-xvfb.service
[Service]
Environment=DISPLAY=:99
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -S /tmp/.X11-unix/X99 ] && exit 0; sleep 0.5; done'
ExecStart=/usr/bin/x11vnc -display :99 -localhost -forever -shared -rfbport 5900 -nopw -quiet
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/svf-novnc.service <<'UNIT'
[Unit]
Description=svf: noVNC (websockify) on localhost:6080
Requires=svf-x11vnc.service
After=svf-x11vnc.service
[Service]
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 6080 localhost:5900
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable svf-x11unix.service svf-xvfb.service svf-x11vnc.service svf-novnc.service
systemctl restart svf-x11unix.service svf-xvfb.service svf-x11vnc.service svf-novnc.service
echo "DISPLAY_SERVICES_INSTALLED"
