#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash scripts/setup/install_system_services.sh" >&2
  exit 1
fi

PYPOE_USER="${PYPOE_USER:-sdl2}"
PYPOE_GROUP="${PYPOE_GROUP:-sdl2}"
PYPOE_REPO="${PYPOE_REPO:-/home/sdl2/caoyang/pypoe}"
PYPOE_BIN="${PYPOE_BIN:-/home/sdl2/pyenv/bin/pypoe}"
PYPOE_ENV="${PYPOE_ENV:-${PYPOE_REPO}/.env}"

install -d -m 0755 /etc/systemd/system

cat >/etc/systemd/system/pypoe-web.service <<UNIT
[Unit]
Description=PyPoe Web UI
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=${PYPOE_USER}
Group=${PYPOE_GROUP}
WorkingDirectory=${PYPOE_REPO}
Environment=PYTHONPATH=${PYPOE_REPO}/src
Environment=PATH=/home/sdl2/pyenv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=${PYPOE_ENV}
ExecStart=/bin/bash -lc 'exec ${PYPOE_BIN} web --host "$(/usr/bin/tailscale ip -4)" --port "\${PYPOE_PORT:-8000}"'
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
SyslogIdentifier=pypoe-web
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=false
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=${PYPOE_REPO} /home/sdl2/.pypoe

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/pypoe-slack.service <<UNIT
[Unit]
Description=PyPoe Slack Bot
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=${PYPOE_USER}
Group=${PYPOE_GROUP}
WorkingDirectory=${PYPOE_REPO}
Environment=PYTHONPATH=${PYPOE_REPO}/src
Environment=PATH=/home/sdl2/pyenv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=${PYPOE_ENV}
ExecStart=${PYPOE_BIN} slack
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
SyslogIdentifier=pypoe-slack
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=false
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=${PYPOE_REPO} /home/sdl2/.pypoe

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

# Stop user services first to avoid a duplicate Slack Socket Mode connection
# and a web port bind conflict during migration.
runuser -u "${PYPOE_USER}" -- systemctl --user stop pypoe-web.service pypoe-slack.service 2>/dev/null || true
runuser -u "${PYPOE_USER}" -- systemctl --user disable pypoe-web.service pypoe-slack.service 2>/dev/null || true

systemctl enable --now pypoe-web.service pypoe-slack.service
systemctl --no-pager --full status pypoe-web.service pypoe-slack.service
