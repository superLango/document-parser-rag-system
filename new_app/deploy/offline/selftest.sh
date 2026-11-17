#!/usr/bin/env bash
# install.sh 自测（本地 Git Bash 即可，不需要真 docker）：
#   假 docker 记录调用并模拟 recipe-registry，假网关/页面用 python http.server，在临时 HOME 里跑部署、回滚和各项拦截。
# 用法: bash new_app/deploy/offline/selftest.sh <make_bundle.sh all --parser 1.7.999 --dict pk 生成的 .run>
set -uo pipefail
case "${1:-}" in *-all-parser*-pk.run) ;; *) echo "需要 make_bundle.sh all --parser <版本> --dict pk 生成的 .run" >&2; exit 2 ;; esac
RUN=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
VER=$(basename "$RUN" | sed 's/.*-parser\([0-9.]*\)-pk\.run/\1/')
APP=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
export HOME="$T/home" LOG="$T/docker.log" REQ="$T/req.txt" MIG="$T/mig.txt" REGSTATE="$T/registry.txt"
D="$HOME/hanson-deploy/deploy-package"
PY=$(command -v python3 >/dev/null && python3 -c '' 2>/dev/null && echo python3 || echo python)
mkdir -p "$D/web-dist" "$D/data/orchestration/dictionary" "$D/data/recipe_registry" "$T/bin" "$T/srv/v1"
printf 'GATEWAY_PORT=18911\nWEB_PORT=18912\n' > "$D/.env"
printf 'services:\n  web:\n    volumes:\n      - ./web-dist:/usr/share/nginx/html:ro\n' > "$D/docker-compose.yml"
echo '{}' > "$D/data/recipe_registry/registry.json"
echo ok > "$T/srv/healthz"
echo '<script src="/assets/index-TEST.js">' > "$T/srv/index.html"
cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$LOG"
case "$1" in
  image) [ "$3" = hanson-new-app:local ] || grep -q "tag hanson-new-app:local hanson-new-app:base" "$LOG" ;;
  run) case "$*" in *requirements.txt) cat "$REQ" ;; *) cat "$MIG" ;; esac ;;
  inspect) echo healthy ;;
  exec)
    case "$*" in
      *pg_dump*) echo "-- fake dump" ;;
      *" python - state") cat "$REGSTATE" ;;
      *" python - promote "*)
        v=$(echo "$*" | sed 's/.* promote \([^ ]*\) .*/\1/')
        rest=$(cut -d' ' -f2- "$REGSTATE"); echo "$v $rest" > "$REGSTATE"; echo "$v" ;;
      *publish_parser_asset.py*)
        v=$(echo "$*" | sed 's/.*--version \([^ ]*\).*/\1/'); echo "$(cat "$REGSTATE") $v" > "$REGSTATE" ;;
    esac ;;
  *) exit 0 ;;
esac
EOF
printf '#!/usr/bin/env bash\nexec %s "$@"\n' "$PY" > "$T/bin/python3"
chmod +x "$T/bin/docker" "$T/bin/python3"
export PATH="$T/bin:$PATH"
"$PY" -m http.server 18911 --directory "$T/srv" >/dev/null 2>&1 & S1=$!
"$PY" -m http.server 18912 --directory "$T/srv" >/dev/null 2>&1 & S2=$!
trap 'kill $S1 $S2 2>/dev/null; rm -rf "$T"' EXIT
sleep 2

fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }
reset() {
  rm -rf "$HOME/hanson-deploy/backups" "$D/web-dist"; mkdir -p "$D/web-dist"; echo old > "$D/web-dist/index.html"
  : > "$LOG"; tr -d '\r' < "$APP/requirements.txt" > "$REQ"; ls "$APP/services/orchestration/migrations/versions" > "$MIG"
  echo '[{"status":"HUMAN_REVIEW"}]' > "$T/srv/v1/runs"
  echo '{"version": "paike-lims-test"}' > "$D/data/orchestration/dictionary/business_dictionary.json"
  echo "1.7.901 1.7.900 1.7.901" > "$REGSTATE"
}
bk() { ls -d "$HOME"/hanson-deploy/backups/2* 2>/dev/null | head -1; }
stable() { cut -d' ' -f1 "$REGSTATE"; }

echo "1) 部署 + 回滚（后端、前端、解析内核 $VER）"
reset
bash "$RUN" > "$T/out" 2>&1; check "部署成功" "[ $? = 0 ]"
check "前端已替换" "[ -d '$D/web-dist/assets' ]"
check "镜像先定基底再构建" "grep -q 'tag hanson-new-app:local hanson-new-app:base' '$LOG' && grep -q 'docker build' '$LOG'"
check "无新迁移时不导出数据库" "! grep -q pg_dump '$LOG'"
check "发布了 $VER 并设为 stable" "grep -q 'publish_parser_asset.py.*--version $VER' '$LOG' && [ \"\$(stable)\" = $VER ]"
check "重启了 recipe-registry" "grep -q 'restart hanson-recipe-registry-1' '$LOG'"
check "备份了 registry 数据与原 stable" "[ -s \"\$(bk)/recipe_registry.tgz\" ] && grep -qx 1.7.901 \"\$(bk)/parser-stable\""
bash "$RUN" rollback > "$T/out" 2>&1; check "回滚成功" "[ $? = 0 ]"
check "前端已还原" "grep -q old '$D/web-dist/index.html'"
check "镜像已还原" "grep -q 'tag hanson-new-app:bak-' '$LOG'"
check "stable 已切回 1.7.901" "[ \"\$(stable)\" = 1.7.901 ]"
bash "$RUN" rollback > "$T/out" 2>&1; check "无备份时回滚报错" "[ $? != 0 ] && grep -q 没有可回滚 '$T/out'"

echo "2) 有解析任务进行中 → 拒绝，且不留备份"
reset; echo '[{"status":"SANDBOX_RUNNING"}]' > "$T/srv/v1/runs"
bash "$RUN" > "$T/out" 2>&1; check "被拦截" "[ $? != 0 ] && grep -q 解析任务进行中 '$T/out'"
check "未改动" "[ -z \"\$(bk)\" ] && grep -q old '$D/web-dist/index.html'"

echo "3) requirements.txt 变了 → 拒绝"
reset; echo "extra==1.0" >> "$REQ"
bash "$RUN" > "$T/out" 2>&1; check "被拦截" "[ $? != 0 ] && grep -q requirements '$T/out'"

echo "4) 有新的数据库迁移 → 先导出数据库"
reset; sed -i '$d' "$MIG"
bash "$RUN" > "$T/out" 2>&1; check "部署成功" "[ $? = 0 ]"
check "已导出数据库" "[ -s \"\$(bk)/db.sql.gz\" ]"
bash "$RUN" rollback > "$T/out" 2>&1; check "回滚时提示迁移" "grep -q 数据库迁移 '$T/out'"

echo "5) 派克词典的包装到汉唐盒子 → 拒绝，且未改动"
reset; echo '{"version": "hanson-ht-xlsx-test"}' > "$D/data/orchestration/dictionary/business_dictionary.json"
bash "$RUN" > "$T/out" 2>&1; check "被拦截" "[ $? != 0 ] && grep -q '本机业务词典是「hanson' '$T/out'"
check "未改动" "[ -z \"\$(bk)\" ] && [ \"\$(stable)\" = 1.7.901 ] && ! grep -q 'docker build' '$LOG'"

echo "6) $VER 已是 stable → 跳过发布"
reset; echo "$VER 1.7.901 $VER" > "$REGSTATE"
bash "$RUN" > "$T/out" 2>&1; check "部署成功" "[ $? = 0 ]"
check "没有重新发布" "! grep -q publish_parser_asset '$LOG' && grep -q 跳过发布 '$T/out'"

echo "7) $VER 已发布但不是 stable → 只切换"
reset; echo "1.7.901 1.7.901 $VER" > "$REGSTATE"
bash "$RUN" > "$T/out" 2>&1; check "部署成功" "[ $? = 0 ]"
check "没有重新发布、已切到 $VER" "! grep -q publish_parser_asset '$LOG' && [ \"\$(stable)\" = $VER ]"

[ $fail = 0 ] && echo "全部通过" || { echo "有失败，最后一次输出:"; cat "$T/out"; exit 1; }
