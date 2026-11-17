#!/bin/sh
# 在 WSL 内通过 ssh 执行本地脚本：remote-exec.sh <user@host> <本地脚本路径>
# 依赖：/mnt/c/Users/lango/AppData/Local/Temp/htjc_askpass.sh 提供密码
set -e
HOST="$1"
SCRIPT="$2"
ASKPASS=${ASKPASS_HELPER:-/mnt/c/Users/lango/AppData/Local/Temp/htjc_askpass.sh}
export SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force DISPLAY=:0
sed -i 's/\r$//' "$SCRIPT" 2>/dev/null || true
exec setsid -w ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=10 -o LogLevel=ERROR "$HOST" 'bash -s' < "$SCRIPT"
