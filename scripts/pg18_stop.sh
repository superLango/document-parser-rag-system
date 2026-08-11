#!/usr/bin/env bash
# 停止 PostgreSQL 18.4 实例
set -euo pipefail
/home/grainuser/pgsql18/bin/pg_ctl -D /home/grainuser/hansondoc_pgdata18 stop -m fast
