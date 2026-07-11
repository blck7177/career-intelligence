#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:=postgres}"
: "${PGPORT:=5432}"
: "${PGUSER:=career}"
: "${PGDATABASE:=career_openclaw}"
: "${BACKUP_DIR:=/backups}"
: "${ARTIFACTS_DIR:=/app/data/agent_artifacts}"
: "${BACKUP_INTERVAL_SECONDS:=21600}"
: "${BACKUP_RETENTION_DAYS:=7}"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

wait_for_pg() {
    log "Waiting for PostgreSQL at ${PGHOST}:${PGPORT}..."
    until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -q; do
        sleep 2
    done
    log "PostgreSQL is ready."
}

run_backup() {
    local ts
    ts=$(date -u '+%Y%m%dT%H%M%SZ')
    local pg_file="${BACKUP_DIR}/pg_${ts}.sql.gz"
    local art_file="${BACKUP_DIR}/artifacts_${ts}.tar.gz"

    mkdir -p "$BACKUP_DIR"

    log "Starting PostgreSQL backup..."
    pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
        --no-password --format=plain | gzip > "$pg_file"
    local pg_size
    pg_size=$(du -h "$pg_file" | cut -f1)
    log "PostgreSQL backup complete: ${pg_file} (${pg_size})"

    if [ -d "$ARTIFACTS_DIR" ] && [ "$(ls -A "$ARTIFACTS_DIR" 2>/dev/null)" ]; then
        log "Starting artifacts backup..."
        tar czf "$art_file" -C "$(dirname "$ARTIFACTS_DIR")" "$(basename "$ARTIFACTS_DIR")"
        local art_size
        art_size=$(du -h "$art_file" | cut -f1)
        log "Artifacts backup complete: ${art_file} (${art_size})"
    else
        log "Artifacts directory empty or missing, skipping."
    fi

    log "Pruning backups older than ${BACKUP_RETENTION_DAYS} days..."
    find "$BACKUP_DIR" -name "pg_*.sql.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete -print | while read -r f; do
        log "  Deleted: $f"
    done
    find "$BACKUP_DIR" -name "artifacts_*.tar.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete -print | while read -r f; do
        log "  Deleted: $f"
    done

    local count
    count=$(find "$BACKUP_DIR" -name "pg_*.sql.gz" | wc -l)
    log "Backup cycle complete. ${count} PostgreSQL backup(s) on disk."
}

# Run once immediately on startup, then loop
wait_for_pg

log "Backup sidecar started. interval=${BACKUP_INTERVAL_SECONDS}s, retention=${BACKUP_RETENTION_DAYS}d"
while true; do
    run_backup
    log "Next backup in ${BACKUP_INTERVAL_SECONDS}s..."
    sleep "$BACKUP_INTERVAL_SECONDS"
done
