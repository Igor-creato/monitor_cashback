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

postgres_container="$(compose ps -q postgres || true)"
if [ -z "$postgres_container" ]; then
  echo "No existing postgres container found; target major will start with the new stack."
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
echo "Legacy postgres-data volume is retained; restoring into postgres-data-v18."
compose up -d postgres

for _ in $(seq 1 60); do
  if compose exec -T postgres sh -lc \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

compose exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
compose exec -T postgres sh -lc \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl' \
  < "$dump_path"

echo "PostgreSQL restore into target major $TARGET_POSTGRES_MAJOR completed."
