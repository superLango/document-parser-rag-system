#!/usr/bin/env bash
# 在本地（Windows Git Bash）把当前代码打成离线更新包：一个 .run 文件。
# 拷到盒子上执行 `bash hanson-update-*.run` 即完成部署（自动备份，可回滚）。说明见同目录 PAIKE.md。
#
# 用法: bash new_app/deploy/offline/make_bundle.sh [web|app|all]
#   web  只更新前端（new_app/web）           —— 不重启后端，不打断解析任务
#   app  只更新后端代码（services/packages/tests）
#   all  两者都更新（默认）
set -euo pipefail

PART=${1:-all}
case "$PART" in web|app|all) ;; *) echo "用法: $0 [web|app|all]" >&2; exit 2 ;; esac

HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(cd "$HERE/../.." && pwd) # new_app
OUT=${OUT:-$HERE/out}
SHA=$(git -C "$APP" rev-parse --short HEAD)
DIRTY=""
if [ -n "$(git -C "$APP" status --porcelain -- .)" ]; then
  DIRTY="-dirty"
  echo "[注意] new_app 下有未提交的改动，也会被打进包里（包名带 -dirty）。部署前最好先提交。"
fi
NAME="hanson-update-$(date +%Y%m%d-%H%M)-$SHA$DIRTY-$PART"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if [ "$PART" != app ]; then
  echo "==> 构建前端"
  (cd "$APP/web" && { [ -d node_modules ] || npm ci; } && npm run build)
  tar czf "$WORK/web-dist.tgz" -C "$APP/web/dist" .
fi

if [ "$PART" != web ]; then
  echo "==> 打包后端代码"
  # 与 deploy/compose/Dockerfile 拷进镜像的内容一致。取 git 里存的内容（LF）而不是 Windows 工作区副本：
  # 工作区是 CRLF，会破坏解析内核资产的 sha256 校验。未提交的修改经 stash create 一并带上（不改动工作区）。
  NEW=$(git -C "$APP" ls-files -o --exclude-standard -- services packages tests)
  [ -z "$NEW" ] || { echo "有未纳入 git 的新文件，先 git add：" >&2; echo "$NEW" >&2; exit 1; }
  REV=$(git -C "$APP" stash create)
  PREFIX=$(git -C "$APP" rev-parse --show-prefix)
  git -C "$(git -C "$APP" rev-parse --show-toplevel)" -c core.autocrlf=false archive --format=tar.gz -o "$WORK/app-src.tgz" \
    "${REV:-HEAD}:${PREFIX%/}" services packages tests requirements.txt
fi

printf 'commit=%s%s\nbranch=%s\npart=%s\nbuilt=%s\n' \
  "$SHA" "$DIRTY" "$(git -C "$APP" rev-parse --abbrev-ref HEAD)" "$PART" "$(date '+%F %T')" > "$WORK/BUNDLE_INFO"
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
