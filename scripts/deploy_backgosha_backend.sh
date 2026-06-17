#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ProTires/Bitrix-Tires}"
BACKEND_DIR="${BACKEND_DIR:-/home/ProTires/web_backend}"
BRANCH="${BRANCH:-master}"
BACKUP_DIR="${BACKUP_DIR:-/home/ProTires/backups}"

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

mkdir -p "$BACKUP_DIR"
backup_file="$BACKUP_DIR/web_backend_before_deploy_$(date +%Y%m%d_%H%M%S).tar.gz"
tar --exclude='./runtime' --exclude='./.env' -czf "$backup_file" -C "$BACKEND_DIR" .

rsync -a --delete \
  --exclude '.env' \
  --exclude 'runtime/' \
  "$REPO_DIR/web_backend/" \
  "$BACKEND_DIR/"

cd "$BACKEND_DIR"
docker compose up -d --build
docker compose ps

for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18080/health >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "Backend health check failed after $attempt attempts" >&2
    docker compose ps >&2
    exit 1
  fi
  sleep 2
done

curl -fsS http://127.0.0.1:18080/health
echo
curl -fsS http://127.0.0.1:18080/api/health
echo

echo "Deployed backend from $REPO_DIR ($BRANCH)"
echo "Backup: $backup_file"
