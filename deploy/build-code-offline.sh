#!/usr/bin/env bash
# Reuse the running API image; copy code without installing dependencies.
set -euo pipefail

cd -- "${FOLK_GUIDE_DEPLOY_DIR:-$HOME/folk-guide/deploy}"
task_container=$(docker-compose --env-file .env.production ps -q api)
if [[ -z "$task_container" || "$task_container" == *$'\n'* ]]; then
  printf '%s\n' 'Expected exactly one running API container.' >&2
  exit 1
fi
task_base=$(docker inspect --format '{{.Image}}' "$task_container")
task_target=$(docker inspect --format '{{.Config.Image}}' "$task_container")
task_compose_version=$(docker-compose version --short)
# This Compose file has build-only services. V1 uses PROJECT_api even when
# the running container was originally created by V2 as PROJECT-api.
case "$task_compose_version" in
  1.*)
    task_project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$task_container")
    if [[ -z "$task_project" || "$task_project" == '<no value>' ]]; then
      printf '%s\n' 'Missing Compose project label; stopped before building.' >&2
      exit 1
    fi
    task_target="${task_project}_api:latest"
    ;;
esac
case "$task_target" in
  ''|sha256:*|*@*) printf '%s\n' 'API image must have a writable local tag.' >&2; exit 1 ;;
esac

task_context=$(mktemp -d /tmp/folk-guide-code.XXXXXX)
trap 'rm -rf -- "$task_context"' EXIT
docker exec "$task_container" cat /app/requirements.txt > "$task_context/requirements.running"
docker exec "$task_container" cat /app/app/ziwei_runtime/package-lock.json > "$task_context/package-lock.running"
if ! cmp -s "$task_context/requirements.running" ../backend/requirements.txt ||
   ! cmp -s "$task_context/package-lock.running" ../backend/app/ziwei_runtime/package-lock.json; then
  printf '%s\n' 'Dependency manifests differ; stopped without downloading.' >&2
  exit 1
fi

task_backup="folk-guide-api-backup:$(date +%Y%m%d-%H%M%S)"
docker image inspect "$task_base" >/dev/null
docker tag "$task_base" "$task_backup"
tar -C .. --exclude=node_modules --exclude=__pycache__ --exclude='*.pyc' \
  -cf - backend/app alembic alembic.ini | tar -C "$task_context" -xf -
cat > "$task_context/Dockerfile" <<'DOCKERFILE'
ARG LOCAL_BASE
FROM ${LOCAL_BASE}
WORKDIR /app
COPY --chown=10001:10001 backend/app/ /app/app/
COPY --chown=10001:10001 alembic/ /app/alembic/
COPY --chown=10001:10001 alembic.ini /app/alembic.ini
DOCKERFILE
DOCKER_BUILDKIT=0 docker build --network=none --pull=false \
  --build-arg "LOCAL_BASE=$task_backup" -t "$task_target" "$task_context"
printf 'CODE_IMAGE_OK\nPrevious image: %s\n' "$task_backup"
