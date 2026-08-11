#!/usr/bin/env bash
# 启动独立安装的 PostgreSQL 18.4（/home/grainuser/pgsql18，数据目录 /home/grainuser/hansondoc_pgdata18）
set -euo pipefail
/home/grainuser/pgsql18/bin/pg_ctl -D /home/grainuser/hansondoc_pgdata18 -l /tmp/pg18.log start
