---
name: paike-deploy
description: 派克（Paike）客户盒子的架构与离线部署。用户提到派克、派克盒子、192.168.70.161、离线部署、打更新包、.run 更新包、把本地改动部署到盒子，或要改离线部署脚本时使用。
---

# 派克盒子离线部署

1. 先完整读 `new_app/deploy/offline/PAIKE.md`：盒子架构、端口、目录、镜像、与汉唐 01 的差异、各类改动的部署方式、脚本扩展规则。
2. 盒子平时离线。默认流程：在本地提交改动 → `bash new_app/deploy/offline/make_bundle.sh [web|app|all]` 生成 `.run` → 用户拷到盒子执行 `bash <包>.run`（回滚 `bash <包>.run rollback`）。
3. 判断改动类型选 `web` / `app` / `all`：只动 `new_app/web` 用 `web`（不打断解析任务）；动了 `requirements.txt`、nginx、compose、.env、词典 / 解析内核时，脚本不覆盖，按 PAIKE.md 第 6 节处理。
4. 改了 `make_bundle.sh` / `install.sh` 后，必须用 `make_bundle.sh all` 打包并跑 `bash new_app/deploy/offline/selftest.sh <*-all.run>` 全部通过；新增能力同时补 selftest 用例和 PAIKE.md 第 6 节。
5. 盒子在线时（`ssh -o BatchMode=yes yzling@192.168.70.161 true` 能通）可以代用户 scp 并执行，但先确认没有进行中的解析任务，执行前告诉用户。

约束：只用公钥 SSH，不输入任何密码 / sudo 密码；不打印 `.env`；不删 `hansondoc-backend:latest`、`hanson-new-app:base`、老项目 `~/hansonDoc_RAG` 的数据卷；不碰模型进程；盒子事实与 PAIKE.md 不符时以 `docker ps` / `docker inspect` 为准并更新 PAIKE.md。
