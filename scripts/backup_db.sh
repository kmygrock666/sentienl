#!/usr/bin/env bash
# 每日備份 sentinel Postgres 資料庫（透過 docker 容器內的 pg_dump）。
#
# 用法：
#   scripts/backup_db.sh              # 產生今日備份並輪替舊檔
#   BACKUP_DIR=/path scripts/backup_db.sh
#
# 輪替策略：每日備份保留 7 份；每週日的備份另存 weekly/ 保留 28 天。
# 建議 crontab（每日 17:30，收盤資料同步完成後）：
#   30 17 * * * /Users/ian-yu/git/sentinel/scripts/backup_db.sh >> /Users/ian-yu/git/sentinel/data/backups/backup.log 2>&1
#
# 還原程序（TimescaleDB 需要 pre/post restore；已於 2026-07-04 實測驗證）：
#   docker exec sentinel-db-1 psql -U trading -d postgres -c "CREATE DATABASE sentinel_new"
#   docker exec sentinel-db-1 psql -U trading -d sentinel_new \
#       -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
#   docker exec -i sentinel-db-1 pg_restore -U trading -d sentinel_new --no-owner < <備份檔.dump>
#   docker exec sentinel-db-1 psql -U trading -d sentinel_new -c "SELECT timescaledb_post_restore()"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/data/backups/pg}"
WEEKLY_DIR="$BACKUP_DIR/weekly"
CONTAINER="${PG_CONTAINER:-sentinel-db-1}"
DB_USER="${PG_USER:-trading}"
DB_NAME="${PG_DB:-sentinel}"
DAILY_KEEP=7
WEEKLY_KEEP_DAYS=28

mkdir -p "$BACKUP_DIR" "$WEEKLY_DIR"

if ! docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    echo "[$(date '+%F %T')] ERROR: container $CONTAINER is not running" >&2
    exit 1
fi

stamp="$(date +%Y%m%d)"
outfile="$BACKUP_DIR/${DB_NAME}-${stamp}.dump"
tmpfile="${outfile}.tmp"

echo "[$(date '+%F %T')] dumping $DB_NAME from $CONTAINER ..."
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc >"$tmpfile"
mv "$tmpfile" "$outfile"
echo "[$(date '+%F %T')] wrote $outfile ($(du -h "$outfile" | cut -f1))"

# 驗證 dump 檔可被 pg_restore 讀取（目錄完整性）
docker exec -i "$CONTAINER" pg_restore --list >/dev/null <"$outfile"
echo "[$(date '+%F %T')] archive verified (pg_restore --list ok)"

# 週日另存 weekly
if [ "$(date +%u)" = "7" ]; then
    cp "$outfile" "$WEEKLY_DIR/"
fi

# 輪替：每日保留最近 N 份；weekly 保留 N 天
ls -1t "$BACKUP_DIR"/${DB_NAME}-*.dump 2>/dev/null | tail -n +$((DAILY_KEEP + 1)) | xargs -I{} rm -f {}
find "$WEEKLY_DIR" -name "${DB_NAME}-*.dump" -mtime +$WEEKLY_KEEP_DAYS -delete

echo "[$(date '+%F %T')] done. current backups:"
ls -lh "$BACKUP_DIR"/*.dump 2>/dev/null || true
