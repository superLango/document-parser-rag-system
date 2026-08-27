hansonDoc_RAG 离线部署包
========================
版本：2026-08-23（全容器化 · 后端与小模型分离）

> 部署产物（镜像 tar、分卷、离线解压）已移出项目目录，存放于：
>   /home/grainuser/hansondoc-release/
>   ├── hansondoc-deploy-20260823.part_aa~ad（分卷，U 盘传输用）
>   ├── images/（镜像 tar）
>   └── offline_test/（部署验证解压）

一、包内容
  images/hansondoc-backend.tar    后端镜像（不含小模型，约 6.3G）
  images/hansondoc-frontend.tar   前端镜像（nginx，约 67M）
  images/pgvector-pg18.tar        PostgreSQL+pgvector 依赖镜像（约 453M）
  images/redis.tar                Redis 依赖镜像（约 41M）
  images/minio.tar                MinIO 文件库/对象存储镜像（约 328M）
  images/mc.tar                   MinIO 客户端（bucket 初始化，约 80M）
  models/bge-m3                   嵌入模型（约 2.6G）
  models/bge-reranker-v2-m3       重排模型（约 2.2G）
  models/pp_doclayoutv3_finetuned_v1  微调版面模型（约 128M）
  docker-compose.yml              编排（6 服务：pg/redis/minio/backend/worker/frontend）
  .env.example                    环境变量模板（复制为 .env 修改）
  initdb/                         数据初始化脚本（01-vector / 02-恢复dump / 03-清理）
  backup/dump.sql                 PostgreSQL 数据备份（已内置，首次启动自动恢复并清理）
  scripts/                        导出/构建/部署脚本（db_export 仅用于重新生成 dump）
  docs/                           部署方案、部署手册、接口对接文档、功能文档

二、部署步骤（目标机）
  1) 解压本包到目标机目录
  2) docker load < images/hansondoc-backend.tar
     docker load < images/hansondoc-frontend.tar
     docker load < images/pgvector-pg18.tar
     docker load < images/redis.tar
     docker load < images/minio.tar
     docker load < images/mc.tar
  3) 将 models/ 三个目录放入项目根（与 docker-compose.yml 同级，保持 ./models/...）
  4) 宿主机启动 vLLM：GLM-OCR(:9977) 与 LLM(:9988)
  5) cp .env.example .env（修改 POSTGRES_PASSWORD 等）
  6) docker compose up -d
     （数据自动初始化：首次启动 PG 自动恢复 backup/dump.sql 并清理，无需手动导出）
  7) 校验：前端 http://<host>:18080 · 后端 http://<host>:18000
     docker exec hansondoc-postgres-1 psql -U hansondoc -d hanson_doc_rag -c "SELECT count(*) FROM knowledge_bases;"  # 期望 1

三、关于 U 盘传输（重要）
  完整 zip 为 13G，FAT32 U 盘无法复制（单文件 4G 上限）。
  本包已拆分为分卷：hansondoc-deploy-20260823.part_aa ~ part_ad（每个 <4G）。
  目标机合并解压：
    cat deploy/hansondoc-deploy-20260823.part_* > /tmp/hansondoc.tar
    tar -xf /tmp/hansondoc.tar -C <部署目录>
  然后按上面第二步开始部署（docker load 等）。

四、改代码后更新
  只重新构建并传输 images/hansondoc-backend.tar（模型目录/前端/数据库不动）。

四、文档
  docs/DOCKER_BUILD_PLAN.md   构建方案
  docs/DOCKER_DEPLOY.md       部署手册
  docs/INTEGRATION_API.md     系统对接接口文档
  docs/EXTRACTION_RESULT_EDIT.md  抽取结果人工编辑功能文档
