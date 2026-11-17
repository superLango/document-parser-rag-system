#!/usr/bin/env bash
# 汉唐标准拆分平台 · 盒子离线更新。make_bundle.sh 生成的 .run 文件头部就是本脚本，尾部是更新内容。
#
# 用法（在盒子上，普通用户，需在 docker 组）:
#   bash hanson-update-*.run              部署（自动备份）
#   bash hanson-update-*.run rollback     回滚最近一次部署（再执行一次回滚更早的一次）
#   FORCE=1 bash hanson-update-*.run      有解析任务进行中也强制部署（会中断这些任务）
#
# 不会动: .env、data/、数据库与对象存储、模型服务、hanson-layout 容器。
set -euo pipefail

DEPLOY=${HANSON_DEPLOY:-$HOME/hanson-deploy/deploy-package}
BACKUPS=${HANSON_BACKUPS:-$HOME/hanson-deploy/backups}
PROJECT=${HANSON_PROJECT:-hanson}
IMAGE=hanson-new-app:local
BASE=hanson-new-app:base # 首次部署时的原始镜像；每次只在它上面叠一层新代码，镜像不会越叠越大
WEB="$PROJECT-web-1"
SELF=$0

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }
compose() { (cd "$DEPLOY" && docker compose -p "$PROJECT" --env-file .env -f docker-compose.yml "$@"); }
env_port() { sed -n "s/^$1=//p" "$DEPLOY/.env" 2>/dev/null | tail -1 | tr -d '\r"'; }
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" || true; }

API=${API:-http://127.0.0.1:$(env_port GATEWAY_PORT || true)}
PAGE=${PAGE:-http://127.0.0.1:$(env_port WEB_PORT || true)}
[ "$API" = "http://127.0.0.1:" ] && API=http://127.0.0.1:18000
[ "$PAGE" = "http://127.0.0.1:" ] && PAGE=http://127.0.0.1:18080

# 进行中（未到终态）的解析任务数；网关不可达时按 0 处理
busy_runs() {
  curl -fsS --max-time 5 "$API/v1/runs" 2>/dev/null | python3 -c '
import json, sys
done = {"STRUCTURED_READY","REVIEW_FAILED","HUMAN_REVIEW","HUMAN_APPROVED","HUMAN_REJECTED","UNROUTED","FAILED","CANCELLED"}
print(sum(r.get("status") not in done for r in json.load(sys.stdin)))' 2>/dev/null || echo 0
}

verify() {
  say "等待服务就绪（最多 3 分钟）"
  local a w
  for _ in $(seq 60); do
    a=$(http_code "$API/healthz"); w=$(http_code "$PAGE/healthz")
    [ "$a$w" = 200200 ] && break
    sleep 3
  done
  echo "  网关 $API/healthz = $a"
  echo "  页面 $PAGE/healthz = $w"
  echo "  页面前端版本: $(curl -s --max-time 5 "$PAGE/" | grep -o 'index-[A-Za-z0-9_-]*\.js' | head -1)"
  compose ps --format 'table {{.Name}}\t{{.Status}}' || true
  [ "$a$w" = 200200 ] || die "服务未就绪。查看日志: docker logs --tail 50 $PROJECT-api-gateway-1 ；需要回滚: bash $SELF rollback"
}

preflight() {
  [ -f "$DEPLOY/docker-compose.yml" ] && [ -f "$DEPLOY/.env" ] || die "找不到部署目录 $DEPLOY（可用 HANSON_DEPLOY=... 指定）"
  docker info >/dev/null 2>&1 || die "docker 不可用（当前用户需在 docker 组）"
}

do_install() {
  local line stamp bk n
  line=$(awk '/^__PAYLOAD__$/ { print NR + 1; exit }' "$SELF")
  [ -n "$line" ] || die "本文件不含更新内容。请用 make_bundle.sh 生成的 .run 文件部署"
  preflight
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  tail -n +"$line" "$SELF" | tar xzf - -C "$tmp" || die "更新包损坏（拷贝不完整？）"
  say "更新包"
  sed 's/^/  /' "$tmp/BUNDLE_INFO"

  # 先做全部检查，再动任何东西
  if [ -f "$tmp/web-dist.tgz" ]; then
    grep -q '\./web-dist:/usr/share/nginx/html' "$DEPLOY/docker-compose.yml" ||
      die "docker-compose.yml 的 web 服务没有挂载 ./web-dist（派克已配置；其他盒子见 PAIKE.md「前端挂载」）"
  fi
  if [ -f "$tmp/app-src.tgz" ]; then
    n=$(busy_runs)
    [ "$n" = 0 ] || [ "${FORCE:-}" = 1 ] ||
      die "有 $n 个解析任务进行中，重启后端会中断它们。等完成后再部署，或 FORCE=1 bash $SELF"
    docker image inspect "$IMAGE" >/dev/null 2>&1 || die "本机没有镜像 $IMAGE"
    docker image inspect "$BASE" >/dev/null 2>&1 || docker tag "$IMAGE" "$BASE"
    mkdir "$tmp/app"
    tar xzf "$tmp/app-src.tgz" -C "$tmp/app"
    docker run --rm --entrypoint cat "$BASE" /app/requirements.txt | diff -q - "$tmp/app/requirements.txt" >/dev/null ||
      die "requirements.txt 与镜像内不同（新增/变更了 Python 依赖），离线覆盖代码装不了依赖，见 PAIKE.md「新增依赖」"
  fi

  stamp=$(date +%Y%m%d-%H%M%S)
  bk="$BACKUPS/$stamp"
  mkdir -p "$bk"
  cp "$tmp/BUNDLE_INFO" "$bk/"

  if [ -f "$tmp/app-src.tgz" ]; then
    # 新的数据库迁移会在 orchestration 启动时自动执行，回滚镜像退不回表结构，所以先导出数据库
    local mig=services/orchestration/migrations/versions
    if [ -n "$(comm -13 <(docker run --rm --entrypoint ls "$IMAGE" "/app/$mig" | sort) <(ls "$tmp/app/$mig" | sort))" ]; then
      say "本次含新的数据库迁移，先备份数据库到 $bk/db.sql.gz"
      docker exec "$PROJECT-postgres-1" sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$bk/db.sql.gz" ||
        die "数据库备份失败，已停止（尚未改动任何服务）"
    fi
    say "更新后端镜像（基于 $BASE 覆盖代码）"
    docker tag "$IMAGE" "hanson-new-app:bak-$stamp"
    echo "hanson-new-app:bak-$stamp" > "$bk/app-image"
    printf '%s\n' "FROM $BASE" \
      "RUN rm -rf /app/services /app/packages /app/tests" \
      "COPY services /app/services" "COPY packages /app/packages" "COPY tests /app/tests" > "$tmp/app/Dockerfile.offline"
    docker build -q -t "$IMAGE" -f "$tmp/app/Dockerfile.offline" "$tmp/app"
    say "重建后端容器"
    compose up -d --no-build --pull never
  fi

  if [ -f "$tmp/web-dist.tgz" ]; then
    say "更新前端"
    if [ -d "$DEPLOY/web-dist" ]; then mv "$DEPLOY/web-dist" "$bk/web-dist"; fi
    mkdir "$DEPLOY/web-dist"
    tar xzf "$tmp/web-dist.tgz" -C "$DEPLOY/web-dist"
    docker restart "$WEB" >/dev/null
  fi

  echo "$stamp install $(tr '\n' ' ' < "$tmp/BUNDLE_INFO")" >> "$BACKUPS/history.log"
  verify
  say "部署完成。备份在 $bk ；回滚: bash $SELF rollback"
}

do_rollback() {
  local bk
  preflight
  if [ -n "${1:-}" ]; then bk="$BACKUPS/$1"; else bk=$(ls -d "$BACKUPS"/2*[0-9] 2>/dev/null | tail -1 || true); fi
  [ -n "$bk" ] && [ -d "$bk" ] || die "没有可回滚的备份（$BACKUPS）"
  say "回滚 $bk 这次部署"
  sed 's/^/  /' "$bk/BUNDLE_INFO" 2>/dev/null || true
  if [ -f "$bk/app-image" ]; then
    docker tag "$(cat "$bk/app-image")" "$IMAGE"
    compose up -d --no-build --pull never
  fi
  if [ -d "$bk/web-dist" ]; then
    rm -rf "$DEPLOY/web-dist"
    mv "$bk/web-dist" "$DEPLOY/web-dist"
    docker restart "$WEB" >/dev/null
  fi
  if [ -f "$bk/db.sql.gz" ]; then
    echo "  [注意] 那次部署执行过数据库迁移，回滚镜像不会回退表结构。若服务报数据库错误，"
    echo "         用 $bk.rolled-back/db.sql.gz 恢复数据库（会丢失之后的新数据，先找开发确认）。"
  fi
  mv "$bk" "$bk.rolled-back"
  echo "$(date +%Y%m%d-%H%M%S) rollback $(basename "$bk")" >> "$BACKUPS/history.log"
  verify
  say "已回滚到 $(basename "$bk") 之前的版本"
}

case "${1:-install}" in
  install) do_install ;;
  rollback) do_rollback "${2:-}" ;;
  *) sed -n '2,10p' "$SELF"; exit 2 ;;
esac
exit 0
