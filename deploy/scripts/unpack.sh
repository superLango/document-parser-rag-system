#!/usr/bin/env bash
# 离线部署包：合并分卷 + 校验 + 解压（避免手输命令出错）
# 用法: bash unpack.sh <目标目录>   或   bash unpack.sh（默认解压到当前目录）
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$(dirname "$SELF_DIR")"
TARGET="${1:-$(pwd)}"
mkdir -p "$TARGET"

# 分卷文件
PARTS=("$DEPLOY_DIR"/hansondoc-deploy-*.part_*)
if [ ${#PARTS[@]} -eq 0 ]; then
    echo "错误：未找到分卷文件（$DEPLOY_DIR/hansondoc-deploy-*.part_*）"
    exit 1
fi
echo "==> 找到 ${#PARTS[@]} 个分卷："
for p in "${PARTS[@]}"; do ls -lh "$p" | awk '{print "    " $5 "  " $9}'; done

OUT=/tmp/hansondoc-full.tar
echo "==> 合并分卷 -> $OUT"
cat "${PARTS[@]}" > "$OUT"

echo "==> 校验 tar 完整性"
tar -tf "$OUT" >/dev/null
echo "    tar 校验通过（无尾随数据）"

echo "==> 解压到 $TARGET"
tar -xf "$OUT" -C "$TARGET"

echo "==> 完成。开始部署：cd $TARGET && cp .env.example .env && docker compose up -d"
