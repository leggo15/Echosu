#!/usr/bin/env bash
# Idempotent deploy/update script for echosu on Ubuntu 22.04
set -euo pipefail

: "${APP_NAME:=echosu}"
: "${APP_USER:=django}"
: "${REPO_DIR:=/opt/$APP_NAME}"
: "${VENV_DIR:=$REPO_DIR/venv}"
: "${ENV_FILE:=$REPO_DIR/.env}"

sudo() { command sudo "$@"; }
log() { echo "[deploy:$APP_NAME] $*"; }

pull_latest() {
  log "Pulling latest code"
  if [[ ! -d $REPO_DIR/.git ]]; then
    echo "Repo not found at $REPO_DIR" >&2
    exit 1
  fi
  sudo -u "$APP_USER" git -C "$REPO_DIR" fetch --quiet --all
  BR=$(sudo -u "$APP_USER" git -C "$REPO_DIR" symbolic-ref --short HEAD || echo main)
  sudo -u "$APP_USER" git -C "$REPO_DIR" reset --hard "origin/$BR" --quiet
}

install_requirements() {
  log "Installing Python requirements"
  sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip wheel setuptools
  sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
}

run_django_tasks() {
  log "Applying migrations and collecting static"
  sudo -u "$APP_USER" bash -c "cd '$REPO_DIR' && \
    set -a && . '$ENV_FILE' && set +a && \
    source '$VENV_DIR/bin/activate' && \
    python manage.py migrate --noinput && \
    python manage.py collectstatic --noinput"
}

restart_services() {
  log "Restarting systemd service and reloading Nginx"
  sudo systemctl restart "$APP_NAME"
  sudo systemctl reload nginx || true
}

main() {
  pull_latest
  install_requirements
  run_django_tasks
  restart_services
  log "Deploy complete"
}

main "$@"


