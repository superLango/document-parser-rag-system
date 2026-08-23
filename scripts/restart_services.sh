#!/usr/bin/env bash
# 清理并重启 后端 + arq + 前端（避免重复进程累积导致任务重复消费/端口冲突）。
set -euo pipefail

cd /home/grainuser/hansonDoc_RAG

# 收集自身进程树，避免误杀执行环境（命令行可能含模式字样）
keep="$PPID"
pid="$PPID"
while [ "$pid" != "1" ] && [ -n "$pid" ]; do
    npid=$(awk '/^PPid:/{print $2}' /proc/"$pid"/status 2>/dev/null || true)
    [ "$npid" = "$pid" ] && break
    keep="$keep $npid"
    pid="$npid"
done

for pat in "uvicorn app.main" "arq app.tasks.arq_worker" "vite"; do
    while read -r pid args; do
        case " $keep " in
            *" $pid "*) continue ;;
        esac
        case "$args" in
            *"$pat"*) kill "$pid" 2>/dev/null || true ;;
        esac
    done < <(ps -eo pid=,args=)
done

sleep 3
bash scripts/start_services.sh
