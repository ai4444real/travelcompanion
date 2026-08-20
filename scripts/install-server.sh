#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/travel-companion
SERVICE_FILE=/etc/systemd/system/travel-companion.service

if [[ $EUID -ne 0 ]]; then
  echo "Eseguire con sudo: sudo ./scripts/install-server.sh" >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "Repository non trovato in $APP_DIR" >&2
  exit 1
fi

install -d -o ubuntu -g ubuntu -m 0750 "$APP_DIR/data"

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  runuser -u ubuntu -- python3 -m venv "$APP_DIR/.venv"
fi

runuser -u ubuntu -- "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
runuser -u ubuntu -- "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

install -o root -g root -m 0644 "$APP_DIR/infra/travel-companion.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now travel-companion.service
systemctl --no-pager --full status travel-companion.service

