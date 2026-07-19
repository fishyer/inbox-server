#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
DEPLOY_ROOT="${INBOX_DEPLOY_ROOT:-$(dirname "$(dirname "$SCRIPT_DIR")")}"
SHARED_DIR="${INBOX_SHARED_DIR:-$DEPLOY_ROOT/shared}"
COMPOSE_PROJECT="${INBOX_COMPOSE_PROJECT:-inbox-server}"
DEPLOY_TIMEOUT="${INBOX_DEPLOY_TIMEOUT_SECONDS:-180}"
HEALTH_URL="${INBOX_HEALTH_URL:-http://127.0.0.1:8000/healthz}"

for config_name in .env channels.yaml; do
  shared_config="$SHARED_DIR/$config_name"
  test -s "$shared_config" || {
    printf '共享配置不存在或为空：%s\n' "$shared_config" >&2
    exit 1
  }
  ln -sfn "$shared_config" "$SCRIPT_DIR/$config_name"
done

compose() {
  docker compose \
    -p "$COMPOSE_PROJECT" \
    --env-file "$SCRIPT_DIR/.env" \
    -f "$SCRIPT_DIR/docker-compose.yml" \
    "$@"
}

docker compose version >/dev/null
compose config --quiet
compose up -d --build --remove-orphans --wait --wait-timeout "$DEPLOY_TIMEOUT"

running_services="$(compose ps --services --status running)"
for service in postgres redis server worker console; do
  printf '%s\n' "$running_services" | grep -Fqx "$service" || {
    printf '服务未运行：%s\n' "$service" >&2
    exit 1
  }
  container_id="$(compose ps -q "$service")"
  test -n "$container_id"
  restart_policy="$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$container_id")"
  test "$restart_policy" = "unless-stopped" || {
    printf '服务 %s 的重启策略不是 unless-stopped\n' "$service" >&2
    exit 1
  }
done

docker volume inspect \
  "${COMPOSE_PROJECT}_pgdata" \
  "${COMPOSE_PROJECT}_redisdata" >/dev/null
curl -fsS "$HEALTH_URL" >/dev/null

printf 'inbox-server 部署完成：release=%s project=%s\n' \
  "${DEPLOY_RELEASE_TAG:-unknown}" "$COMPOSE_PROJECT"
