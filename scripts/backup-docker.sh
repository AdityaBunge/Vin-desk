#!/bin/sh
# Nightly backup for the Docker deployment: database dump + job photographs, kept for 14 days.
#   crontab -e   ->   30 2 * * * /opt/vindesk/scripts/backup-docker.sh >> /var/log/vindesk-backup.log 2>&1
# Copy the backup folder off the server too (e.g. to object storage), or a lost server loses the backups.
set -eu
cd "$(dirname "$0")/.."
DEST="${BACKUP_DIR:-/var/backups/vindesk}"
STAMP="$(date +%Y%m%d-%H%M)"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
mkdir -p "$DEST"

$COMPOSE exec -T db pg_dump -U vindesk -d vindesk -Fc > "$DEST/db-$STAMP.dump"
$COMPOSE exec -T api tar -C /data -czf - uploads > "$DEST/uploads-$STAMP.tar.gz"

find "$DEST" -type f -mtime +14 -delete
echo "$(date) backup ok: $DEST/db-$STAMP.dump"
# Restore: docker compose ... exec -T db pg_restore -U vindesk -d vindesk --clean --if-exists < db-XXXX.dump
