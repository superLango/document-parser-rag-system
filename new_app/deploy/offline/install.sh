#!/usr/bin/env bash
# 汉唐标准拆分平台 · 盒子离线更新。make_bundle.sh 生成的 .run 文件头部就是本脚本，尾部是更新内容。
#
# 用法（在盒子上，普通用户，需在 docker 组）:
#   bash hanson-update-*.run              部署（自动备份）
#   bash hanson-update-*.run rollback     回滚最近一次部署（再执行一次回滚更早的一次）
#   FORCE=1 bash hanson-update-*.run      有解析任务进行中也强制部署（会中断这些任务）
#
# 不会动: .env、业务数据、数据库与对象存储、模型服务、hanson-layout 容器。
# 包内带解析内核时会在 recipe-registry 新增一个版本并设为 stable（先备份 data/recipe_registry）。
set -euo pipefail

DEPLOY=${HANSON_DEPLOY:-$HOME/hanson-deploy/deploy-package}
BACKUPS=${HANSON_BACKUPS:-$HOME/hanson-deploy/backups}
PROJECT=${HANSON_PROJECT:-hanson}
IMAGE=hanson-new-app:local
BASE=hanson-new-app:base # 首次部署时的原始镜像；每次只在它上面叠一层新代码，镜像不会越叠越大
WEB="$PROJECT-web-1"
ORCH="$PROJECT-orchestration-1"
REG="$PROJECT-recipe-registry-1"
BOX_DICT="$DEPLOY/data/orchestration/dictionary/business_dictionary.json"
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

# recipe-registry 的端口不对宿主开放，经 orchestration 容器调用。
#   registry state            -> "<stable> <全部版本...>"
#   registry promote <v> <备注> -> 把 <v> 设为 stable
registry() {
  docker exec -i "$ORCH" python - "$@" <<'PY'
import json, sys, urllib.request
api = "http://recipe-registry:8005/internal/assets/parser/parser_core"
if sys.argv[1] == "state":
    d = json.load(urllib.request.urlopen(api, timeout=10))
    versions = [v.get("version") if isinstance(v, dict) else v for v in d.get("versions", [])]
    print(d["channels"].get("stable", ""), *versions)
elif sys.argv[1] == "promote":
    body = {"channel": "stable", "actor": "offline-install", "note": sys.argv[3]}
    req = urllib.request.Request(
        f"{api}/versions/{sys.argv[2]}/promote",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(json.load(urllib.request.urlopen(req, timeout=20))["version"])
PY
}

wait_healthy() {
  for _ in $(seq 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ] && return 0
    sleep 3
  done
  die "$1 未就绪：docker logs --tail 50 $1"
}

# 本机业务词典的版本标识：派克 paike-...，汉唐 hanson-...
box_dict() {
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("version", ""))' "$BOX_DICT" 2>/dev/null || true
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
    docker run --rm --entrypoint cat "$BASE" /app/requirements.txt | diff -q --strip-trailing-cr - "$tmp/app/requirements.txt" >/dev/null ||
      die "requirements.txt 与镜像内不同（新增/变更了 Python 依赖），离线覆盖代码装不了依赖，见 PAIKE.md「新增依赖」"
  fi
  local pver="" pdict="" pstable="" pversions="" pmode=""
  if [ -f "$tmp/parser.tgz" ]; then
    mkdir "$tmp/parser"
    tar xzf "$tmp/parser.tgz" -C "$tmp/parser"
    pver=$(sed -n 's/^version=//p' "$tmp/parser/PARSER_INFO")
    pdict=$(sed -n 's/^dict=//p' "$tmp/parser/PARSER_INFO")
    local bdict
    bdict=$(box_dict)
    # 防止把汉唐词典的内核发到派克（或反过来）
    case "$pdict:$bdict" in
      pk:paike* | ht:hanson*) ;;
      *) die "包里的解析内核用的是 $pdict 词典，但本机业务词典是「${bdict:-读不到}」。派克用 --dict pk，汉唐用 --dict ht" ;;
    esac
    read -r pstable pversions <<<"$(registry state)" || true
    [ -n "$pstable" ] || die "读不到 recipe-registry 的解析内核状态（docker logs --tail 50 $REG）"
    if [ "$pstable" = "$pver" ]; then
      pmode=skip
    elif [[ " $pversions " == *" $pver "* ]]; then
      pmode=promote # 之前发布过（版本不可变），只切换 stable
    else
      pmode=publish
    fi
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

  if [ "$pmode" = skip ]; then
    say "解析内核 $pver 已是 stable，跳过发布"
  elif [ -n "$pmode" ]; then
    say "解析内核：$pstable → $pver（词典 $pdict），原数据备份到 $bk/recipe_registry.tgz"
    tar czf "$bk/recipe_registry.tgz" -C "$DEPLOY/data" recipe_registry
    echo "$pstable" > "$bk/parser-stable"
    wait_healthy "$ORCH"
    wait_healthy "$REG"
    if [ "$pmode" = publish ]; then
      docker exec "$ORCH" rm -rf /tmp/parser-pub
      docker cp "$tmp/parser" "$ORCH:/tmp/parser-pub"
      docker exec "$ORCH" python /tmp/parser-pub/scripts/assets/publish_parser_asset.py \
        --api http://recipe-registry:8005 --version "$pver" --actor offline-install --note "offline install $stamp ($pdict)"
      docker exec "$ORCH" rm -rf /tmp/parser-pub
    fi
    registry promote "$pver" "offline install $stamp" >/dev/null
    docker restart "$REG" >/dev/null
    wait_healthy "$REG"
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
  if [ -n "$pver" ]; then
    pstable=$(registry state | cut -d' ' -f1) || true
    echo "  解析内核 stable: $pstable"
    [ "$pstable" = "$pver" ] || die "解析内核 stable 是 $pstable，不是 $pver。需要回滚: bash $SELF rollback"
  fi
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
  if [ -f "$bk/parser-stable" ]; then
    # 新发布的版本保留在 registry 里（版本不可变），只把 stable 指回去
    wait_healthy "$ORCH"
    wait_healthy "$REG"
    registry promote "$(cat "$bk/parser-stable")" "rollback $(basename "$bk")" >/dev/null
    docker restart "$REG" >/dev/null
    wait_healthy "$REG"
    echo "  解析内核 stable 已切回 $(cat "$bk/parser-stable")"
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
