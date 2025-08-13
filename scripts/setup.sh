#!/usr/bin/env bash
# Idempotent bootstrap for Ubuntu 22.04 to deploy the echosu app
set -euo pipefail

# -------- Configuration (override via env before running) --------
: "${APP_NAME:=echosu}"
: "${APP_USER:=django}"
: "${REPO_URL:=git@github.com:Leggo15/echosu.git}"   # Set to your repo (SSH or HTTPS)
: "${DOMAIN:=echosu.com}"
: "${WWW_DOMAIN:=www.echosu.com}"
: "${ADMIN_EMAIL:=richardhanse.no@outlook.com}"
: "${GENERATE_DEPLOY_KEY:=0}"  # set to 1 to auto-generate an ed25519 key for $APP_USER
: "${GIT_AS_ROOT:=1}"          # set to 1 to run git operations as root (use root's SSH key)

REPO_DIR=/opt/$APP_NAME
VENV_DIR=$REPO_DIR/venv
# Derived after detecting manage.py location
APP_DIR=""
ENV_FILE=""
SERVICE_FILE=/etc/systemd/system/$APP_NAME.service
NGINX_CONF=/etc/nginx/sites-available/$APP_NAME
WSGI_MODULE=echoOsu.wsgi

sudo() { command sudo "$@"; }

log() { echo "[setup:$APP_NAME] $*"; }

install_pkgs() {
  log "Installing apt packages"
  sudo apt-get update
  sudo apt-get install -y \
       python3-venv python3-pip build-essential \
       libjpeg-dev zlib1g-dev git nginx unzip curl ca-certificates

  if ! command -v aws >/dev/null 2>&1; then
    log "Installing AWS CLI v2 (optional, used by some workflows)"
    curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
    (cd /tmp && unzip -q awscliv2.zip && sudo ./aws/install)
  fi
}

setup_user() {
  log "Ensuring system user $APP_USER exists"
  if ! id -u "$APP_USER" &>/dev/null; then
    sudo adduser --system --group --home "/home/$APP_USER" --shell /bin/bash "$APP_USER"
  fi
}

clone_repo() {
  if [[ -d $REPO_DIR/.git ]]; then
    log "Repo exists; fetching latest"
    if [[ "$GIT_AS_ROOT" == "1" ]]; then
      git -C "$REPO_DIR" fetch --quiet --all
      CURRENT_BRANCH=$(git -C "$REPO_DIR" symbolic-ref --short HEAD || echo main)
      git -C "$REPO_DIR" reset --hard "origin/$CURRENT_BRANCH" --quiet
    else
      sudo -u "$APP_USER" -H git -C "$REPO_DIR" fetch --quiet --all
      CURRENT_BRANCH=$(sudo -u "$APP_USER" -H git -C "$REPO_DIR" symbolic-ref --short HEAD || echo main)
      sudo -u "$APP_USER" -H git -C "$REPO_DIR" reset --hard "origin/$CURRENT_BRANCH" --quiet
    fi
  else
    log "Cloning repo into $REPO_DIR"
    sudo mkdir -p "$REPO_DIR"
    sudo chown -R "$APP_USER":"www-data" "$REPO_DIR"
    if [[ -z "${REPO_URL}" ]]; then
      echo "REPO_URL is empty. Please set REPO_URL to your repository URL." >&2
      exit 1
    fi
    if [[ "$GIT_AS_ROOT" == "1" ]]; then
      git clone "$REPO_URL" "$REPO_DIR"
    else
      sudo -u "$APP_USER" -H git clone "$REPO_URL" "$REPO_DIR"
    fi
  fi
  sudo chown -R "$APP_USER":"www-data" "$REPO_DIR"
}

add_git_safedir() {
  if ! sudo git config --global --get-all safe.directory | grep -q "^$REPO_DIR$"; then
    log "Marking $REPO_DIR as a safe Git directory"
    sudo git config --global --add safe.directory "$REPO_DIR"
  fi
}

get_user_home() {
  USER_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
  if [[ -z "$USER_HOME" || "$USER_HOME" == "/nonexistent" ]]; then
    USER_HOME="/home/$APP_USER"
    log "Fixing $APP_USER home to $USER_HOME"
    sudo usermod -d "$USER_HOME" -m "$APP_USER"
  fi
}

prepare_user_home_ssh() {
  get_user_home
  log "Preparing $APP_USER SSH directory at $USER_HOME/.ssh"
  sudo mkdir -p "$USER_HOME/.ssh"
  sudo chown -R "$APP_USER":"$APP_USER" "$USER_HOME/.ssh"
  sudo chmod 700 "$USER_HOME/.ssh"

  local host=""
  # Best-effort extraction of SSH host from REPO_URL
  if echo "$REPO_URL" | grep -qE '^[^@]+@[^:]+:'; then
    host=$(echo "$REPO_URL" | sed -n 's/.*@\([^:]*\):.*/\1/p')
  elif echo "$REPO_URL" | grep -qE '^ssh://'; then
    host=$(echo "$REPO_URL" | sed -n 's#ssh://[^@]*@\([^/]*\)/.*#\1#p')
  elif echo "$REPO_URL" | grep -q 'github.com'; then
    host="github.com"
  fi

  if [[ -n "$host" ]]; then
    log "Seeding known_hosts for $host"
    sudo -u "$APP_USER" ssh-keyscan -H "$host" 2>/dev/null | sudo tee -a "$USER_HOME/.ssh/known_hosts" >/dev/null || true
    sudo chmod 644 "$USER_HOME/.ssh/known_hosts" || true
  fi

  if [[ "$GENERATE_DEPLOY_KEY" == "1" && ! -f "$USER_HOME/.ssh/id_ed25519" ]]; then
    log "Generating deploy key for $APP_USER (ed25519)"
    sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -C "$APP_NAME-deploy" -f "$USER_HOME/.ssh/id_ed25519"
    log "Public key (add as a deploy key in your repo settings):"
    sudo cat "$USER_HOME/.ssh/id_ed25519.pub" || true
  fi
}

detect_app_dir() {
  # Determine the directory that contains manage.py
  if [[ -f "$REPO_DIR/manage.py" ]]; then
    APP_DIR="$REPO_DIR"
  elif [[ -f "$REPO_DIR/echoOsu/manage.py" ]]; then
    APP_DIR="$REPO_DIR/echoOsu"
  else
    local found
    found=$(find "$REPO_DIR" -maxdepth 3 -type f -name manage.py | head -n1 || true)
    if [[ -n "$found" ]]; then
      APP_DIR=$(dirname "$found")
    else
      echo "Could not locate manage.py under $REPO_DIR" >&2
      exit 1
    fi
  fi
  ENV_FILE="$APP_DIR/.env"
}

detect_requirements() {
  # Prefer repo root requirements.txt, fallback to APP_DIR
  if [[ -f "$REPO_DIR/requirements.txt" ]]; then
    REQ_FILE="$REPO_DIR/requirements.txt"
  elif [[ -f "$APP_DIR/requirements.txt" ]]; then
    REQ_FILE="$APP_DIR/requirements.txt"
  else
    echo "requirements.txt not found under $REPO_DIR or $APP_DIR" >&2
    exit 1
  fi
}

create_venv() {
  log "Creating/upgrading virtualenv"
  if [[ ! -d $VENV_DIR ]]; then
    sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
  fi
  sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip wheel setuptools
  sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$REQ_FILE"
}

ensure_env_file() {
  if [[ ! -f $ENV_FILE ]]; then
    log "Creating skeleton .env at $ENV_FILE"
    sudo tee "$ENV_FILE" >/dev/null <<EOF
# Django
SECRET_KEY=CHANGE_ME
DEBUG=0
ALLOWED_HOSTS=$DOMAIN,$WWW_DOMAIN
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://$WWW_DOMAIN

# Cookies/security
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true

# osu! OAuth
SOCIAL_AUTH_OSU_KEY=
SOCIAL_AUTH_OSU_SECRET=

# AWS creds for S3 static/media (bucket is configured in settings.py)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Admin provisioning (comma-separated osu IDs)
ADMIN_OSU_IDS=
EOF
    sudo chown "$APP_USER":"www-data" "$ENV_FILE"
    sudo chmod 640 "$ENV_FILE"
    echo "Created $ENV_FILE. Edit it to set real secrets before proceeding." >&2
  fi
}

django_tasks() {
  log "Running Django migrations and collectstatic"
  # No shell-sourcing of .env; Django loads it via python-dotenv in settings.py
  sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && \
    source '$VENV_DIR/bin/activate' && \
    python manage.py migrate --noinput"

  # Only attempt collectstatic if AWS credentials appear present
  if grep -qE '^[ ]*AWS_ACCESS_KEY_ID=.+$' "$ENV_FILE" && grep -qE '^[ ]*AWS_SECRET_ACCESS_KEY=.+$' "$ENV_FILE"; then
    sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && \
      source '$VENV_DIR/bin/activate' && \
      python manage.py collectstatic --noinput"
  else
    log "Skipping collectstatic (AWS credentials not set in $ENV_FILE)"
  fi
}

create_service() {
  log "Creating systemd service at $SERVICE_FILE"
  sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Gunicorn daemon for $APP_NAME
After=network.target

[Service]
User=$APP_USER
Group=www-data
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
RuntimeDirectory=$APP_NAME
ExecStart=$VENV_DIR/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:/run/$APP_NAME/$APP_NAME.sock \
          $WSGI_MODULE:application
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$APP_NAME"
}

configure_nginx() {
  log "Configuring Nginx site: $NGINX_CONF"
  sudo tee "$NGINX_CONF" >/dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN $WWW_DOMAIN;

    # Increase if you expect larger payloads
    client_max_body_size 20M;

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/$APP_NAME/$APP_NAME.sock;
        proxy_read_timeout 60s;
    }
}
EOF
  sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/$APP_NAME
  if [[ -f /etc/nginx/sites-enabled/default ]]; then
    sudo rm -f /etc/nginx/sites-enabled/default
  fi
  sudo nginx -t
  sudo systemctl reload nginx
}

install_certbot() {
  # Only attempt if no existing cert
  if ! sudo test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"; then
    log "Issuing Let's Encrypt certificate for $DOMAIN and $WWW_DOMAIN"
    sudo apt-get install -y certbot python3-certbot-nginx
    sudo certbot --nginx \
         -d "$DOMAIN" -d "$WWW_DOMAIN" \
         -m "$ADMIN_EMAIL" --agree-tos --non-interactive || true
  fi
}

restart_stack() {
  log "Restarting service and reloading Nginx"
  sudo systemctl restart "$APP_NAME"
  sudo systemctl reload nginx
}

main() {
  install_pkgs
  setup_user
  prepare_user_home_ssh
  clone_repo
  add_git_safedir
  detect_app_dir
  detect_requirements
  create_venv
  ensure_env_file
  django_tasks
  create_service
  configure_nginx
  install_certbot
  restart_stack
  log "Setup complete. Ensure $ENV_FILE contains valid secrets."
}

main "$@"


