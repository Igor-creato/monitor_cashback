#!/usr/bin/env bash
set -euo pipefail

: "${BASE_DIR:?BASE_DIR is required}"
: "${PRICE_MONITOR_ENV_FILE:?PRICE_MONITOR_ENV_FILE is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"
: "${TARGET_POSTGRES_MAJOR:?TARGET_POSTGRES_MAJOR is required}"

cd "$BASE_DIR/current"

compose() {
  PRICE_MONITOR_ENV_FILE="$PRICE_MONITOR_ENV_FILE" \
    docker compose --env-file "$PRICE_MONITOR_ENV_FILE" "$@"
}

log_postgres() {
  PRICE_MONITOR_ENV_FILE="$PRICE_MONITOR_ENV_FILE" \
    docker compose --env-file "$PRICE_MONITOR_ENV_FILE" logs --no-color --tail=200 postgres || true
}

find_latest_dump() {
  ls -t "$BASE_DIR"/shared/postgres-*-to-"$TARGET_POSTGRES_MAJOR"-*.dump 2>/dev/null \
    | head -n 1 || true
}

wait_for_postgres() {
  for _ in $(seq 1 60); do
    if compose exec -T postgres sh -lc \
      'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "PostgreSQL did not become ready; recent logs follow." >&2
  log_postgres
  return 1
}

write_completion_marker() {
  marker_path="$BASE_DIR/shared/postgres-major-upgrade-${TARGET_POSTGRES_MAJOR}.done"
  {
    echo "release_sha=$RELEASE_SHA"
    echo "dump_path=$1"
    date -u '+completed_at=%Y-%m-%dT%H:%M:%SZ'
  } > "$marker_path"
}

restore_dump() {
  restore_path="$1"

  echo "Restoring PostgreSQL dump $restore_path into target major $TARGET_POSTGRES_MAJOR."
  compose exec -T postgres sh -lc \
    'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl' \
    < "$restore_path"
  write_completion_marker "$restore_path"
  echo "PostgreSQL restore into target major $TARGET_POSTGRES_MAJOR completed."
}

postgres_container="$(compose ps -aq postgres | head -n 1 || true)"
if [ -z "$postgres_container" ]; then
  echo "No existing postgres container found; target major will start with the new stack."
  exit 0
fi

if [ "$(docker inspect -f '{{.State.Running}}' "$postgres_container" 2>/dev/null || echo false)" != "true" ]; then
  latest_dump="$(find_latest_dump)"
  if [ -z "$latest_dump" ]; then
    echo "Existing postgres container is not running, and no prior upgrade dump was found." >&2
    log_postgres
    exit 1
  fi

  echo "Existing postgres container is not running; retrying target major restore from $latest_dump."
  compose up -d postgres
  wait_for_postgres
  restore_dump "$latest_dump"
  exit 0
fi

current_version="$(compose exec -T postgres postgres --version | awk '{print $3}')"
current_major="${current_version%%.*}"
if [ "$current_major" = "$TARGET_POSTGRES_MAJOR" ]; then
  echo "PostgreSQL already on major $TARGET_POSTGRES_MAJOR ($current_version)."
  exit 0
fi

if [ "$current_major" -gt "$TARGET_POSTGRES_MAJOR" ]; then
  echo "Refusing to downgrade PostgreSQL from $current_version to major $TARGET_POSTGRES_MAJOR." >&2
  exit 1
fi

dump_path="$BASE_DIR/shared/postgres-${current_major}-to-${TARGET_POSTGRES_MAJOR}-${RELEASE_SHA}.dump"

echo "Preparing PostgreSQL major upgrade: $current_version -> $TARGET_POSTGRES_MAJOR.x"
compose stop api worker || true
compose exec -T postgres sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "$dump_path"

echo "Dump saved to $dump_path"
echo "Legacy postgres-data volume is retained; restoring into postgres-data-pg18."
compose up -d postgres

wait_for_postgres
restore_dump "$dump_path"
