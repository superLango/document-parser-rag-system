# 派克盒子 · 架构与离线部署手册

本文件给两类读者：**开发者**（本地开发完怎么部署到派克盒子）和 **AI 助手**（新会话里快速了解派克盒子，不再重新摸索）。
状态截至 2026-11-17；盒子上的实际情况以 `docker ps`、`docker inspect` 为准，与本文不符时先核实再动手，并更新本文。

---

## 1. 一句话

派克盒子是一台**平时离线**的 NVIDIA GB10（aarch64）单机，同时跑模型（GLM-OCR、Qwen）和整套新应用栈（`new_doc_parse` 分支）。
盒子连不上 Docker Hub、pip 源，**所有更新都是在本地打好包，拷进去执行**。

## 2. 网络与访问

| 项 | 值 |
|---|---|
| 主机名 / 用户 | `promaxgb10-085a` / `yzling` |
| 生产内网 IP | **192.168.70.161** —— LIMS、OAPI 脚本、用户访问都用它 |
| 临时外网 IP | 192.168.185.236（盒子被拿到外网时，网卡 `wlP9s9`）|
| SSH | 只用公钥：`ssh yzling@192.168.70.161`。sudo 需要密码，AI 不代输，交给用户 |
| 本地电脑注意 | 开发机装了代理 TUN（网卡 198.18.0.1），会吞掉 192.168.x 的 SSH，报 `kex_exchange_identification: Connection closed`。连盒子前关 TUN 或把 192.168.0.0/16 设为直连 |

## 3. 架构

```text
LIMS (OAPI 脚本) ──HTTP──▶ 192.168.70.161:18080  web（nginx，hanson-web-1）
                                 ├─ /                 前端页面（来自 ./web-dist 挂载）
                                 ├─ /api/v1/integration/...  一站式对接 ─┐
                                 └─ /v1/...           平台 API        ─┤
                                                                       ▼
                          18000  api-gateway ─▶ orchestration / ocr / agent / sandbox /
                                                recipe-registry / review   （同一个镜像 hanson-new-app:local）
                                                postgres · redis · minio （仅 127.0.0.1 端口）
                                 │  容器内经 host.docker.internal 访问宿主机模型
                                 ▼
宿主机：9977 GLM-OCR（vLLM，max-num-seqs 2）
        9988 Qwen3.6-35B-A3B-FP8（vLLM）
        9979 版面 PP-DocLayoutV3（容器 hanson-layout，CPU，跑在旧镜像 hansondoc-backend:latest 里）
```

### 端口

| 端口 | 服务 | 对外 |
|---|---|---|
| 18080 | web：页面 + `/api/v1/integration` + `/v1` 代理 | 是（LIMS 用这个）|
| 18000 | api-gateway | 是 |
| 9977 / 9988 | GLM-OCR / Qwen（vLLM，宿主机进程）| 是 |
| 9979 | 版面服务（容器 hanson-layout）| 是 |
| 15432 / 16379 / 19000 / 19001 | postgres / redis / minio | 仅本机 |

### 目录

```text
~/hanson-deploy/
├── deploy-package/              # 新栈（compose 项目名 hanson），2026-11-15 从汉唐 01 拷来
│   ├── docker-compose.yml       # 只用镜像不构建；派克改过三处，见第 4 节
│   ├── .env                     # 派克自己的密钥 + 模型地址（host.docker.internal）。不要打印、不要覆盖
│   ├── web-nginx.conf           # web 容器的 nginx 配置（含 LIMS iframe 嵌 PDF 的放行）
│   ├── web-dist/                # 前端构建产物，挂载进 web 容器
│   ├── data/orchestration/dictionary/   # 业务词典（派克版；汉唐原版备份为 business_dictionary.hanson.json）
│   ├── data/recipe_registry/    # 配方与解析内核资产（parser_core stable=1.7.901）
│   └── scripts/                 # 部署包自带脚本（start/stop/status/smoke-test/reset-tasks）
├── backups/                     # 离线更新脚本的备份，每次部署一个时间戳目录 + history.log
└── paike/                       # 派克词典等原始文件

~/hansonDoc_RAG/                 # 老项目。容器已停（restart=no），数据卷保留，不要删
└── scripts/start_all.sh | stop_all.sh | start_containers.sh   # 已改写为驱动新栈（原版 *.old-hansondoc）
    scripts/start_glm_ocr.sh | start_qwen36.sh                  # 模型启动脚本
```

### 镜像

| 镜像 | 用途 |
|---|---|
| `hanson-new-app:local` | 7 个应用服务共用。离线更新会重新生成它 |
| `hanson-new-app:base` | 第一次离线更新时由当时的 `:local` 打的标签；之后每次都在它上面叠一层新代码 |
| `hanson-new-app:bak-<时间>` | 每次更新前的旧镜像，回滚用 |
| `hanson-web:local` | nginx；页面和配置都来自挂载，镜像本身基本不用换 |
| `hanson-sandbox-runtime:local`、`postgres:16-alpine`、redis、minio | 基础组件 |
| `hansondoc-backend:latest` | **老镜像，版面服务 hanson-layout 在用，绝对不能删** |

### 启停

```bash
bash ~/hansonDoc_RAG/scripts/start_all.sh     # 起容器 + 自检（模型需单独起）
bash ~/hansonDoc_RAG/scripts/stop_all.sh      # 停容器，数据保留；--with-models 连模型一起停
```

模型（9977、9988）是在盒子桌面终端里手动起的，**不是 systemd，重启盒子后不会自己起来**：
`~/hansonDoc_RAG/scripts/start_glm_ocr.sh`、`~/hansonDoc_RAG/scripts/start_qwen36.sh`。内存紧（空闲约 11GB），不要随意加并发。

## 4. 与仓库、与汉唐 01 的差异

| 项 | 仓库 `new_app/deploy/compose` | 汉唐 01 | 派克 |
|---|---|---|---|
| compose | 带 build，web 端口 15173 | deploy-package，18000/18080 | 同 01，另加：`extra_hosts: host.docker.internal:host-gateway`、`./web-nginx.conf` 挂载、`./web-dist` 挂载 |
| 前端 | 打进 `hanson-web` 镜像 | 打进镜像（未挂载 web-dist）| **挂载 `./web-dist`**，替换文件即可 |
| 模型 | — | 01 跑 GLM/版面（systemd），02 跑 Qwen | 全在本机，手动起 |
| 词典 / 解析内核 | 汉唐 | 汉唐，parser 1.7.40 | **派克词典**，parser 1.7.900 → **1.7.901**（多大类拆条）|

派克 compose 改动前的备份：`docker-compose.yml.from-01`、`docker-compose.yml.before-extract`。

## 5. 日常更新流程（开发者照做）

### 5.1 本地

先把改动提交到 `wjh-doc_parse`，然后在 **cmd / PowerShell** 里（也可以双击 `make_bundle.cmd`，默认打 all）：

```bat
cd /d F:\work\RAG_doc_parse
new_app\deploy\offline\make_bundle.cmd web     &rem 只改了前端
new_app\deploy\offline\make_bundle.cmd app     &rem 只改了后端 Python
new_app\deploy\offline\make_bundle.cmd         &rem 都改了（all）
```

在 cmd 里**不要直接敲 `bash ...`**：那会调用 WSL 的 bash（报 `execvpe(/bin/bash) failed`），`make_bundle.cmd` 会自己找 Git Bash。
在 Git Bash 终端里则可以直接 `bash new_app/deploy/offline/make_bundle.sh web`（路径写 `/f/work/...`）。

产物在 `new_app/deploy/offline/out/hanson-update-<时间>-<提交>-<web|app|all>.run`，一个文件，约 0.2MB（web）到 10MB（all）。
包名带 `-dirty` 表示打包时有未提交的改动 —— 能用，但盒子上就对不上 git 提交了，尽量先提交。

### 5.2 拷到盒子

- 电脑在内网且能 SSH：`scp new_app/deploy/offline/out/<包名>.run yzling@192.168.70.161:~/`
- 否则用 U 盘，在盒子上 `cp /media/yzling/*/<包名>.run ~/`

### 5.3 盒子上执行

```bash
bash ~/<包名>.run              # 部署
bash ~/<包名>.run rollback     # 出问题就回滚（任意一个 .run 文件都能回滚）
```

脚本做的事（顺序很重要：**先检查，后动手**）：

1. 校验包完整、部署目录与 docker 可用；
2. 含后端时：若有解析任务未结束 → 拒绝（重启会中断任务，`FORCE=1` 可强制）；若 `requirements.txt` 与镜像不同 → 拒绝（见 6.3）；
3. 含新的数据库迁移时：先 `pg_dump` 到备份目录（迁移在 orchestration 启动时自动执行，回滚镜像退不回表结构）；
4. 备份旧镜像标签 / 旧 `web-dist` 到 `~/hanson-deploy/backups/<时间>/`；
5. 后端：`FROM hanson-new-app:base` 覆盖 `services/ packages/ tests/` 生成新的 `:local`，`docker compose up -d --no-build --pull never`；
6. 前端：替换 `web-dist`，`docker restart hanson-web-1`；
7. 等网关、页面 `/healthz` 返回 200，打印容器状态和前端版本号（`index-xxxx.js`）。

验证：浏览器打开 `http://192.168.70.161:18080`，**Ctrl+F5** 强刷，确认改动生效；LIMS 里点一次「结果审核」看嵌入页正常。

## 6. 各类改动怎么上盒子

| 改了什么 | 怎么部署 |
|---|---|
| `new_app/web/**` | `make_bundle.sh web` |
| `new_app/services/**`、`packages/**`、`tests/**` | `make_bundle.sh app`（解析任务空闲时做）|
| `deploy/compose/nginx.conf` | 脚本不管。盒子用的是 `deploy-package/web-nginx.conf`，手工对比合并后 `docker restart hanson-web-1` |
| `.env`、`docker-compose.yml` | 脚本不管。手工改，先 `cp x x.before-<改动名>` 备份，再 `docker compose -p hanson --env-file .env -f docker-compose.yml up -d --no-build --pull never` |
| 业务词典 / 解析内核（parser_core）| 走 recipe-registry 的发布接口，发**新的 semver 版本**再 promote 到 stable，见 6.2 |
| `requirements.txt`（新增依赖）| 见 6.3 |
| 模型参数 | 改 `~/hansonDoc_RAG/scripts/start_*.sh`，在盒子桌面终端重启模型 |

### 6.1 前端挂载（其他盒子想用同样的前端更新方式）

在该盒子 `docker-compose.yml` 的 `web:` 服务加：

```yaml
    volumes:
      - ./web-dist:/usr/share/nginx/html:ro
```

并先把当前前端拷出来：`docker cp hanson-web-1:/usr/share/nginx/html ./web-dist`，再 `up -d web`。

### 6.2 词典 / 解析内核

- 派克词典来源：LIMS 导出的 `业务词表new.txt` → 转换脚本 `F:\work\汉唐标准拆分\派克词典转换\build_paike_dictionary.py` → `business_dictionary.paike.json`、`dictionary_data.json`（parser 资产内的词典用 `new_app/scripts/assets/build_dictionary_asset.py` 生成）。
- 资产版本不可变：每次发布新版本号（1.7.901 → 1.7.902…），通过 recipe-registry `:8005` 的 `/internal/assets` 发布、`/internal/assets/parser/parser_core/versions/{v}/promote` 晋级到 stable。
- 改了 parser 代码后，派克要基于新代码**重新发一版带派克词典的内核**，否则派克仍用旧代码。
- 这一步建议让 AI 做（需要盒子在线或 AI 生成一个专用 .run 脚本）。

### 6.3 新增 Python 依赖

离线覆盖代码装不了新依赖，`.run` 会拒绝。做法：在能上网的电脑下载 aarch64 的 wheel：

```bash
pip download -r new_app/requirements.txt --platform manylinux2014_aarch64 --python-version 3.12 --only-binary=:all: -d wheels
```

拷到盒子后基于 `hanson-new-app:base` 构建新的基底（`COPY wheels /wheels` + `pip install --no-index --find-links /wheels -r requirements.txt`），打标签为新的 `hanson-new-app:base`（旧基底先另打标签保留），再正常跑 `.run`。

## 7. 怎么写 / 改离线部署脚本

脚本都在 `new_app/deploy/offline/`：

| 文件 | 运行位置 | 作用 |
|---|---|---|
| `make_bundle.sh` + `make_bundle.cmd` | 本地（cmd 用 .cmd，Git Bash 用 .sh）| 构建前端、打包后端代码，把 `install.sh` + 负载拼成一个 `.run` |
| `install.sh` | 盒子 | `.run` 的头部：检查 → 备份 → 更新 → 验证；`rollback` 回滚 |
| `selftest.sh` | 本地 Git Bash | 假 docker + 假服务，跑部署 / 回滚 / 各项拦截，**改完脚本必须跑通** |

`.run` 结构：`install.sh` 文本 + 一行 `__PAYLOAD__` + tar.gz（`BUNDLE_INFO`、`web-dist.tgz`、`app-src.tgz`）。脚本在标记前 `exit`，所以 bash 不会读到二进制部分。

要支持一种新的更新内容（例如 nginx 配置、词典文件）时：

1. **make_bundle.sh**：加一个分支，把文件打进 `$WORK/<名字>.tgz`；
2. **install.sh 检查段**：先校验（文件存在、格式正确、目标路径对），任何不满足就 `die`，此时还没改动任何东西；
3. **install.sh 执行段**：把要被替换的东西先移/拷进 `$bk`，再替换，再重启**受影响的最少容器**；
4. **do_rollback**：按 `$bk` 里有什么就还原什么，与执行段一一对应；
5. **selftest.sh**：加一组用例（成功、被拦截、回滚）；`bash new_app/deploy/offline/selftest.sh <*-all.run>` 全部通过再用；
6. 更新本文第 6 节表格。

铁律：不碰 `.env`、`data/` 下的业务数据、数据库卷、minio 卷、模型进程、`hanson-layout`、`hansondoc-backend:latest`；能只重启 web 就不重启后端；后端重启前确认没有进行中的解析任务。

## 8. 排障

| 现象 | 处理 |
|---|---|
| `kex_exchange_identification: Connection closed` | 本地代理 TUN 吞了 SSH，见第 2 节 |
| 页面没变化 | Ctrl+F5；`curl -s localhost:18080/ \| grep -o 'index-[^"]*js'` 看实际版本 |
| 上传后 OCR / 抽取阶段失败 | 模型没起：`ss -ltnp \| grep -E ':9977\|:9988'`，没有就去桌面终端起模型 |
| `.run` 报 requirements 不同 | 见 6.3 |
| 网关不就绪 | `docker logs --tail 80 hanson-orchestration-1`、`hanson-api-gateway-1`；必要时 `bash <包>.run rollback` |
| 备份占空间 | `~/hanson-deploy/backups/` 下旧目录可删；旧镜像 `docker rmi hanson-new-app:bak-<时间>`（别删 `:base`、`:local`）|

## 9. 相关资料（仓库外）

- 派克 OAPI 替换脚本：`F:\work\汉唐标准拆分\OAPI替换脚本_派克新系统\`
- 清理旧 AI 表 SQL：`F:\work\汉唐标准拆分\拆分自动化_派克\清理AI表并导入新建标准.sql`
- 词典转换：`F:\work\汉唐标准拆分\派克词典转换\`（`歧义别名清单.csv` 中 80 个歧义别名待业务确认）
- 一站式对接接口：`new_app/services/api_gateway/main.py`（`/api/v1/integration/upload`、`tasks/{id}/status|result|retrigger`）
