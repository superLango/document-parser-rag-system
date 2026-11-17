#!/usr/bin/env bash
# 在本地（Windows Git Bash）把当前代码打成离线更新包：一个 .run 文件。
# 拷到盒子上执行 `bash hanson-update-*.run` 即完成部署（自动备份，可回滚）。说明见同目录 PAIKE.md。
#
# 用法: bash new_app/deploy/offline/make_bundle.sh [web|app|all] [--parser <版本> --dict <ht|pk>]
#   web  只更新前端（new_app/web）           —— 不重启后端，不打断解析任务
#   app  只更新后端代码（services/packages/tests）
#   all  两者都更新（默认）
#   --parser 1.7.902 --dict pk   另外发布解析内核：当前 sandbox runtime 代码 + dict/<ht|pk>/dictionary_data.json，
#                                在盒子上发布为该版本并设为 stable、重启 recipe-registry
set -euo pipefail

PART=all
PARSER=""
DICT=""
while [ $# -gt 0 ]; do
  case "$1" in
    web | app | all) PART=$1 ;;
    --parser) PARSER=${2:-}; shift ;;
    --dict) DICT=${2:-}; shift ;;
    *) echo "用法: $0 [web|app|all] [--parser <版本> --dict <ht|pk>]" >&2; exit 2 ;;
  esac
  shift
done
if [ -n "$PARSER$DICT" ]; then
  [[ "$PARSER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "--parser 需要 X.Y.Z 版本号" >&2; exit 2; }
  case "$DICT" in ht | pk) ;; *) echo "--dict 必须是 ht（汉唐）或 pk（派克）" >&2; exit 2 ;; esac
fi

HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(cd "$HERE/../.." && pwd) # new_app
ROOT=$(git -C "$APP" rev-parse --show-toplevel)
OUT=${OUT:-$HERE/out}
SHA=$(git -C "$APP" rev-parse --short HEAD)
DIRTY=""
if [ -n "$(git -C "$ROOT" status --porcelain -- new_app dict)" ]; then
  DIRTY="-dirty"
  echo "[注意] new_app 或 dict 下有未提交的改动，也会被打进包里（包名带 -dirty）。部署前最好先提交。"
fi
NAME="hanson-update-$(date +%Y%m%d-%H%M)-$SHA$DIRTY-$PART${PARSER:+-parser$PARSER-$DICT}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
# 取 git 里存的内容（LF）而不是 Windows 工作区副本：工作区是 CRLF，会破坏解析内核资产的 sha256 校验。
# 未提交的修改经 stash create 一并带上（不改动工作区）。
REV=$(git -C "$ROOT" stash create)
REV=${REV:-HEAD}
gitx() { git -C "$ROOT" -c core.autocrlf=false "$@"; }

if [ "$PART" != app ]; then
  echo "==> 构建前端"
  (cd "$APP/web" && { [ -d node_modules ] || npm ci; } && npm run build)
  tar czf "$WORK/web-dist.tgz" -C "$APP/web/dist" .
fi

if [ "$PART" != web ]; then
  echo "==> 打包后端代码"
  # 与 deploy/compose/Dockerfile 拷进镜像的内容一致
  NEW=$(git -C "$APP" ls-files -o --exclude-standard -- services packages tests)
  [ -z "$NEW" ] || { echo "有未纳入 git 的新文件，先 git add：" >&2; echo "$NEW" >&2; exit 1; }
  gitx archive --format=tar.gz -o "$WORK/app-src.tgz" "$REV:new_app" services packages tests requirements.txt
fi

if [ -n "$PARSER" ]; then
  echo "==> 打包解析内核 $PARSER（词典 dict/$DICT）"
  # 结构与仓库一致，盒子上 publish_parser_asset.py 按自身位置找到 services/sandbox/runtime
  P="$WORK/parser"
  mkdir -p "$P/scripts/assets" "$P/services/sandbox/runtime"
  gitx show "$REV:new_app/scripts/assets/publish_parser_asset.py" > "$P/scripts/assets/publish_parser_asset.py"
  gitx archive "$REV:new_app/services/sandbox/runtime" | tar xf - -C "$P/services/sandbox/runtime"
  gitx show "$REV:dict/$DICT/dictionary_data.json" > "$P/services/sandbox/runtime/dictionary_data.json"
  printf 'version=%s\ndict=%s\n' "$PARSER" "$DICT" > "$P/PARSER_INFO"
  tar czf "$WORK/parser.tgz" -C "$P" .
  rm -rf "$P"
fi

printf 'commit=%s%s\nbranch=%s\npart=%s\nparser=%s\nbuilt=%s\n' \
  "$SHA" "$DIRTY" "$(git -C "$APP" rev-parse --abbrev-ref HEAD)" "$PART" "${PARSER:+$PARSER ($DICT)}" "$(date '+%F %T')" > "$WORK/BUNDLE_INFO"
(cd "$WORK" && tar czf payload.tgz --exclude=payload.tgz ./*)

mkdir -p "$OUT"
# 头部是盒子上运行的 install.sh（去掉 Windows 换行），标记行之后是二进制负载
{ tr -d '\r' < "$HERE/install.sh"; echo "__PAYLOAD__"; cat "$WORK/payload.tgz"; } > "$OUT/$NAME.run"

echo
echo "完成: $OUT/$NAME.run ($(du -h "$OUT/$NAME.run" | cut -f1))"
cat "$WORK/BUNDLE_INFO"
echo
echo "部署: 把该文件拷到盒子（scp 或 U 盘）后执行  bash $NAME.run"
echo "回滚: bash $NAME.run rollback"
