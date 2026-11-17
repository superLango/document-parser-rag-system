#!/bin/sh
# 从 WSL 传文件到远端：remote-rsync.sh <user@host> <本地路径> <远端路径> [额外 rsync 参数]
set -e
HOST="$1"; SRC="$2"; DST="$3"; shift 3
ASKPASS=${ASKPASS_HELPER:-/mnt/c/Users/lango/AppData/Local/Temp/htjc_askpass.sh}
export SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force DISPLAY=:0
exec setsid -w rsync -az --partial \
  -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  "$@" "$SRC" "$HOST:$DST"
